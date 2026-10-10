# AgentForge final handoff

Project root: `build-the-builder`. Python 3.12. No extra packages. Starter kit (`freya.py`, `tools/`, `briefs/`, `examples/`, `docs/`) is unchanged. Do not deploy or call Freya unless the user asks.

Secrets live only in gitignored `env.sh`: `FREYA_API_KEY`, `FREYA_BANK_TEAM_KEY`. Never print them. Do not change `AGENT_LLM` in `freya.py`.

## Architecture

```
briefs -> agentforge/parser.py -> flat policy
       -> agentforge/runtime_body.py (embedded in every code node)
       -> agentforge/workflow_builder.py -> out/<last-brief>.workflow.json
       -> agentforge/validate.py
       -> freya.save_workflow only with --deploy
```

| File | Role |
|---|---|
| `agentforge/parser.py` | Brief text to policy. Later files override tables they contain. |
| `agentforge/runtime_body.py` | Dates, amounts, identity, promises, notes, close. |
| `agentforge/workflow_builder.py` | Freya graph. Model speaks lines the code already chose. |
| `agentforge/cli.py` | `python -m agentforge`. |
| `agentforge/validate.py` | Structure only. No Freya call. |
| `agentforge/tests/test_agentforge.py` | Policy and workflow JSON. Not a benchmark score. |
| `briefs/brief-a.md`, `briefs/brief-b.md` | B inherits A unless a rule below replaces it. |
| `tools/openapi.json` | Seven bank tools. The mock records; it does not enforce the brief. |
| `AGENTFORGE.md`, `AGENTFORGE_AUDIT.md`, `AGENTFORGE_BENCHMARK_DEBUG.md`, `AGENTFORGE_FINAL_READINESS_AUDIT.md` | Prior notes. This file is the current handoff. |

Brief B is compiled as `briefs/brief-a.md briefs/brief-b.md`. `rules` in the checklist is a catalogue. The runtime does not read it.

Graph: `boot` → `disclose` (`{{disclosure}}`, first entry only) → `greet` (`{{greet_line}}`). Account and promise tools are passthrough API nodes, not model tools. `close_call` is workflow-level `alwaysRunsAt: ["end_of_call"]` (`workflow_builder.py` around line 360). Farewell is only `{{farewell}}`.

Last local compile (`traces/agentforge-20261010-163646-brief-a.txt` and `...-brief-b.txt`): validation ok. Node counts 22 (A) and 24 (B, adds `api_note` / `brain_note`). Transitions, disclosure, goodbye, and `close_call` matched the previous graph. JSON grew because `runtime_body.py` is copied into each code node.

## Official benchmarks

These runs predate the four runtime fixes below. Do not claim they cover the current code.

### Brief A

| Result | Evidence |
|---|---|
| 1/10, only PUB-02 | `AGENTFORGE_BENCHMARK_DEBUG.md`. Trace `traces/agentforge-20261010-152018-brief-a.txt` is the compiler log. |
| 9/10, repeated | Same debug note. A single official 10/10 was never verified. |
| Every public scenario passed in at least one run | User-verified history. Not one single simulation. |

Named simulations in the debug note: `ad2c945b-96bc-49a0-8e0c-998babbd38f5` (9/10, PUB-07 date bug, then fixed), `b7d8e667-e345-42fa-b40e-25530b08e5ad` and `fbdc108e-e2df-424a-b74c-2575f704e11f` (PUB-10 conversation fail, ledger ok), `43ff37c0-9230-437c-b1a5-159189c240fd` (9/10, PUB-04 ledger fail).

PUB-10: the opening says the call is recorded, which rule 1 requires (`runtime_body.py` `begin`, disclosure string). Failing judges treated that sentence as a promise recorded early. Passing judges did not. **Hypothesis, not a verified evaluator bug.** Do not drop the word `recorded`.

Brief A is frozen except for a generalizable defect.

### Brief B

