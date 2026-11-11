"""COP estimation and learning for HeatShift.

No Home Assistant imports, so this module can be tested on its own.

The estimate starts from physics (a fraction of the Carnot efficiency) or,
when the user enters them, from two datasheet points at 35 °C leaving water.
Measured data (flow, supply and return temperature, electrical power) then
corrects that estimate per degree of outdoor temperature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KELVIN = 273.15
# Fraction of the Carnot COP that a typical air-to-water heat pump reaches.
CARNOT_EFFICIENCY = 0.5
# Temperature differences of the heat exchangers.
CONDENSER_LIFT = 5.0
EVAPORATOR_DROP = 6.0
# Defrost penalty: largest around 2 °C in humid air, none below -7 or above 7 °C.
DEFROST_PEAK = 0.12
DEFROST_CENTER = 2.0
DEFROST_WIDTH = 5.0

COP_MIN = 1.0
COP_MAX = 8.0
DATASHEET_LWT = 35.0
WATER_KJ_PER_KG_K = 4.186

# Learning
BIN_MIN = -15
BIN_MAX = 25
MIN_BIN_ENERGY_KWH = 0.5
DECAY_AT_KWH = 20.0
MIN_POWER_KW = 0.2


def carnot_cop(outdoor: float, lwt: float) -> float:
    """Physics-based COP for an outdoor and leaving water temperature."""
    hot = lwt + CONDENSER_LIFT + KELVIN
    cold = outdoor - EVAPORATOR_DROP + KELVIN
    lift = max(hot - cold, 5.0)
    return _clamp(CARNOT_EFFICIENCY * hot / lift)


def defrost_factor(outdoor: float, humidity: float | None) -> float:
    """Share of the COP that remains after defrost losses (1.0 = no loss)."""
    closeness = max(0.0, 1 - abs(outdoor - DEFROST_CENTER) / DEFROST_WIDTH)
    if humidity is None:
        wetness = 0.5
    else:
        wetness = min(1.0, max(0.0, (humidity - 60) / 30))
    return 1 - DEFROST_PEAK * closeness * wetness


def _clamp(value: float) -> float:
    return max(COP_MIN, min(COP_MAX, value))


@dataclass
class CopModel:
    """Estimate of the COP, optionally anchored on two datasheet points."""

    cop_a7: float | None = None
    cop_a2: float | None = None

    @property
    def has_datasheet(self) -> bool:
        """Whether both datasheet points are known."""
        return bool(self.cop_a7 and self.cop_a2)

    def estimate(self, outdoor: float, lwt: float, humidity: float | None = None) -> float:
        """Estimated COP at an outdoor and leaving water temperature."""
        if self.has_datasheet:
            # Linear through A2/W35 and A7/W35. These points already include
            # defrost, so no extra penalty. Beyond the points the slope is kept
            # but limited, as real curves flatten out.
            slope = (self.cop_a7 - self.cop_a2) / 5.0
            clamped = min(max(outdoor, -10.0), 15.0)
            if clamped <= 7.0:
                base = self.cop_a2 + slope * (clamped - 2.0)
            else:
                # Above 7 °C there is no defrost left to win: half the slope.
                base = self.cop_a7 + slope * 0.5 * (clamped - 7.0)
            # Correct for the leaving water temperature with the physics ratio.
            ratio = carnot_cop(outdoor, lwt) / carnot_cop(outdoor, DATASHEET_LWT)
            return _clamp(base * ratio)
        return _clamp(carnot_cop(outdoor, lwt) * defrost_factor(outdoor, humidity))


def heat_kw(flow_l_per_min: float, supply: float, return_: float) -> float:
    """Heat output in kW from flow and the temperature difference."""
    kg_per_s = flow_l_per_min / 60.0
    return max(0.0, kg_per_s * WATER_KJ_PER_KG_K * (supply - return_))


@dataclass
class LearnedCorrection:
    """Measured COP divided by the estimate, per degree of outdoor temperature."""

    # Per bin: [measured heat kWh, estimated heat kWh, electricity kWh]
    bins: dict[int, list[float]] = field(default_factory=dict)

    @staticmethod
    def bin_for(outdoor: float) -> int:
        """Bin index for an outdoor temperature."""
        return int(round(max(BIN_MIN, min(BIN_MAX, outdoor))))

    def add_sample(
        self,
        model: CopModel,
        outdoor: float,
        humidity: float | None,
        supply: float,
        return_: float,
        flow_l_per_min: float,
        power_kw: float,
        hours: float,
    ) -> bool:
        """Add one measurement. Returns False when it was skipped."""
        if power_kw < MIN_POWER_KW or flow_l_per_min <= 0 or supply <= return_:
            return False
        measured_heat = heat_kw(flow_l_per_min, supply, return_) * hours
        expected_heat = power_kw * model.estimate(outdoor, supply, humidity) * hours
        if measured_heat <= 0 or expected_heat <= 0:
            return False
        entry = self.bins.setdefault(self.bin_for(outdoor), [0.0, 0.0, 0.0])
        entry[0] += measured_heat
        entry[1] += expected_heat
        entry[2] += power_kw * hours
        # Forget old data slowly, so the curve follows changes in the system.
        if entry[2] > DECAY_AT_KWH:
            entry[:] = [value * 0.5 for value in entry]
        return True

    def factor(self, outdoor: float) -> float | None:
        """Correction for an outdoor temperature, from that bin or its neighbours."""
        center = self.bin_for(outdoor)
        heat = expected = electric = 0.0
        for distance in (0, 1, 2):
            for index in {center - distance, center + distance}:
                entry = self.bins.get(index)
                if entry:
                    heat += entry[0]
                    expected += entry[1]
                    electric += entry[2]
            if expected > 0 and electric >= MIN_BIN_ENERGY_KWH:
                return heat / expected
        return None

    def measured_cop(self, outdoor: float) -> float | None:
        """Average measured COP in the bin of this outdoor temperature."""
        entry = self.bins.get(self.bin_for(outdoor))
        if not entry or entry[2] < MIN_BIN_ENERGY_KWH:
            return None
        return entry[0] / entry[2]

    def cop(self, model: CopModel, outdoor: float, lwt: float, humidity: float | None) -> float:
        """Estimated COP, corrected with measurements when there are enough."""
        estimate = model.estimate(outdoor, lwt, humidity)
        factor = self.factor(outdoor)
        if factor is None:
            return estimate
        return _clamp(estimate * max(0.5, min(1.5, factor)))

    def to_dict(self) -> dict[str, Any]:
        """Data to store."""
        return {"bins": {str(key): value for key, value in self.bins.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LearnedCorrection:
        """Restore stored data."""
        bins: dict[int, list[float]] = {}
        for key, value in ((data or {}).get("bins") or {}).items():
            try:
                bins[int(key)] = [float(value[0]), float(value[1]), float(value[2])]
            except (TypeError, ValueError, IndexError):
                continue
        return cls(bins=bins)
