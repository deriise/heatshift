"""Price parsing and planning for HeatShift.

This module has no Home Assistant imports, so it can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Mapping

# Attribute names under which price integrations publish their price list.
LIST_ATTRIBUTES = ("prices", "raw_today", "prices_today", "data", "forecast")
START_KEYS = ("from", "start", "start_time", "starts_at", "timestamp")
END_KEYS = ("till", "end", "end_time", "ends_at")
PRICE_KEYS = ("total_price_eur_kwh", "price", "value", "total", "electricity_price")

DEFAULT_SLOT = timedelta(minutes=15)


@dataclass(frozen=True)
class PriceSlot:
    """One price period."""

    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class Block:
    """A run of consecutive slots."""

    start: datetime
    end: datetime
    average: float


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _first(entry: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in entry and entry[key] is not None:
            return entry[key]
    return None


def parse_prices(attributes: Mapping[str, Any]) -> list[PriceSlot]:
    """Read a list of price slots from a sensor's attributes.

    Works with Frank Energie (`prices` with `from`/`till`/`total_price_eur_kwh`)
    and with integrations that use `start`/`end`/`value` style entries.
    Entries that cannot be read are skipped. The result is sorted by start.
    """
    raw: list[Any] = []
    for name in LIST_ATTRIBUTES:
        value = attributes.get(name)
        if isinstance(value, list) and value and isinstance(value[0], Mapping):
            raw = value
            break

    parsed: list[tuple[datetime, datetime | None, float]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        start = _to_datetime(_first(entry, START_KEYS))
        price = _first(entry, PRICE_KEYS)
        if start is None or price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        parsed.append((start, _to_datetime(_first(entry, END_KEYS)), price))

    parsed.sort(key=lambda item: item[0])
    slots: list[PriceSlot] = []
    for index, (start, end, price) in enumerate(parsed):
        if end is None:
            if index + 1 < len(parsed):
                end = parsed[index + 1][0]
            else:
                end = start + DEFAULT_SLOT
        slots.append(PriceSlot(start=start, end=end, price=price))
    return slots


def slots_for_day(slots: list[PriceSlot], day: date) -> list[PriceSlot]:
    """Slots that start on the given local day."""
    return [slot for slot in slots if slot.start.date() == day]


def current_slot(slots: list[PriceSlot], now: datetime) -> PriceSlot | None:
    """The slot that contains `now`."""
    for slot in slots:
        if slot.start <= now < slot.end:
            return slot
    return None


def price_position(day_slots: list[PriceSlot], price: float) -> float | None:
    """Where a price sits in the day's range: 0 is cheapest, 1 is most expensive."""
    if not day_slots:
        return None
    low = min(slot.price for slot in day_slots)
    high = max(slot.price for slot in day_slots)
    if high <= low:
        return None
    return (price - low) / (high - low)


def offset_for_position(
    position: float | None,
    expensive_threshold: float,
    expensive_offset: float,
    cheap_threshold: float,
    cheap_offset: float,
) -> float:
    """Pick the change for a price position.

    Used for both modes: an offset on the leaving water temperature, or a
    change of the room setpoint. Thresholds are percentages (0 to 100).
    Without a usable position the result is 0, so nothing is shifted.
    """
    if position is None:
        return 0
    if position >= expensive_threshold / 100:
        return expensive_offset
    if cheap_threshold > 0 and position <= cheap_threshold / 100:
        return cheap_offset
    return 0


def offset_plan(
    slots: list[PriceSlot],
    day: date,
    expensive_threshold: float,
    expensive_offset: float,
    cheap_threshold: float,
    cheap_offset: float,
) -> list[tuple[PriceSlot, float]]:
    """Offset for every slot of the day."""
    day_slots = slots_for_day(slots, day)
    return [
        (
            slot,
            offset_for_position(
                price_position(day_slots, slot.price),
                expensive_threshold,
                expensive_offset,
                cheap_threshold,
                cheap_offset,
            ),
        )
        for slot in day_slots
    ]


def cheapest_block(
    slots: list[PriceSlot],
    day: date,
    window_start: time,
    window_end: time,
    block_minutes: int,
) -> Block | None:
    """Cheapest run of consecutive slots of `block_minutes` inside the window.

    The block must start at or after `window_start` and end at or before
    `window_end` on the given day. The average is weighted by slot length.
    """
    length = timedelta(minutes=block_minutes)
    day_slots = slots_for_day(slots, day)
    best: Block | None = None

    for first_index, first in enumerate(day_slots):
        if first.start.time() < window_start:
            continue
        block_end = first.start + length
        tz = first.start.tzinfo
        if block_end > datetime.combine(day, window_end, tzinfo=tz):
            continue

        covered = timedelta(0)
        weighted = 0.0
        previous_end = first.start
        for slot in day_slots[first_index:]:
            if slot.start != previous_end or covered >= length:
                break
            part = min(slot.end, block_end) - slot.start
            weighted += slot.price * part.total_seconds()
            covered += part
            previous_end = slot.end

        if covered < length:
            continue
        average = weighted / length.total_seconds()
        if best is None or average < best.average:
            best = Block(start=first.start, end=block_end, average=average)

    return best


def thermostat_setpoint(base: float, delta: float, minimum: float, maximum: float) -> float:
    """Room setpoint for a change, rounded to 0.5 and kept within the limits."""
    value = round((base + delta) * 2) / 2
    return max(minimum, min(maximum, value))


def entity_fits_mode(mode: str, min_temp: float | None, max_temp: float | None) -> bool:
    """Check that a climate entity looks like an offset or a room thermostat.

    An offset entity has a range around 0 (for example -10 to 10). A room
    thermostat has a range that reaches normal room temperatures. This stops
    a room thermostat from being set to an offset value like -2 °C.
    """
    if min_temp is None or max_temp is None:
        return False
    if mode == "offset":
        return min_temp < 0 < max_temp and max_temp <= 15
    if mode == "thermostat":
        return min_temp >= 0 and max_temp >= 18
    return False
