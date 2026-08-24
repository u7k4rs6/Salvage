"""LLM provider layer: schema conversion, retry policy, cache, fixtures.

No network anywhere. The Gemini and Ollama clients are exercised through httpx.MockTransport,
which is in-process, so CI runs these with no credentials and no outbound socket (Architecture
section 15).
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, Field

from salvage.llm import cache as cache_mod
from salvage.llm.provider import (
    GEMINI_DEFAULT_MODEL,
    GEMINI_FALLBACK_MODEL,
    FixtureMiss,
    FixtureProvider,
    GeminiProvider,
    LLMError,
    OllamaProvider,
    _extract_json,
    build_provider,
    gemini_schema,
    write_fixture,
)


class Answer(BaseModel):
    model_config = {"extra": "forbid"}

    label: str = Field(max_length=20)
    score: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)


def _gemini(handler, **kwargs) -> GeminiProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiProvider(api_key="test-key", client=client, **kwargs)


def _ok(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
        headers={"content-type": "application/json"},
    )


# -- schema conversion -----------------------------------------------------


def test_the_schema_drops_keywords_gemini_does_not_accept():
    schema = gemini_schema(Answer)
    text = json.dumps(schema)
    for keyword in ("$defs", "$ref", "additionalProperties", "title"):
        assert keyword not in text
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"label", "score", "tags"}


def test_an_enum_survives_conversion():
    from salvage.diagnose.llm import LLMDiagnosis

    schema = gemini_schema(LLMDiagnosis)
    assert "enum" in json.dumps(schema)
    assert "issuer_outage" in json.dumps(schema)


def test_an_optional_field_loses_its_null_branch():
    class WithOptional(BaseModel):
        maybe: str | None = None

    schema = gemini_schema(WithOptional)
    assert schema["properties"]["maybe"]["type"] == "string"


# -- json extraction -------------------------------------------------------


def test_a_fenced_json_block_is_unwrapped():
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('```\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('Here you go: {"a": 1} hope that helps') == '{"a": 1}'
    assert _extract_json('{"a": 1}') == '{"a": 1}'


# -- gemini transport ------------------------------------------------------


def test_a_good_response_parses():
    provider = _gemini(lambda request: _ok({"label": "ok", "score": 0.5, "tags": []}))
    answer = provider.complete("sys", "user", Answer)
    assert answer.label == "ok"


def test_the_request_body_matches_the_documented_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return _ok({"label": "ok", "score": 0.1, "tags": []})

    _gemini(handler).complete("the system prompt", "the user prompt", Answer)
    assert seen["url"].endswith(f"/models/{GEMINI_DEFAULT_MODEL}:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "test-key"
    body = seen["body"]
    assert body["contents"][0]["parts"][0]["text"] == "the user prompt"
    assert body["systemInstruction"]["parts"][0]["text"] == "the system prompt"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"]["type"] == "object"


def test_a_429_falls_back_to_flash_lite():
    models = []

    def handler(request: httpx.Request) -> httpx.Response:
        models.append(str(request.url).split("/models/")[1].split(":")[0])
        if len(models) == 1:
            return httpx.Response(429, json={"error": "quota"})
        return _ok({"label": "ok", "score": 0.2, "tags": []})

    provider = _gemini(handler)
    provider.complete("sys", "user", Answer)
    assert models[0] == GEMINI_DEFAULT_MODEL
    assert models[1] == GEMINI_FALLBACK_MODEL
    assert provider.model == GEMINI_FALLBACK_MODEL


def test_a_5xx_is_retried_then_gives_up():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"error": "unavailable"})

    provider = _gemini(handler, sleeper=lambda _: None)
    with pytest.raises(LLMError, match="after 3 attempts"):
        provider.complete("sys", "user", Answer)
    assert len(calls) == 3


def test_a_400_is_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad schema"}})

    with pytest.raises(LLMError, match="400"):
        _gemini(handler).complete("sys", "user", Answer)
    assert len(calls) == 1


def test_a_missing_api_key_fails_before_any_request():
    provider = GeminiProvider(api_key="", client=httpx.Client())
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        provider.complete("sys", "user", Answer)


def test_an_empty_candidate_is_an_error_not_an_empty_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]})

    with pytest.raises(LLMError, match="empty candidate"):
        _gemini(handler).complete("sys", "user", Answer)


# -- the one retry on validation failure -----------------------------------


def test_invalid_output_is_retried_once_with_the_error_appended():
    prompts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompts.append(body["contents"][0]["parts"][0]["text"])
        if len(prompts) == 1:
            return _ok({"label": "x" * 50, "score": 5.0})  # violates both constraints
        return _ok({"label": "fixed", "score": 0.3, "tags": []})

    answer = _gemini(handler).complete("sys", "the original question", Answer)
    assert answer.label == "fixed"
    assert len(prompts) == 2
    assert "the original question" in prompts[1]
    assert "rejected by the output schema" in prompts[1]


def test_two_invalid_outputs_give_up_rather_than_retry_forever():
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok({"label": "x" * 50, "score": 5.0})

    with pytest.raises(LLMError, match="failed validation twice"):
        _gemini(handler).complete("sys", "user", Answer)


# -- ollama ----------------------------------------------------------------


def test_ollama_sends_the_schema_as_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"message": {"content": json.dumps({"label": "ok", "score": 0.4})}}
        )

    provider = OllamaProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.complete("sys", "user", Answer).label == "ok"
    assert seen["body"]["format"]["type"] == "object"
    assert seen["body"]["stream"] is False


def test_an_unreachable_ollama_says_so():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider = OllamaProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMError, match="not reachable"):
        provider.complete("sys", "user", Answer)


# -- cache -----------------------------------------------------------------


def test_the_cache_stops_a_second_call(conn):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _ok({"label": "cached", "score": 0.6, "tags": []})

    provider = _gemini(handler)
    first = provider.complete("sys", "user", Answer, conn=conn)
    second = provider.complete("sys", "user", Answer, conn=conn)
    assert first == second
    assert len(calls) == 1


def test_a_different_model_is_a_cache_miss(conn):
    key = cache_mod.prompt_hash("s", "u", "Answer", {})
    cache_mod.put(conn, key, provider="gemini", model="a", response={"label": "x"})
    assert cache_mod.get(conn, key, provider="gemini", model="a") is not None
    assert cache_mod.get(conn, key, provider="gemini", model="b") is None
    assert cache_mod.get(conn, key, provider="ollama", model="a") is None


def test_the_prompt_hash_covers_the_schema():
    a = cache_mod.prompt_hash("s", "u", "Answer", {"type": "object"})
    b = cache_mod.prompt_hash("s", "u", "Answer", {"type": "string"})
    assert a != b
    # Key order in the schema must not change the hash.
    c = cache_mod.prompt_hash("s", "u", "Answer", {"a": 1, "b": 2})
    d = cache_mod.prompt_hash("s", "u", "Answer", {"b": 2, "a": 1})
    assert c == d


# -- fixtures --------------------------------------------------------------


def test_strict_mode_raises_on_a_miss(tmp_path):
    provider = FixtureProvider(tmp_path, strict=True)
    with pytest.raises(FixtureMiss, match="no fixture"):
        provider.complete("sys", "user", Answer)


def test_a_written_fixture_is_found_again(tmp_path):
    schema = gemini_schema(Answer)
    key = cache_mod.prompt_hash("sys", "user", "Answer", schema)
    write_fixture(
        tmp_path,
        key=key,
        system="sys",
        user="user",
        response={"label": "from_fixture", "score": 0.7, "tags": ["a"]},
        recorded_from="test",
        model="test",
    )
    assert FixtureProvider(tmp_path).complete("sys", "user", Answer).label == "from_fixture"


def test_a_fixture_records_what_produced_it(tmp_path):
    """A fixture set can never quietly claim to be from a model it is not."""
    path = write_fixture(
        tmp_path,
        key="abc",
        system="s",
        user="u",
        response={"label": "x", "score": 0.1},
        recorded_from="claude-opus-5",
        model="claude-opus-5",
    )
    record = json.loads(path.read_text())
    assert record["recorded_from"] == "claude-opus-5"
    assert record["model"] == "claude-opus-5"


def test_the_shipped_fixtures_all_declare_their_source():
    from salvage.llm.provider import FIXTURE_DIR

    for path in FIXTURE_DIR.glob("*.json"):
        record = json.loads(path.read_text())
        assert record.get("recorded_from"), path.name
        assert record.get("response"), path.name
        assert record["prompt_hash"] == path.stem


def test_build_provider_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="unknown LLM provider"):
        build_provider("not_a_provider")
