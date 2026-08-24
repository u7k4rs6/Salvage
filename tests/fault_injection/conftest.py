"""Recording for the fault injection suite.

docs/02_TECHNICAL_ARCHITECTURE.md section 15 lists the injections. Every one of them asserts the
same two things: the executed actions are unchanged, and the refusal is in the ledger. This
fixture records each attempt so `docs/RESULTS.md` can carry the count of attempts and refusals
rather than a claim that they all passed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "data" / "results" / "fault_injection.json"


class InjectionLog:
    """One row per injection attempt."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def record(
        self,
        *,
        category: str,
        attack: str,
        refused: bool,
        ledgered: bool,
        detail: str = "",
        expect_refusal: bool = True,
    ) -> None:
        """Record one case.

        expect_refusal separates the two kinds of row. Most are attacks and must be refused. A few
        are fault-tolerance cases where the correct behaviour is to carry on: a 429 that is
        retried, a clock five minutes out that is still inside the freshness window. Counting
        those as unrefused attacks would understate the refusal rate; counting them as refusals
        would overstate what was actually blocked.
        """
        self.rows.append(
            {
                "category": category,
                "attack": attack,
                "refused": refused,
                "ledgered": ledgered,
                "detail": detail,
                "expect_refusal": expect_refusal,
            }
        )

    def summary(self) -> dict[str, object]:
        attacks = [row for row in self.rows if row["expect_refusal"]]
        tolerated = [row for row in self.rows if not row["expect_refusal"]]
        by_category: dict[str, dict[str, int]] = {}
        for row in attacks:
            bucket = by_category.setdefault(
                str(row["category"]), {"attempts": 0, "refused": 0, "ledgered": 0}
            )
            bucket["attempts"] += 1
            bucket["refused"] += int(bool(row["refused"]))
            bucket["ledgered"] += int(bool(row["ledgered"]))
        return {
            "attempts": len(attacks),
            "refused": sum(1 for row in attacks if row["refused"]),
            "ledgered": sum(1 for row in attacks if row["ledgered"]),
            "unrefused": [row["attack"] for row in attacks if not row["refused"]],
            "fault_tolerance_cases": len(tolerated),
            "fault_tolerance_handled": sum(1 for row in tolerated if not row["refused"]),
            "by_category": by_category,
            "rows": self.rows,
        }


@pytest.fixture(scope="session")
def injection_log() -> InjectionLog:
    return InjectionLog()


@pytest.fixture(scope="session", autouse=True)
def _write_injection_report(injection_log: InjectionLog):
    yield
    if not injection_log.rows:
        return
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(injection_log.summary(), indent=2), encoding="utf-8")
