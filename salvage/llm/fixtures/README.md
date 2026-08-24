# LLM fixtures

Recorded model responses, looked up by prompt hash. CI uses the strict fixture provider, which
raises on a miss, so a test can never silently invent an answer.

## Read this before quoting any accuracy number from these

**These fixtures were not produced by Gemini.** No Gemini API key and no local Ollama were
available in the environment where M2 was built, so every response here was written by
Claude Opus 5 reading the same evidence packet the prompt contains. Each file records that in its
`recorded_from` field.

Two consequences, and the second one matters more:

1. The pipeline is genuinely exercised. The prompts are real, the schemas are enforced, the
   rationale-must-cite-evidence validator runs, and the reconciliation and policy paths downstream
   are the shipped ones. As a test double these fixtures do their job.

2. **The accuracy numbers they produce are not a blind measurement and must not be reported as
   one.** The author knew which scenario each packet came from, because
   `salvage diagnose export-prompts` writes the scenario and seed alongside the prompt, and knew
   from an earlier run which cases the rules classifier had failed. A model that knows the label
   set and knows which items are hard is not being tested; it is being asked to confirm. The
   held-out figure of 1.00 in `docs/BUILD_LOG.md` is therefore an upper bound on what a real
   provider would score, and the useful part of that table is the rules-only column beside it,
   which was produced by code that cannot see labels.

Before anything from these fixtures reaches `docs/RESULTS.md`, re-record them against a real
provider that has never seen the labels:

```
export GEMINI_API_KEY=...
uv run salvage diagnose export-prompts --seeds 0..4 --out data/prompts.jsonl
# then run the prompts through Gemini with the recording provider, or:
uv run salvage diagnose accuracy --seeds 0..4 --provider gemini
```

`salvage/llm/provider.py` has `recording_provider()` for the first form. Delete these files when
real ones exist; the prompt hashes will not collide, so a stale fixture cannot shadow a fresh one
for a prompt that has changed, but it can for one that has not.

## How they were made

```
uv run salvage agent run --scenario S1 --seed 1 --provider fixture-collect \
    --collect-out data/prompts_agent.jsonl
uv run salvage diagnose export-prompts --seeds 0..4 --out data/prompts_diag.jsonl
uv run salvage diagnose import-fixtures data/prompts_diag.jsonl answers.json \
    --recorded-from "..." --model "..."
```

`import-fixtures` validates every answer against the schema the prompt asked for, so an invalid
fixture cannot enter the set.
