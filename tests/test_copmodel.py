"""Tests for the COP model (no Home Assistant needed)."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "heatshift"))

from copmodel import (  # noqa: E402
    CopModel,
    LearnedCorrection,
    carnot_cop,
    defrost_factor,
    heat_kw,
)


def test_cop_rises_with_outdoor_temperature() -> None:
    assert carnot_cop(10, 35) > carnot_cop(0, 35) > carnot_cop(-10, 35)


def test_cop_falls_with_leaving_water_temperature() -> None:
    assert carnot_cop(5, 35) > carnot_cop(5, 55)


def test_defrost_peaks_around_two_degrees_in_humid_air() -> None:
    assert defrost_factor(2, 95) < defrost_factor(2, 50)
    assert defrost_factor(2, 95) < defrost_factor(10, 95)
    assert defrost_factor(-10, 95) == 1


def test_datasheet_points_are_matched() -> None:
    model = CopModel(cop_a7=4.85, cop_a2=3.50)
    assert abs(model.estimate(7, 35) - 4.85) < 1e-9
    assert abs(model.estimate(2, 35) - 3.50) < 1e-9
    assert model.estimate(2, 55) < 3.50
    assert 3.50 < model.estimate(4.5, 35) < 4.85


def test_estimate_without_datasheet_is_plausible() -> None:
    model = CopModel()
    assert 2.5 < model.estimate(7, 35, 70) < 6
    assert 1.5 < model.estimate(2, 55, 95) < 3.5


def test_heat_from_flow() -> None:
    # 20 l/min with 5 K difference: 0.333 kg/s * 4.186 * 5 = 6.98 kW
    assert abs(heat_kw(20, 35, 30) - 6.977) < 0.01
    assert heat_kw(20, 30, 35) == 0


def test_learning_corrects_the_estimate() -> None:
    model = CopModel(cop_a7=4.85, cop_a2=3.50)
    learned = LearnedCorrection()
    assert learned.cop(model, 2, 35, None) == model.estimate(2, 35)
    # The unit really does 20% better than the datasheet at 2 °C.
    power = 1.5
    target_heat = power * model.estimate(2, 35) * 1.2
    flow = target_heat / (4.186 * 5) * 60
    for _ in range(60):
        learned.add_sample(model, 2, None, 35, 30, flow, power, 1 / 60)
    assert abs(learned.cop(model, 2, 35, None) / model.estimate(2, 35) - 1.2) < 0.01
    # Neighbouring temperatures borrow the correction.
    assert learned.factor(3) is not None
    # Far away temperatures do not.
    assert learned.factor(15) is None


def test_learning_skips_idle_samples() -> None:
    model = CopModel()
    learned = LearnedCorrection()
    assert not learned.add_sample(model, 5, None, 35, 30, 20, 0.05, 1 / 60)
    assert not learned.add_sample(model, 5, None, 30, 30, 20, 1.5, 1 / 60)


def test_store_round_trip() -> None:
    learned = LearnedCorrection(bins={2: [10.0, 8.0, 3.0]})
    restored = LearnedCorrection.from_dict(learned.to_dict())
    assert restored.bins == learned.bins
    assert LearnedCorrection.from_dict(None).bins == {}
