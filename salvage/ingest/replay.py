"""Webhook record and replay.

Architecture section 4:

  salvage webhooks record writes every verified raw event to data/webhooks/*.json;
  salvage webhooks replay <dir> feeds them back through the same normaliser with a fake signature
  header accepted only when SALVAGE_ENV=dev.

Replay exists so a recorded real event can be fed through the pipeline in CI and during
development without a live Razorpay account. It is refused outside dev.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from salvage import repo
from salvage.config import Settings, get_settings
from salvage.ingest.webhooks import ingest_event


class ReplayRefused(RuntimeError):
    """Replay was attempted outside SALVAGE_ENV=dev."""


@dataclass(frozen=True)
class ReplaySummary:
    replayed: int
    duplicates: int
    skipped: int


def record_verified_events(conn, out_dir: Path | str) -> int:
    """Write every verified event in the database to one JSON file each.

    Filenames carry the received-at second and the event id, so a directory listing is in
    delivery order and a re-record does not duplicate a file.

    These files contain raw webhook bodies, which can carry a contact or an email. They land under
    data/, which is gitignored, and they are never exported.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for event in repo.verified_webhook_events(conn):
        safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in event["event_id"])
        path = out_dir / f"{int(event['received_at']):011d}_{safe_id}.json"
        path.write_text(
            json.dumps(
                {
                    "event_id": event["event_id"],
                    "received_at": event["received_at"],
                    "event_type": event["event_type"],
                    "body": event["raw_json"],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        written += 1
    return written


def replay_directory(
    conn, directory: Path | str, *, settings: Settings | None = None
) -> ReplaySummary:
    """Feed recorded events back through the same normaliser.

    No signature is checked, which is exactly why this refuses to run outside dev.
    """
    settings = settings or get_settings()
    if not settings.is_dev:
        raise ReplayRefused(
            f"replay needs SALVAGE_ENV=dev, current environment is {settings.salvage_env!r}"
        )

    directory = Path(directory)
    if not directory.is_dir():
        raise ReplayRefused(f"{directory} is not a directory")

    replayed = duplicates = skipped = 0
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        event_id = record.get("event_id")
        body_text = record.get("body")
        if not event_id or body_text is None:
            skipped += 1
            continue
        raw_body = body_text.encode("utf-8")
        try:
            event = json.loads(raw_body)
        except json.JSONDecodeError:
            skipped += 1
            continue
        result = ingest_event(
            conn,
            event=event,
            event_id=str(event_id),
            raw_body=raw_body,
            received_at=int(record.get("received_at") or time.time()),
            # A replayed event was verified when it was first received, but this path did not
            # verify it, so it is recorded as unverified. That distinction is visible in the
            # database and in the ledger.
            verified=False,
            settings=settings,
        )
        if result.duplicate:
            duplicates += 1
        else:
            replayed += 1
    return ReplaySummary(replayed=replayed, duplicates=duplicates, skipped=skipped)
