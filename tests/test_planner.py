"""Tests for the planner (no Home Assistant needed)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "heatshift"))

from planner import (  # noqa: E402
    cheapest_block,
    current_slot,
    entity_fits_mode,
    offset_for_position,
    offset_plan,
    parse_prices,
    price_position,
    thermostat_setpoint,
)

TZ = timezone(timedelta(hours=1))
DAY = date(2026, 11, 10)


def frank_attributes(prices: list[float]) -> dict:
    """Build Frank Energie style attributes with quarter prices from midnight."""
    start = datetime.combine(DAY, time(0, 0), tzinfo=TZ)
    entries = []
    for index, price in enumerate(prices):
        begin = start + timedelta(minutes=15 * index)
        entries.append(
            {
                "from": begin.isoformat(),
                "till": (begin + timedelta(minutes=15)).isoformat(),
                "total_price_eur_kwh": price,
            }
        )
    return {"prices": entries}


def test_parse_frank_format() -> None:
    slots = parse_prices(frank_attributes([0.3, 0.4]))
    assert len(slots) == 2
    assert slots[0].price == 0.3
    assert slots[1].start == datetime(2026, 11, 10, 0, 15, tzinfo=TZ)


def test_parse_start_value_format_without_end() -> None:
    attributes = {
        "raw_today": [
            {"start": "2026-11-10T00:00:00+01:00", "value": 0.2},
            {"start": "2026-11-10T01:00:00+01:00", "value": 0.3},
        ]
    }
    slots = parse_prices(attributes)
    assert slots[0].end == slots[1].start
    assert slots[1].end - slots[1].start == timedelta(minutes=15)


def test_parse_ignores_bad_entries() -> None:
    assert parse_prices({"prices": [{"from": "x", "total_price_eur_kwh": 1}]}) == []
    assert parse_prices({}) == []


def test_offset_matches_current_automation() -> None:
    # Expensive from 65% of the day range gives -2, the rest 0.
    assert offset_for_position(0.65, 65, -2, 15, 0) == -2
    assert offset_for_position(0.64, 65, -2, 15, 0) == 0
    assert offset_for_position(0.0, 65, -2, 15, 0) == 0
    assert offset_for_position(0.1, 65, -2, 15, 1) == 1
    assert offset_for_position(0.1, 65, -2, 0, 1) == 0
    assert offset_for_position(None, 65, -2, 15, 1) == 0


def test_flat_prices_give_no_position() -> None:
    slots = parse_prices(frank_attributes([0.5] * 4))
    assert price_position(slots, 0.5) is None


def test_offset_plan_and_current_slot() -> None:
    prices = [0.2] * 40 + [0.8] * 16 + [0.4] * 40
    slots = parse_prices(frank_attributes(prices))
    plan = offset_plan(slots, DAY, 65, -2, 15, 1)
    assert len(plan) == 96
    assert plan[0][1] == 1
    assert plan[45][1] == -2
    assert plan[80][1] == 0
    now = datetime(2026, 11, 10, 10, 5, tzinfo=TZ)
    assert current_slot(slots, now).price == 0.8


def test_cheapest_block_in_window() -> None:
    prices = [0.5] * 96
    # 13:15 to 14:15 is cheapest.
    for index in range(53, 57):
        prices[index] = 0.1
    # Cheaper, but outside the window (08:00).
    for index in range(32, 36):
        prices[index] = 0.01
    slots = parse_prices(frank_attributes(prices))
    block = cheapest_block(slots, DAY, time(10, 0), time(16, 0), 60)
    assert block is not None
    assert block.start == datetime(2026, 11, 10, 13, 15, tzinfo=TZ)
    assert block.end == datetime(2026, 11, 10, 14, 15, tzinfo=TZ)
    assert abs(block.average - 0.1) < 1e-9


def test_cheapest_block_ends_by_window_end() -> None:
    prices = [0.5] * 96
    for index in range(61, 64):  # 15:15 to 16:00, block would run past 16:00
        prices[index] = 0.01
    slots = parse_prices(frank_attributes(prices))
    block = cheapest_block(slots, DAY, time(10, 0), time(16, 0), 60)
    assert block is not None
    assert block.end <= datetime(2026, 11, 10, 16, 0, tzinfo=TZ)
    assert block.start == datetime(2026, 11, 10, 15, 0, tzinfo=TZ)


def test_cheapest_block_with_hourly_prices() -> None:
    start = datetime.combine(DAY, time(0, 0), tzinfo=TZ)
    entries = [
        {"start": (start + timedelta(hours=h)).isoformat(), "end": (start + timedelta(hours=h + 1)).isoformat(), "value": 0.5 if h != 12 else 0.1}
        for h in range(24)
    ]
    slots = parse_prices({"raw_today": entries})
    block = cheapest_block(slots, DAY, time(10, 0), time(16, 0), 60)
    assert block.start == datetime(2026, 11, 10, 12, 0, tzinfo=TZ)


def test_no_block_without_prices() -> None:
    assert cheapest_block([], DAY, time(10, 0), time(16, 0), 60) is None


def test_thermostat_setpoint_rounds_and_limits() -> None:
    assert thermostat_setpoint(20.5, -1, 17, 23) == 19.5
    assert thermostat_setpoint(20.5, 0.5, 17, 23) == 21.0
    assert thermostat_setpoint(20.3, 0, 17, 23) == 20.5
    assert thermostat_setpoint(17.5, -1, 17, 23) == 17
    assert thermostat_setpoint(22.5, 1, 17, 23) == 23


def test_entity_fits_mode() -> None:
    # Daikin Altherma offset entity: -10 to 10
    assert entity_fits_mode("offset", -10, 10)
    assert not entity_fits_mode("thermostat", -10, 10)
    # Typical room thermostat: 5 to 30
    assert entity_fits_mode("thermostat", 5, 30)
    assert not entity_fits_mode("offset", 5, 30)
    assert not entity_fits_mode("offset", None, 10)


from planner import (  # noqa: E402
    REASON_CHEAP,
    REASON_DIP_NOT_CHEAP,
    REASON_EXPENSIVE,
    REASON_NORMAL,
    REASON_PEAK_NOT_EXPENSIVE,
    REASON_SMALL_SPREAD,
    decide,
    reference_from_history,
)

COSTS = [0.08, 0.09, 0.10, 0.12, 0.14]


def _d(cost, reference, day=COSTS, cheap_offset=1):
    return decide(cost, day, reference, 65, -2, 15, cheap_offset, 20, 20)


def test_expensive_peak_above_normal_is_lowered() -> None:
    d = _d(0.14, 0.10)
    assert d.change == -2 and d.reason == REASON_EXPENSIVE
    assert abs(d.vs_reference - 0.4) < 1e-9


def test_peak_that_is_still_cheap_is_not_lowered() -> None:
    # Whole day cheap: the peak of the day is below the normal price.
    d = _d(0.14, 0.20)
    assert d.change == 0 and d.reason == REASON_PEAK_NOT_EXPENSIVE


def test_small_spread_does_nothing() -> None:
    d = _d(0.302, 0.20, day=[0.30, 0.301, 0.302])
    assert d.change == 0 and d.reason == REASON_SMALL_SPREAD


def test_cheap_dip_below_normal_is_raised() -> None:
    d = _d(0.08, 0.12)
    assert d.change == 1 and d.reason == REASON_CHEAP


def test_dip_above_normal_is_not_raised() -> None:
    d = _d(0.08, 0.07)
    assert d.change == 0 and d.reason == REASON_DIP_NOT_CHEAP


def test_dip_without_cheap_offset_is_normal() -> None:
    d = _d(0.08, 0.12, cheap_offset=0)
    assert d.change == 0 and d.reason == REASON_NORMAL


def test_reference_needs_three_days() -> None:
    today = date(2026, 11, 11)
    daily = {"2026-11-09": 0.1, "2026-11-10": 0.2}
    assert reference_from_history(daily, today, 7) is None
    daily["2026-11-08"] = 0.3
    daily["2026-11-11"] = 9.9  # today is ignored
    assert abs(reference_from_history(daily, today, 7) - 0.2) < 1e-9
    assert reference_from_history(daily, today, 2) is None
    daily["2026-11-07"] = 0.4
    assert abs(reference_from_history(daily, today, 3) - 0.2) < 1e-9