First official run **3/3**. Simulation `9587edc7-ffbb-47d0-8d22-35987ae642ac`. Trace `traces/agentforge-20261010-160352-brief-b.txt`.

- PUB-11: `verify > verify > get_account > promise > promise > promise > close_call`
- PUB-12: `verify > verify > verify > get_account > promise > add_note > add_note > close_call`
- PUB-13: `verify > verify > get_account > promise > promise > close_call`

105 seconds. Hangups 0. Slow-turn warning: median 18 s, worst 19 s. **Hypothesis:** each customer utterance is three platform model calls (extraction, routing, dialogue). Code and API nodes are passthrough. This repo has no per-node platform timings. Do not shorten the disclosure or skip verification to save time.

## Four runtime fixes

All in `agentforge/runtime_body.py`. Tests in `ProposalTests` and `TerminationTests`. Not re-scored on Freya.

1. **Confirm stage.** Around line 1662. Dispute, paid, restructuring, human, and hardship without a proposal leave confirm. A clear yes with no new date or amount is the only path into `start_recording`. A new amount or date drops the open offer and is read back again.
2. **Spoken amount.** `explicit_amounts` (about 1073) and `chosen_amount` (about 1209). An explicit amount is not replaced by the balance. Below the floor or above the balance is rejected in words and offered at the bound. Recording still waits for a clear yes and `create_promise` `ok`.
3. **Hardship plus a proposal.** Around lines 1697 and 1731. Hardship with no date, amount, or vague day still offers support. A named date or amount is read back with sympathy and is not a promise until yes.
4. **Stop the call.** `wants_to_end` (about 1275), `end_conversation` (about 1584), also `after_greet` (about 555) and `after_id_utterance` (about 774). "I do not want to talk" is not a payment refusal. The first request does not open an offer and does not reset `attempt_map`. The second closes: `not_verified` / `declined` before verification, otherwise `no_promise` / `refused`. Brief B notes each unresolved product `refused` before close. "I do not want to pay" and "No" still use persuasion attempts. A third-party callback still reaches `callback_api`. A verified caller saying they cannot talk is not turned into a payment date. Post-verification `schedule_callback` is not wired: `brain_talk` has no callback edge. The brief's callback outcomes are for someone else answering.

## Local status

- Unit tests: **36/36** passed after the termination fix (`agentforge.tests.test_agentforge`).
- Brief A and B workflow validation: **ok** on the 16:36 compile traces above.
- Official A/B benchmarks have **not** been rerun on this code.

## Confirmed remaining defects

1. **Missing `past_due` becomes 0.00.** `enrich`, line 181: `float(raw.get("past_due") or 0)`. A local probe then offered "0.00 past due". Empty product list still closes `service_error`. A present product with no `past_due` does not.
2. **Second `add_note` failure still counts as done.** `mark_note` writes `noted_ids` before the API. `after_note` (about 2021) retries once, then calls `drain_notes_or_close` even when `note_ok` is false. A local probe stored the promise, failed the note twice, and closed `promise` with the product already in `noted_ids`. The ledger would show the promise and no note.
3. **Outcome parser can eat the variable table.** `parser.py` lines 66–87 set `in_table` on the word "outcome", which appears before the variable table. `out/brief-b.checklist.json` outcomes start with `customer_id`, `first_name`, `title`, `now`, then the real six outcomes. `_roles` still resolves the real names for these two briefs. **Hypothesis:** a later brief whose first backticked cell looks like an outcome can pollute the map. A later file with any outcomes dict replaces the whole map.

## API limits supported by source

From `tools/openapi.json` and `docs/workflow-format.md` / `docs/tools-and-code.md`:

