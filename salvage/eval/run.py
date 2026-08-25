"""Evaluation sweeps.

M3 owns the full runner from Architecture section 10. M2 needs one piece of it now: the diagnosis
ablation, which runs each scenario at each seed into its own database, detects, diagnoses with the
rules alone and with the model, and reports both accuracies side by side.

This module reads simulator ground truth. Architecture section 10 says the evaluation runner is
the only code allowed to, and this is it.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from salvage import repo
from salvage.db import open_migrated
from salvage.detect.calibrate import make_workdir
from salvage.detect.run import detect
from salvage.diagnose.reconcile import diagnose_incident
from salvage.eval.metrics import DiagnosisOutcome, true_cause_for
from salvage.sim.runner import run_scenario

DEFAULT_SCENARIOS = ("S1", "S2", "S3", "S4")


def diagnosis_sweep(
    *,
    scenarios: list[str] | None = None,
    seeds: list[int],
    variant: str = "peak",
    provider=None,
    params_path: Path | str | None = None,
) -> list[DiagnosisOutcome]:
    """One row per incident opened, with the rules verdict and, if a provider is given, the model's.

    S0 is excluded by default: it has no fault, so an incident there has no true cause and belongs
    in the false-alarm column of the calibration table rather than the accuracy column here.
    """
    scenarios = scenarios or list(DEFAULT_SCENARIOS)
    workdir = make_workdir()
    outcomes: list[DiagnosisOutcome] = []
    try:
        for scenario in scenarios:
            for seed in seeds:
                outcomes.extend(
                    _one_run(
                        workdir=workdir,
                        scenario=scenario,
                        seed=seed,
                        variant=variant,
                        provider=provider,
                        params_path=params_path,
                    )
                )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return outcomes


@dataclass(frozen=True)
class PromptForRecording:
    """A prompt and its hash, and deliberately nothing else.

    This type is the isolation. `export_prompts` returns rows carrying the scenario, the seed and
    the incident id, which is useful for a human reading them and is exactly what must not reach a
    model that is being measured. `record_fixtures` takes this type instead, so the scenario label
    is not merely unused, it is absent: there is no field to leak it from.
    """

    prompt_hash: str
    system: str
    user: str
    schema_name: str


class LabelLeak(RuntimeError):
    """A scenario id or a seed reached a prompt that is meant to be blind."""


# Anything that would tell a model which scenario it is looking at. Checked against every prompt
# before it is sent, so the isolation fails loudly rather than quietly.
#
# Word boundaries, not substrings. The evidence packet legitimately carries a field called
# `merchant_config_changed_recently`, which a substring check reads as the cause name
# `merchant_config` and refuses. That would have made every S4 prompt unrecordable with a
# confusing error, and it was caught by tests/unit/test_agent_arm_ready.py rather than by anyone
# reading this list. `\b` does not match between "merchant_config" and "_changed" because an
# underscore is a word character, which is exactly the distinction wanted here.
_LABEL_PATTERNS = tuple(
    re.compile(rf"\b{name}\b")
    for name in (
        "scenario",
        "seed",
        "truth_cause",
        "sim_truth",
        "issuer_outage",
        "auth_failure_bin",
        "gateway_degradation",
        "merchant_config",
        "customer_side",
    )
)


def assert_blind(prompt: PromptForRecording, *, allow_cause_names_in_system: bool = True) -> None:
    """Refuse a prompt that carries its own answer.

    The system prompt has to name the six causes, because the model is being asked to choose
    between them; the evidence packet must not. So the user half is checked against every label
    pattern and the system half against the ones that are not the class names.
    """
    lowered = prompt.user.lower()
    for pattern in _LABEL_PATTERNS:
        match = pattern.search(lowered)
        if match:
            raise LabelLeak(
                f"the evidence prompt contains {match.group(0)!r}, which would tell the model "
                "the answer"
            )
    if not allow_cause_names_in_system:
        system = prompt.system.lower()
        for name in ("scenario", "seed", "truth_cause"):
            if re.search(rf"\b{name}\b", system):
                raise LabelLeak(f"the system prompt contains {name!r}")


def prompts_for_recording(
    *,
    scenarios: list[str] | None = None,
    seeds: list[int],
    variant: str = "peak",
    params_path: Path | str | None = None,
) -> list[PromptForRecording]:
    """Every diagnosis prompt the sweep would produce, stripped to prompt and hash.

    Built through `build_for_incident`, the same call the agent makes, which reads the `v_*` views
    and so cannot reach `truth_cause` or any `sim_truth_*` table. The rules classifier is not run:
    a recorder that had the rules verdict in hand could anchor on it, and the whole point of the
    ablation is that the two are independent.
    """
    rows = export_prompts(
        scenarios=scenarios, seeds=seeds, variant=variant, params_path=params_path
    )
    prompts = []
    for row in rows:
        prompt = PromptForRecording(
            prompt_hash=str(row["prompt_hash"]),
            system=str(row["system"]),
            user=str(row["user"]),
            schema_name="LLMDiagnosis",
        )
        assert_blind(prompt)
        prompts.append(prompt)
    return prompts


def record_fixtures(
    prompts: list[PromptForRecording],
    provider,
    *,
    directory: Path | str | None = None,
    pause_seconds: float = 0.0,
) -> tuple[int, list[str]]:
    """Ask a live provider each prompt and write the answer as a fixture.

    Refuses a fixture or collecting provider: recording from a fixture provider would copy
    whatever is already on disk, and recording from the collector would write nothing.

    `pause_seconds` paces the calls. The Gemini free tier is rate limited per minute, and the
    provider answers a 429 by falling back to a smaller model, so recording flat out would split
    one fixture set across two models and the ablation would no longer be measuring one thing.
    Pacing keeps the provenance single valued; it is not a politeness feature.
    """
    from salvage.diagnose.llm import LLMDiagnosis
    from salvage.llm.provider import FIXTURE_DIR, LLMError, write_fixture

    if provider.name not in ("gemini", "ollama"):
        raise ValueError(
            f"fixtures must be recorded from a live provider, not {provider.name!r}. "
            "A fixture recorded from a fixture is a copy, and one written by hand is not a "
            "measurement."
        )

    directory = Path(directory) if directory else FIXTURE_DIR
    written, failures = 0, []
    for index, prompt in enumerate(prompts):
        if pause_seconds and index:
            time.sleep(pause_seconds)
        assert_blind(prompt)
        try:
            answer = provider.complete(prompt.system, prompt.user, LLMDiagnosis)
        except LLMError as exc:
            failures.append(f"{prompt.prompt_hash[:12]}: {exc}")
            continue
        write_fixture(
            directory,
            key=prompt.prompt_hash,
            system=prompt.system,
            user=prompt.user,
            response=json.loads(answer.model_dump_json()),
            recorded_from=provider.name,
            model=provider.model,
        )
        written += 1
    return written, failures


def export_prompts(
    *,
    scenarios: list[str] | None = None,
    seeds: list[int],
    variant: str = "peak",
    params_path: Path | str | None = None,
) -> list[dict]:
    """Every distinct diagnosis prompt the sweep would produce, with its hash.

    Exists so a fixture set can be produced without a live provider. The hash is computed exactly
    as the provider computes it, so a fixture written against one of these rows is found at
    replay. If the evidence packet's shape ever changes, the hashes change and every fixture
    misses loudly rather than silently answering a different question.
    """
    from salvage.diagnose.evidence import build_for_incident
    from salvage.diagnose.llm import SYSTEM_PROMPT, LLMDiagnosis, build_user_prompt
    from salvage.llm.cache import prompt_hash
    from salvage.llm.provider import gemini_schema
    from salvage.sim.params import default_params, load

    scenarios = scenarios or list(DEFAULT_SCENARIOS)
    schema = gemini_schema(LLMDiagnosis)
    workdir = make_workdir()
    rows: list[dict] = []
    try:
        for scenario in scenarios:
            for seed in seeds:
                db_path = workdir / f"prompt_{scenario}_{seed}_{variant}.db"
                conn = open_migrated(db_path)
                try:
                    sim = run_scenario(
                        conn,
                        scenario=scenario,
                        seed=seed,
                        variant=variant,
                        params_path=params_path,
                    )
                    params = load(params_path) if params_path else default_params()
                    detect(
                        conn,
                        eval_start=sim.eval_day_start,
                        eval_end=sim.eval_day_start + params.eval_days * 86400,
                    )
                    for incident in repo.list_incidents(conn):
                        packet = build_for_incident(conn, incident)
                        user = build_user_prompt(packet)
                        rows.append(
                            {
                                "prompt_hash": prompt_hash(
                                    SYSTEM_PROMPT, user, "LLMDiagnosis", schema
                                ),
                                "scenario": scenario,
                                "seed": seed,
                                "incident_id": str(incident["id"]),
                                "segment_key": str(incident["segment_key"]),
                                "system": SYSTEM_PROMPT,
                                "user": user,
                            }
                        )
                finally:
                    conn.close()
                    for suffix in ("", "-wal", "-shm"):
                        Path(str(db_path) + suffix).unlink(missing_ok=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return rows


def _one_run(
    *, workdir: Path, scenario: str, seed: int, variant: str, provider, params_path
) -> list[DiagnosisOutcome]:
    db_path = workdir / f"diag_{scenario}_{seed}_{variant}.db"
    conn = open_migrated(db_path)
    outcomes: list[DiagnosisOutcome] = []
    try:
        sim = run_scenario(
            conn,
            scenario=scenario,
            seed=seed,
            variant=variant,
            params_path=params_path,
        )
        from salvage.sim.params import default_params, load

        params = load(params_path) if params_path else default_params()
        detect(
            conn,
            eval_start=sim.eval_day_start,
            eval_end=sim.eval_day_start + params.eval_days * 86400,
        )
        for incident in repo.list_incidents(conn):
            diagnosis, _ = diagnose_incident(conn, incident, provider=provider)
            truth = true_cause_for(conn, sim.run_id, int(incident["opened_at"]))
            outcomes.append(
                DiagnosisOutcome(
                    scenario=scenario,
                    seed=seed,
                    incident_id=str(incident["id"]),
                    segment_key=str(incident["segment_key"]),
                    # An incident outside every fault window is a false alarm and has no true
                    # cause. It is scored against "unknown", because the correct answer to
                    # "what broke" when nothing broke is that nothing identifiable did.
                    true_cause=truth or "unknown",
                    rules_cause=diagnosis.rules_cause,
                    llm_cause=diagnosis.llm_cause,
                    reconciled_cause=diagnosis.root_cause if provider is not None else None,
                    confidence=diagnosis.confidence,
                )
            )
    finally:
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
    return outcomes
