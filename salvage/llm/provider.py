"""LLM provider abstraction.

docs/02_TECHNICAL_ARCHITECTURE.md section 11:

  LLMProvider.complete(system, user, schema) -> parsed model, with three implementations:
  Gemini (primary, Google AI Studio free tier over REST via httpx, model id from
  SALVAGE_LLM_MODEL, default gemini-2.5-flash, automatic fallback to the Flash-Lite id on 429),
  Ollama (fallback, http://localhost:11434, default qwen3:4b), and Fixture (tests and repeatable
  evals, strict mode raises on a miss, record mode writes new fixtures from a live provider).

  Structured output is enforced by asking for JSON only and validating with pydantic; one retry
  with the validation error, then escalate.

Model ids and the REST shape were checked against Google's own documentation on 25 August 2026:
  https://ai.google.dev/gemini-api/docs/models
  https://ai.google.dev/api/generate-content
  https://ai.google.dev/gemini-api/docs/structured-output
  https://ai.google.dev/gemini-api/docs/rate-limits

What that check found, recorded here because the defaults depend on it:
  gemini-2.5-flash and gemini-2.5-flash-lite are both current, published model ids.
  A newer Gemini 3 family exists (gemini-3.7-flash and others). Salvage does not default to it:
  Architecture section 11 names 2.5 Flash, and the free-tier availability of the 3 series could
  not be confirmed from the documentation.
  The rate-limits page does not publish free-tier numbers. It says limits depend on the account's
  usage tier and are visible only in AI Studio. So no quota figure is hardcoded anywhere; the
  429 handling below is what the code relies on instead, which is the right dependency anyway.
  Google now also documents an Interactions API at /v1beta/interactions. generateContent is still
  documented and is what this client uses, because its request and response shapes are the ones
  that could be verified field by field.

The model has no tools. Its output is a JSON object validated against a pydantic schema. It cannot
call Razorpay, the database or the channel (docs/03_SECURITY_AND_ACCESS.md section 7).
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from salvage.config import get_settings
from salvage.llm import cache as cache_mod

T = TypeVar("T", bound=BaseModel)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# https://ai.google.dev/api/generate-content
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_FALLBACK_MODEL = "gemini-2.5-flash-lite"

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen3:4b"

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_HTTP_ATTEMPTS = 3


class LLMError(RuntimeError):
    """The provider could not produce a valid answer. Callers escalate rather than guess."""


class FixtureMiss(LLMError):
    """Strict fixture mode was asked for a prompt it has never seen."""


class LLMProvider(ABC):
    """complete(system, user, schema) -> parsed model."""

    name: str = "abstract"
    model: str = ""

    @abstractmethod
    def _generate(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        """Return the model's raw text. Implementations do transport and retries only.

        schema_name is passed explicitly rather than read out of the schema dict, because
        gemini_schema strips `title` (Gemini's responseSchema does not accept it) and the prompt
        hash has to be the same value everywhere it is computed: in complete(), in the fixture
        provider's lookup, and in `salvage diagnose export-prompts`. Three different derivations
        of the same key is a silent cache miss waiting to happen.
        """

    def complete(self, system: str, user: str, schema: type[T], *, conn=None) -> T:
        """Ask, validate, and retry once with the validation error appended.

        Architecture section 11 fixes the retry policy: one retry with the validation error, then
        escalate. The retry is here rather than in each implementation so every provider gets the
        same behaviour and the fixture provider exercises the same path.
        """
        schema_json = gemini_schema(schema)
        key = cache_mod.prompt_hash(system, user, schema.__name__, schema_json)

        cached = cache_mod.get(conn, key, provider=self.name, model=self.model)
        if cached is not None:
            return schema.model_validate(cached)

        prompt = user
        last_error: str | None = None
        for attempt in range(2):
            raw = self._generate(system, prompt, schema_json, schema.__name__)
            try:
                parsed = schema.model_validate_json(_extract_json(raw))
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                if attempt == 1:
                    raise LLMError(
                        f"{self.name} returned output that failed validation twice: {last_error}"
                    ) from exc
                prompt = (
                    f"{user}\n\nYour previous answer was rejected by the output schema with this "
                    f"error. Fix it and answer again with JSON only.\n{last_error}"
                )
                continue
            cache_mod.put(
                conn,
                key,
                provider=self.name,
                model=self.model,
                response=json.loads(parsed.model_dump_json()),
            )
            return parsed
        raise LLMError(f"{self.name} produced no valid answer: {last_error}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Schema conversion
# ---------------------------------------------------------------------------

# Keywords Gemini's responseSchema does not accept. It takes a subset of OpenAPI 3.0, so pydantic's
# JSON Schema output has to be trimmed. Isolated here so there is one place to fix when the
# accepted subset changes.
_UNSUPPORTED_KEYS = frozenset(
    {"$defs", "$schema", "$ref", "additionalProperties", "default", "title", "examples", "const"}
)


def gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A pydantic model as a Gemini responseSchema.

    Inlines $defs, drops keywords the API does not accept, and keeps enum, type, properties,
    required, items, description, minimum, maximum and maxLength, which is what the schemas in
    salvage/diagnose and salvage/decide actually use.
    """
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    return _clean(raw, defs)


def _clean(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_clean(item, defs) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        ref = node["$ref"].rsplit("/", 1)[-1]
        merged = dict(defs.get(ref, {}))
        merged.update({k: v for k, v in node.items() if k != "$ref"})
        return _clean(merged, defs)
    if "anyOf" in node:
        # Optional fields become anyOf [type, null]. Gemini has no union, so the non-null branch
        # is used and the field is simply not required.
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        if options:
            merged = dict(options[0])
            merged.update({k: v for k, v in node.items() if k != "anyOf"})
            return _clean(merged, defs)
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_KEYS:
            continue
        cleaned[key] = _clean(value, defs)
    return cleaned


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> str:
    """The JSON object out of whatever the model wrapped it in.

    Asking for JSON only usually works. A small model in a fenced-code mood does not count as a
    schema violation worth burning the single retry on, so a fenced block is unwrapped first.
    """
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    match = _JSON_BLOCK.search(stripped)
    if match:
        return match.group(1).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


class GeminiProvider(LLMProvider):
    """Google AI Studio free tier over REST.

    Falls back to the Flash-Lite model id on 429, which is the documented behaviour in
    Architecture section 11. The fallback is a different model, so it is recorded as such in the
    cache and the provider's `model` attribute moves with it.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        fallback_model: str = GEMINI_FALLBACK_MODEL,
        client: httpx.Client | None = None,
        base_url: str = GEMINI_BASE_URL,
        sleeper: Any = None,
    ) -> None:
        settings = get_settings()
        # Injectable so tests exercise the retry ladder without actually waiting through it.
        self._sleeper = sleeper or _sleep_backoff
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model = model or settings.salvage_llm_model or GEMINI_DEFAULT_MODEL
        self._primary_model = self.model
        self._fallback_model = fallback_model
        self._base_url = base_url
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _body(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Request body, shape from https://ai.google.dev/api/generate-content."""
        return {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.0,
            },
        }

    def _generate(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        del schema_name
        if not self._api_key:
            raise LLMError("GEMINI_API_KEY is not set")

        model = self._primary_model
        body = self._body(system, user, schema)
        last_detail = ""
        for attempt in range(MAX_HTTP_ATTEMPTS):
            try:
                response = self._client.post(
                    f"{self._base_url}/models/{model}:generateContent",
                    json=body,
                    headers={"x-goog-api-key": self._api_key},
                )
            except httpx.TimeoutException as exc:
                last_detail = f"timeout: {exc}"
                self._sleeper(attempt)
                continue

            if response.status_code == 429:
                # Quota. Move to Flash-Lite once, then keep backing off on the smaller model.
                last_detail = "429 rate limited"
                if model != self._fallback_model:
                    model = self._fallback_model
                    self.model = model
                    continue
                self._sleeper(attempt)
                continue

            if response.status_code >= 500:
                last_detail = f"{response.status_code} server error"
                self._sleeper(attempt)
                continue

            if response.status_code >= 400:
                # No retry on other 4xx: a bad request will be bad again.
                raise LLMError(f"gemini returned {response.status_code}: {response.text[:200]}")

            self.model = model
            return _gemini_text(response.json())

        raise LLMError(f"gemini failed after {MAX_HTTP_ATTEMPTS} attempts: {last_detail}")


def _gemini_text(payload: dict[str, Any]) -> str:
    """The text out of a generateContent response.

    Shape from https://ai.google.dev/api/generate-content: candidates[0].content.parts[].text.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        raise LLMError(f"gemini returned no candidates: {json.dumps(payload)[:200]}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)
    if not text:
        finish = candidates[0].get("finishReason", "unknown")
        raise LLMError(f"gemini returned an empty candidate, finishReason {finish}")
    return text


def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff with jitter, same policy as the Razorpay client."""
    delay = (2**attempt) * 0.5
    time.sleep(delay + random.uniform(0, delay / 2))


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class OllamaProvider(LLMProvider):
    """Local fallback. Architecture section 16: never run while Vite is running."""

    name = "ollama"

    def __init__(
        self,
        model: str = OLLAMA_DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _generate(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        del schema_name
        try:
            response = self._client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    # Ollama takes a JSON Schema in `format` for structured output.
                    "format": schema,
                    "options": {"temperature": 0.0},
                },
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama is not reachable at {self._base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"ollama returned {response.status_code}: {response.text[:200]}")
        payload = response.json()
        return str((payload.get("message") or {}).get("content", ""))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


class FixtureProvider(LLMProvider):
    """Recorded responses, looked up by prompt hash.

    Strict mode raises on a miss, which is what CI uses: a test that silently invented an answer
    would make the diagnosis ablation meaningless. Record mode delegates to a live provider and
    writes the answer to disk.
    """

    name = "fixture"

    def __init__(
        self,
        directory: Path | str = FIXTURE_DIR,
        *,
        strict: bool = True,
        recorder: LLMProvider | None = None,
        model: str = "fixture",
    ) -> None:
        self.directory = Path(directory)
        self.strict = strict
        self.recorder = recorder
        self.model = model
        self.misses: list[str] = []

    def path_for(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def _generate(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        key = cache_mod.prompt_hash(system, user, schema_name, schema)
        path = self.path_for(key)
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(record["response"])

        self.misses.append(key)
        if self.recorder is not None:
            raw = self.recorder._generate(system, user, schema, schema_name)  # noqa: SLF001
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "prompt_hash": key,
                        "system": system,
                        "user": user,
                        "recorded_from": self.recorder.name,
                        "model": self.recorder.model,
                        "response": json.loads(_extract_json(raw)),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return raw

        if self.strict:
            raise FixtureMiss(
                f"no fixture for prompt hash {key}. Record one with "
                f"SALVAGE_LLM_PROVIDER=gemini and the fixture recorder, or check that the "
                f"evidence packet has not changed shape."
            )
        raise LLMError("fixture provider has no response and no recorder")


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class CollectingProvider(LLMProvider):
    """Records every prompt it is asked and answers none of them.

    This is how a fixture set is bootstrapped without a live provider. Run the agent with it, and
    every prompt the loop would have sent is written out with the hash the fixture will be looked
    up by. Each call then fails, so the loop takes its documented "no model answer" path and
    escalates, which is also a useful thing to be able to exercise on purpose.
    """

    name = "collect"

    def __init__(self, out_path: Path | str, model: str = "collect") -> None:
        self.out_path = Path(out_path)
        self.model = model
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()

    def _generate(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        key = cache_mod.prompt_hash(system, user, schema_name, schema)
        if key not in self._seen:
            self._seen.add(key)
            with self.out_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "prompt_hash": key,
                            "schema_title": schema_name,
                            "system": system,
                            "user": user,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
        raise LLMError(f"collecting provider recorded prompt {key} and returns no answer")


class FixtureThenCollectProvider(FixtureProvider):
    """Answer from fixtures where they exist, record the prompts where they do not.

    The bootstrap loop: run, collect the prompts the run needs, author those answers, run again.
    Each pass answers one more step of the loop, because a later prompt depends on an earlier
    answer. Local tooling only; CI uses the strict fixture provider.
    """

    name = "fixture"

    def __init__(self, out_path: Path | str, directory: Path | str = FIXTURE_DIR) -> None:
        super().__init__(directory, strict=False)
        self._collector = CollectingProvider(out_path)

    def _generate(self, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        key = cache_mod.prompt_hash(system, user, schema_name, schema)
        path = self.path_for(key)
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(record["response"])
        return self._collector._generate(system, user, schema, schema_name)  # noqa: SLF001


def build_provider(name: str | None = None, **kwargs: Any) -> LLMProvider:
    """The provider named by SALVAGE_LLM_PROVIDER, or by the argument.

    CI sets fixture and has no network and no credentials (Architecture section 15).
    """
    name = name or get_settings().salvage_llm_provider
    if name == "fixture":
        return FixtureProvider(**kwargs)
    if name == "gemini":
        return GeminiProvider(**kwargs)
    if name == "ollama":
        return OllamaProvider(**kwargs)
    if name == "collect":
        return CollectingProvider(**kwargs)
    if name == "fixture-collect":
        return FixtureThenCollectProvider(**kwargs)
    raise ValueError(f"unknown LLM provider {name!r}")


def write_fixture(
    directory: Path | str,
    *,
    key: str,
    system: str,
    user: str,
    response: dict[str, Any],
    recorded_from: str,
    model: str,
) -> Path:
    """Write one fixture by hand.

    Used by `salvage diagnose import-fixtures`, which exists because the fixture set has to be
    producible without a live provider: CI has no network and no credentials, and a contributor
    without a Gemini key still needs the diagnosis tests to run. The recorded_from field says what
    produced the answer, so a fixture set can never quietly claim to be from a model it is not.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.json"
    path.write_text(
        json.dumps(
            {
                "prompt_hash": key,
                "system": system,
                "user": user,
                "recorded_from": recorded_from,
                "model": model,
                "response": response,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def recording_provider(directory: Path | str = FIXTURE_DIR) -> FixtureProvider:
    """A fixture provider that records misses from a live Gemini. Local use only."""
    if os.environ.get("SALVAGE_LLM_PROVIDER") == "fixture":
        raise ValueError("set SALVAGE_LLM_PROVIDER to gemini or ollama to record fixtures")
    return FixtureProvider(directory, strict=False, recorder=GeminiProvider())