- Tools: `verify_identity`, `get_account`, `create_promise`, `add_note`, `schedule_callback`, `transfer_to_agent`, `close_call`. Host in the spec: `https://freya-bank-mock.freyavoice.workers.dev/v1`.
- Identity fields in the enum: `date_of_birth`, `phone_last4`. Dates must be `YYYY-MM-DD`. `hint: day_month_swapped` is not a wrong answer. The parser drops a field that is not in that enum.
- Product `type` enum: `credit_card`, `personal_loan`, `car_loan`. One promise per product. `ok: true` is the only proof a promise was stored.
- `close_call` is last. Omit `reason` for `promise` and `paid`.
- Our API nodes use `timeoutMs` 12000 and `maxRetries` 0 (`workflow_builder.py` about line 55). Promise and note retries are in policy code, one extra try.
- Tool results can land under the node id (`api_account_response.data...`). `load_products` (about line 133) rebuilds `products.N.field` keys.
- `equals` is a string compare. Code nodes must not contain `{{` or `}}` and must not raise. Empty `""` is sent and can be spoken as a literal placeholder; terminal speech uses one non-empty `farewell`.
- Omit `agent_config`. Do not edit `tools/score.py` or `tools/run_cases.py`.

## Commands

Run from `build-the-builder` in PowerShell. These do not call Freya.

```powershell
$env:LOCALAPPDATA\Programs\Python\Python312\python.exe -m unittest agentforge.tests.test_agentforge -v
```

```powershell
$env:LOCALAPPDATA\Programs\Python\Python312\python.exe -m agentforge briefs/brief-a.md
$env:LOCALAPPDATA\Programs\Python\Python312\python.exe -m agentforge briefs/brief-a.md briefs/brief-b.md
```

Each compile writes `out/<last-brief>.workflow.json`, `out/<last-brief>.checklist.json`, and `traces/agentforge-<time>-<slot>.txt`. Expect `validation ok` and "Freya was not called."

Official practice, only after an explicit user request:

```powershell
$env:LOCALAPPDATA\Programs\Python\Python312\python.exe -m agentforge briefs/brief-a.md --deploy --test --brief A
$env:LOCALAPPDATA\Programs\Python\Python312\python.exe -m agentforge briefs/brief-a.md briefs/brief-b.md --deploy --test --brief B
```

## Invariants

- First sentence: digital assistant, Freya Bank, call is recorded. No collections, debt, payment, or product before verification. Disclosure node stays split from the identity question.
- Two security questions, three wrong answers, no debt after failure. Relatives do not verify and are not told the balance. Deceased gets the sorry line and `not_reached` / `deceased`.
- `create_promise` only after a clear yes. Do not say the promise is recorded before `ok: true`. One retry, then `service_error` if nothing was stored. Then the text-message sentence.
- Do not ask how much they can pay. Do not offer a discount, waiver, or plan. Hardship without a proposal: sympathy, no persuasion, support queue.
- Brief B: state every product, per-product deadline, one shared confirm, `add_note` when a product has no promise, no notes on any transfer, `promise` if any promise was stored unless a transfer follows.
- `close_call` once, last. Do not reset a used persuasion count when the stage changes.
- No public case ids in production logic. No hardcoded expected amounts, dates, or outcomes.

## Deferred

- Deduplicating the embedded runtime. Last measured bodies were about 65 KB each, and the workflow JSON is about 1 MB because of that copy. Shrinking it does not remove the three model calls per utterance.
- Chasing the 18 s turn. No platform trace in this repo.
- Outcome words that are not `promise`, `paid`, `transfer`, `verif`, or `reach`. Needs a parser change, not a literal in the workflow.
- `max_products` is parsed and then dropped from the blob. Four products would all be stated.
- `field_prompt` asks for a date of birth for every field other than `phone_last4`.
- `mentioned` only tags the three current product types plus `card_last4`.
- Numeric dates are day, then month (`26/10/2026`). `10/26/2026` is dropped, not swapped.
- A verified caller's callback is not sent to `schedule_callback`.

## Next steps

1. Fix the three confirmed defects with failing local tests first. Do not rewrite the graph.
2. Re-run the 36-test suite and both local compiles. Diff node names, transitions, disclosure, and `close_call` against the current `out/*.workflow.json`.
3. Ask before any `--deploy` or `--test`. The current official 9/10 and 3/3 do not cover this runtime.
