# Salvage console: design pack

Nine files, enough to design and wire the frontend without guessing. Salvage is an AI agent that
detects payment-failure clusters for a Razorpay merchant, diagnoses the cause, and acts inside hard
limits. This console is its operator surface.

## Read in this order

1. `BOARD_CORRECTIONS.md` first. It overrides the spec where they disagree, lists what the API
   does not return, and explains why an empty tile on the board is usually correct rather than
   broken. It also names three fields in the samples that must never be shown as a ratio.
2. `04_FRONTEND_SPEC.md` is the contract for everything the corrections do not touch. All seven
   pages, what each shows, and the build order. It is a frozen M1 document written before the API
   existed, so trust the corrections over it.
3. `salvage_api_samples.json` is real output from a live run, scenario S1 seed 1, agent arm. Every
   shape is exact. Long arrays are capped at five entries with a bare string appended in place of
   the rest, which will break a naive `.map`, see corrections section 3. The real responses carry
   hundreds of entries, so design for volume.
4. `segment_roster.json` is every segment key the detector can produce, 33 of them, with the
   expected attempt count per 15 minute window. The overview response omits any key below the 20
   attempt floor, so this is the only way the board can tell "below detection floor" from
   "does not exist".
5. `types.ts` is the TypeScript shape of everything in that JSON.
6. `primitives.tsx` is the existing component vocabulary.
7. `Overview.tsx` and `IncidentDetail.tsx` are the two hardest pages: the segment heatmap with a
   merchant-wide row pinned at the top, and the evidence packet with both diagnoses side by side
   plus the ledger slice for that incident.
8. `PITCH.md` is optional, for tone and for why contact volume sits beside revenue everywhere.

## Constraints, not preferences

- **Recharts only, no component library.** The dependency set is fixed. A design assuming shadcn,
  MUI or similar cannot be built.
- **Every data region needs loading, empty and error states.** The `Region` primitive enforces
  this. The console is demoed live against a running simulation, so a design that assumes data has
  already arrived will break on screen.
- **The dashboard token lives in React state, never in localStorage.** A page reload re-prompts.
- **Read routes are open on loopback. Mutating routes need `Authorization: Bearer <token>`:**
  `POST /api/control/kill-switch`, `/api/sim/run`, `/api/sim/stop`,
  `/api/incidents/{id}/close`, `/api/escalations/{id}/decision`, `/api/storefront/order`.
- **Live updates arrive over server-sent events** at `GET /api/stream`. One shared EventSource for
  the whole console. Event names are a fixed set: `sim.tick`, `incident.opened`,
  `escalation.opened`, `control.kill_switch`.
- **Revenue is never shown without contact volume beside it.** This is a product rule, not a
  layout preference: the whole argument is recovery per message, so a card showing rupees alone
  misrepresents the result.

## The seven pages

| page | what it is for |
| --- | --- |
| Overview | merchant-wide success rate, segment heatmap with the merchant row pinned first, open incidents, today's recovery |
| Incidents | the list, filtered by state |
| Incident detail | evidence packet, rules and model verdicts side by side, action timeline, ledger slice |
| Escalations | the queue; approving or rejecting requires a written note |
| Ledger | browse, verify the hash chain, export JSONL |
| Results | the evaluation tables, served from the same JSON that produced the results document |
| Storefront | a checkout page showing what a customer sees when the agent sets a display hint |
| Scenario Runner | start a run, watch it over SSE, flip the kill switch |

## Tone

This is an operator console for money movement, not a marketing page. Density over whitespace,
numbers over icons, and every number legible at a glance. The most important visual job is making
a refusal as readable as an action: most of what this agent does is decline to do things, and the
gate that refused is the interesting part.
