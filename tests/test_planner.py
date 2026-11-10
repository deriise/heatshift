"""Tests for the planner (no Home Assistant needed)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "heatshift"))

from planner import (  # noqa: E402
    cheapest_block,
    current_slot,
    offset_for_position,
    offset_plan,
    parse_prices,
    price_position,
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
