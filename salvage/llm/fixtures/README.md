# LLM fixtures

Recorded model responses, looked up by prompt hash. CI uses the strict fixture provider, which
raises on a miss, so a test can never silently invent an answer.

## This directory is empty on purpose

It held 46 fixtures written by Claude Opus 5 standing in for Gemini, because no Gemini key was
available when M2 was built. **They were deleted in M3 and no number was ever taken from them into
`docs/RESULTS.md`.** The reason is in `docs/BUILD_LOG.md` and it is worth restating: the author of
those fixtures knew the scenario each evidence packet came from and knew which cases the rules
classifier had already failed. A model that knows the label set and knows which items are hard is
not being measured, it is being asked to confirm. Their held-out accuracy of 1.00 was an artefact
of that, not a result.

Until this directory is refilled from a live provider, the LLM arm of the diagnosis ablation and
the agent policy arm are **unmeasured**, and `docs/RESULTS.md` says so in both places.

## Refilling it, blind

`salvage diagnose record-fixtures` is the only supported way. It exists because doing this by hand
is exactly how the last set went wrong. The recorder:

  builds each evidence packet through the same code path the agent uses, which reads the `v_*`
  views and therefore cannot see `truth_cause` or any `sim_truth_*` table;

  strips the scenario id and the seed from everything it hands to the provider, and asserts they
  do not appear in the prompt text;

  never runs the rules classifier, so the model's answer cannot be anchored on it;

  refuses to run at all unless the provider is a live one.

The isolation is in the code path, not in the operator's discipline. `PromptForRecording` carries
the prompt and its hash and nothing else, and `record_fixtures` takes that type rather than the
richer row `export-prompts` writes.

```
export GEMINI_API_KEY=...            # Google AI Studio free tier, no billing account needed
uv run salvage diagnose record-fixtures --scenarios S1,S2,S3,S4 --seeds 0..9 --provider gemini
uv run salvage diagnose accuracy --seeds 0..9 --provider fixture
```

Every fixture records `recorded_from` and `model`, and
`tests/unit/test_llm_provider.py::test_no_fixture_claims_a_model_that_did_not_write_it` refuses any
fixture whose `recorded_from` names a Claude model.
