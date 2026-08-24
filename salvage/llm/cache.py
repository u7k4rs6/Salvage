"""Prompt-hash cache in front of every provider.

docs/02_TECHNICAL_ARCHITECTURE.md section 11: "A cache table keyed by prompt hash sits in front of
every provider."

Two reasons it exists. The free tier has a request quota, and PRD section 14 lists rate limits as
a risk to the whole evaluation. And a cached response makes an evaluation run reproducible: the
same evidence packet produces the same diagnosis whether or not the network was up.

The key covers the system prompt, the user prompt and the schema. It does not cover the model id,
which is stored alongside instead, so switching from Flash to Flash-Lite does not silently reuse
the other model's answer: a lookup checks the stored model matches.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from salvage import repo


def prompt_hash(system: str, user: str, schema_name: str, schema: dict[str, Any]) -> str:
    """Stable hash of everything that determines the answer.

    The schema is included because the same prompt against a different output shape is a different
    question, and canonicalised so that a reordering of its keys is not a cache miss.
    """
    digest = hashlib.sha256()
    digest.update(b"salvage.llm.prompt.v1\n")
    for part in (system, user, schema_name, json.dumps(schema, sort_keys=True)):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def get(conn, key: str, *, provider: str, model: str) -> dict[str, Any] | None:
    """A cached response, or None.

    A hit recorded under a different model is a miss: the cache answers "what did this model say",
    not "what did some model say".
    """
    if conn is None:
        return None
    row = repo.get_llm_cache(conn, key)
    if row is None:
        return None
    if row["provider"] != provider or row["model"] != model:
        return None
    return json.loads(row["response_json"])


def put(conn, key: str, *, provider: str, model: str, response: dict[str, Any]) -> None:
    if conn is None:
        return
    repo.put_llm_cache(
        conn,
        {
            "prompt_hash": key,
            "provider": provider,
            "model": model,
            "response_json": json.dumps(response, sort_keys=True),
            "created_at": int(time.time()),
        },
    )
