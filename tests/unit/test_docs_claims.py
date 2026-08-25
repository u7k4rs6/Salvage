"""Claims the shipped documents make about themselves.

These are not style checks. Each one is a statement a reader will act on, and each has been wrong
at least once in this project's history: a results file that said "unmeasured" after the thing had
been measured, a provenance line that outlived the artifact it described, a table of at-risk
revenue with no contact volume beside it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path("docs")
RESULTS = DOCS / "RESULTS.md"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"{path} has not been generated in this checkout")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "path",
    [Path("README.md"), DOCS / "RESULTS.md", DOCS / "PITCH.md", DOCS / "WHAT_BROKE.md"],
)
def test_no_em_or_en_dashes_in_the_shipped_documents(path):
    text = _read(path)
    offenders = [
        f"line {index}: {line.strip()}"
        for index, line in enumerate(text.splitlines(), start=1)
        if "—" in line or "–" in line
    ]
    assert offenders == [], offenders


def test_results_never_calls_a_measured_thing_unmeasured():
    """M5 measured the agent arm. A leftover 'unmeasured' would tell a reader the opposite of what
    the tables below it now say, and the word is cheap to leave behind."""
    text = _read(RESULTS)
    offenders = [
        f"line {index}: {line.strip()}"
        for index, line in enumerate(text.splitlines(), start=1)
        if "unmeasured" in line.lower()
    ]
    assert offenders == [], offenders


def test_the_results_provenance_names_a_provider_and_a_model():
    """The provenance line is read out of the fixture files rather than asserted, so it cannot
    outlive them. This checks the line actually made it into the document."""
    text = _read(RESULTS)
    assert "The agent arm is measured, from fixtures recorded blind." in text
    assert re.search(r"\d+ diagnosis fixture\(s\): .*from \w+ model `", text), (
        "the provenance line should name how many diagnosis fixtures, from which provider, on "
        "which model"
    )
    # Planner fixtures live in the same directory and must not be counted as evidence for the
    # ablation. The line said "82 fixture(s)" when 41 of them had nothing to do with that table.
    assert "planner fixture(s) sit alongside them and back no table here" in text


def test_every_primary_cell_carries_contact_volume():
    """Recovered revenue without messages beside it invites the reading that recovery is free."""
    text = _read(RESULTS)
    section = text.split("## 1. Primary")[1].split("##")[0]
    # The first table in the section only. The per-arm message and opt-out table sits below it
    # under the same heading and carries counts rather than revenue, which is the whole reason
    # the two were split apart.
    rows: list[str] = []
    for line in section.splitlines():
        if line.startswith("|"):
            if line.startswith("| S"):
                rows.append(line)
        elif rows:
            break
    assert rows, "the primary table has no scenario rows"
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")][2:]
        for cell in cells:
            assert "msg" in cell, f"{cell!r} in {row!r} has revenue with no contact volume"


def test_the_escalation_fix_section_states_who_cannot_benefit():
    text = _read(RESULTS)
    assert "## 11. Escalation to fix" in text
    assert "Only an arm that escalates can be repaired." in text
