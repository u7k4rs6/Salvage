"""Sim clock.

Architecture section 9: "a monotonic integer that the runner advances; every component takes
now() from it. Speed is arbitrary, so a full evaluation day runs in seconds."

Not listed in the section 13 layout; see docs/BUILD_LOG.md. It is here rather than in runner.py
because the traffic generator, the fault schedule and the detector all need the same IST
arithmetic and nothing else in runner.py is reusable.
"""

from __future__ import annotations

from dataclasses import dataclass

DAY_SECONDS = 86400
HOUR_SECONDS = 3600
MINUTE_SECONDS = 60


class SimClock:
    """A monotonic integer clock in Unix seconds. Advances only forward."""

    def __init__(self, start: int) -> None:
        self._now = int(start)
        self._start = int(start)

    def now(self) -> int:
        return self._now

    @property
    def start(self) -> int:
        return self._start

    def advance(self, seconds: int) -> int:
        if seconds < 0:
            raise ValueError("the sim clock never runs backwards")
        self._now += int(seconds)
        return self._now

    def set(self, when: int) -> int:
        if when < self._now:
            raise ValueError("the sim clock never runs backwards")
        self._now = int(when)
        return self._now


@dataclass(frozen=True)
class IstCalendar:
    """IST arithmetic on integer Unix seconds.

    IST is UTC+5:30 with no daylight saving, so a fixed offset is correct rather than an
    approximation. Quiet hours (21:00 to 09:00 IST) and the diurnal curve are both expressed in
    IST, which is why this exists instead of calling into datetime everywhere.
    """

    offset_seconds: int = 19800

    def hour_of_day(self, ts: int) -> int:
        return ((ts + self.offset_seconds) % DAY_SECONDS) // HOUR_SECONDS

    def minute_of_day(self, ts: int) -> int:
        return ((ts + self.offset_seconds) % DAY_SECONDS) // MINUTE_SECONDS

    def day_index(self, ts: int, epoch: int) -> int:
        return (ts + self.offset_seconds - epoch - self.offset_seconds) // DAY_SECONDS

    def start_of_day(self, ts: int) -> int:
        local = ts + self.offset_seconds
        return local - (local % DAY_SECONDS) - self.offset_seconds

    def hour_band(self, ts: int, bands_per_day: int = 4) -> int:
        """Four bands per day (Architecture section 5). Band 0 is 00:00 to 06:00 IST."""
        band_hours = 24 // bands_per_day
        return self.hour_of_day(ts) // band_hours

    def is_quiet_hours(self, ts: int, start_hour: int = 21, end_hour: int = 9) -> bool:
        """21:00 to 09:00 IST (docs/01_PRD.md section 9). Not used in M1; the executor needs it."""
        hour = self.hour_of_day(ts)
        return hour >= start_hour or hour < end_hour
