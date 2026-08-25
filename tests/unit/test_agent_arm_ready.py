"""The agent arm's whole path, end to end, without a live provider.

No Gemini key and no Ollama were available for M1 to M4, so the agent arm's numbers are
unmeasured and docs/RESULTS.md says so. What is measured here is that the path works: record
fixtures blind from a provider, replay them, run the agent, and get an incident diagnosed, planned,
gated, acted on and settled.

A fake Gemini answers over httpx.MockTransport, which is in-process, so this runs in CI with no
network and no credentials. The fixtures it writes go to a temporary directory and are never
shipped: `tests/unit/test_llm_provider.py::test_no_fixture_claims_a_model_that_did_not_write_it`
would fail the suite if they were. **No number from this test is reported anywhere.** Its only
claim is that when a key arrives, one command fills the arm.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import yaml

from salvage.db import open_migrated
from salvage.eval.agent_run import run_policy_scenario
from salvage.eval.run import LabelLeak, PromptForRecording, assert_blind, record_fixtures
from salvage.llm.provider import FixtureProvider, GeminiProvider
from salvage.sim.params import PARAMS_PATH


def _diagnosis_answer(user: str) -> dict[str, Any]:
    """What a plausible model would say, chosen from the prompt and nothing else.

    Deliberately crude: it reads the dominant error source out of the prompt text, the same way a
    reader would. It is not trying to be accurate; it is trying to be a well-formed answer that
    exercises the schema, the rationale validator and the reconciliation rule.
    """
    if "business=" in user and "business=0.0" not in user:
        cause = "merchant_config"
    elif "gateway=0.5" in user or "gateway=0.6" in user or "gateway=0.7" in user:
        cause = "gateway_degradation"
    elif "payment_authentication=1.0" in user or "payment_authentication=0.9" in user:
        cause = "auth_failure_bin"
    else:
        cause = "issuer_outage"
    return {
        "root_cause": cause,
        "confidence": 0.86,
        "rationale": (
            "error_source_dist and error_step_dist both move sharply against their baselines and "
            "sibling_segments shows the neighbours healthy."
        ),
        "affected_scope": [],
    }


def _plan_answer(user: str) -> dict[str, Any]:
    incident_id = next(
        line.split(": ", 1)[1] for line in user.splitlines() if line.startswith("incident_id: ")
    )
    forbidden = "SEND_RECOVERY_LINK: NOT allowed" in user
    actions: list[dict[str, Any]] = []
    if not forbidden:
        if "STEER_METHOD: allowed" in user:
            actions.append(
                {
                    "type": "STEER_METHOD",
                    "scope": "all_affected",
                    "params": {"hide_methods": ["upi"], "prefer_methods": ["card"]},
                }
            )
        actions.append(
            {
                "type": "SEND_RECOVERY_LINK",
                "scope": "consented_with_alternate",
                "params": {"case_id": "pending"},
            }
        )
    else:
        actions.append(
            {
                "type": "ESCALATE_HUMAN",
                "scope": "all_affected",
                "params": {"reason": "the merchant's own configuration is refusing these payments"},
            }
        )
    return {"incident_id": incident_id, "actions": actions, "rationale": "test double"}


def _fake_gemini_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    user = body["contents"][0]["parts"][0]["text"]
    schema = body["generationConfig"]["responseSchema"]
    is_plan = "incident_id" in schema["properties"]
    answer = _plan_answer(user) if is_plan else _diagnosis_answer(user)
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]},
    )


def _fake_gemini() -> GeminiProvider:
    return GeminiProvider(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(_fake_gemini_handler)),
    )


@pytest.fixture
def small_params(tmp_path):
    raw = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    # Full traffic volume, fewer days. The detector needs volume per 15-minute window, not a long
    # history, and below about 5,000 attempts a day it does not fire at all (see the operating
    # envelope in docs/RESULTS.md). A reduced-volume fixture here would test nothing.
    raw["merchant"]["customer_count"] = 3000
    raw["clock"]["warmup_days"] = 3
    raw["clock"]["settle_days"] = 2
    path = tmp_path / "params.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_the_recorder_refuses_a_fixture_or_collecting_provider():
    with pytest.raises(ValueError, match="live provider"):
        record_fixtures([], FixtureProvider(strict=True))


def test_the_recorder_checks_every_prompt_before_sending_it(tmp_path):
    """assert_blind runs inside record_fixtures, not only when the prompts are built."""
    leaky = PromptForRecording(
        prompt_hash="h",
        system="system",
        user="segment_key: upi\nscenario: S1",
        schema_name="LLMDiagnosis",
    )
    with pytest.raises(LabelLeak):
        record_fixtures([leaky], _fake_gemini(), directory=tmp_path)
    assert list(tmp_path.glob("*.json")) == []


def test_record_then_replay_then_run_the_agent(tmp_path, small_params):
    """The whole chain: record blind, replay strictly, act.

    This is the command sequence in salvage/llm/fixtures/README.md, executed against a fake
    provider so it runs with no network and no key.
    """
    from salvage.diagnose.evidence import build_for_incident
    from salvage.diagnose.llm import SYSTEM_PROMPT, build_user_prompt
    from salvage.llm.cache import prompt_hash
    from salvage.llm.provider import gemini_schema

    fixtures = tmp_path / "fixtures"

    # 1. A first pass with no provider, to produce the incident whose prompts we need.
    conn = open_migrated(tmp_path / "probe.db")
    try:
        probe = run_policy_scenario(
            conn, scenario="S1", seed=1, policy="agent", params_path=small_params
        )
        assert probe.incidents, "no incident to diagnose, so this test proves nothing"
        packets = [build_for_incident(conn, incident) for incident in probe.incidents]
    finally:
        conn.close()

    # 2. Record the diagnosis fixtures blind.
    from salvage.diagnose.llm import LLMDiagnosis

    schema = gemini_schema(LLMDiagnosis)
    prompts = []
    for packet in packets:
        user = build_user_prompt(packet)
        prompt = PromptForRecording(
            prompt_hash=prompt_hash(SYSTEM_PROMPT, user, "LLMDiagnosis", schema),
            system=SYSTEM_PROMPT,
            user=user,
            schema_name="LLMDiagnosis",
        )
        assert_blind(prompt)
        prompts.append(prompt)
    outcome = record_fixtures(prompts, _fake_gemini(), directory=fixtures)
    assert outcome.failures == []
    assert outcome.written == len(prompts)
    assert outcome.skipped == 0

    # Recording again asks nothing: a pass that died halfway resumes rather than spending a free
    # tier's daily quota re-answering questions that are already answered.
    again = record_fixtures(prompts, _fake_gemini(), directory=fixtures)
    assert (again.written, again.skipped) == (0, len(prompts))

    # Every fixture records what produced it.
    for path in fixtures.glob("*.json"):
        record = json.loads(path.read_text())
        assert record["recorded_from"] == "gemini"

    # 3. Run the agent with the recorded diagnosis and a live planner, which is what happens with
    #    a real key: the diagnosis comes from cache or fixture, the planner is asked fresh.
    class Chained(FixtureProvider):
        name = "gemini"

        def __init__(self) -> None:
            super().__init__(fixtures, strict=False)
            self.model = "chained"
            self._live = _fake_gemini()

        def _generate(self, system, user, schema, schema_name):  # noqa: ANN001
            path = self.path_for(prompt_hash(system, user, schema_name, schema))
            if path.exists():
                return json.dumps(json.loads(path.read_text())["response"])
            return self._live._generate(system, user, schema, schema_name)  # noqa: SLF001

    conn = open_migrated(tmp_path / "agent.db")
    try:
        result = run_policy_scenario(
            conn,
            scenario="S1",
            seed=1,
            policy="agent",
            provider=Chained(),
            params_path=small_params,
        )
    finally:
        conn.close()

    stats = result.stats
    assert stats.incidents >= 1
    assert stats.diagnosed >= 1
    # The agent acted: it planned, gated, created links and sent validated messages.
    assert stats.actions_proposed > 0
    assert stats.links_created > 0
    assert stats.messages_sent > 0
    assert stats.messages_rejected == 0
    # And every incident carries a real diagnosis above the action threshold.
    for incident in result.incidents:
        if str(incident["id"]).endswith("_baseline"):
            continue
        assert incident["llm_cause"] is not None
        assert incident["confidence"] >= 0.7


def test_the_agent_arm_beats_doing_nothing_on_the_at_risk_set(tmp_path, small_params):
    """Not a reported number. A check that the arm is wired to the metric it will be judged on."""

    class Live(FixtureProvider):
        name = "gemini"

        def __init__(self) -> None:
            super().__init__(tmp_path / "unused", strict=False)
            self.model = "live"
            self._live = _fake_gemini()

        def _generate(self, system, user, schema, schema_name):  # noqa: ANN001
            return self._live._generate(system, user, schema, schema_name)  # noqa: SLF001

    outcomes = {}
    for policy, provider in (("B0", None), ("agent", Live())):
        conn = open_migrated(tmp_path / f"{policy}.db")
        try:
            outcomes[policy] = run_policy_scenario(
                conn,
                scenario="S1",
                seed=1,
                policy=policy,
                provider=provider,
                params_path=small_params,
            ).metrics
        finally:
            conn.close()

    assert outcomes["agent"].at_risk_orders == outcomes["B0"].at_risk_orders > 0
    assert outcomes["agent"].at_risk_recovered_amount >= outcomes["B0"].at_risk_recovered_amount, (
        "the agent recovered less than doing nothing on the at-risk set"
    )


def test_a_merchant_config_incident_still_contacts_nobody_with_a_model(tmp_path, small_params):
    """The matrix does not soften when a model is present and confident."""

    class Live(FixtureProvider):
        name = "gemini"

        def __init__(self) -> None:
            super().__init__(tmp_path / "unused2", strict=False)
            self.model = "live"
            self._live = _fake_gemini()

        def _generate(self, system, user, schema, schema_name):  # noqa: ANN001
            return self._live._generate(system, user, schema, schema_name)  # noqa: SLF001

    conn = open_migrated(tmp_path / "s4.db")
    try:
        result = run_policy_scenario(
            conn,
            scenario="S4",
            seed=1,
            policy="agent",
            provider=Live(),
            params_path=small_params,
        )
    finally:
        conn.close()
    assert result.stats.messages_sent == 0
    assert result.stats.links_created == 0
    assert result.stats.escalations > 0
    assert result.escalations
