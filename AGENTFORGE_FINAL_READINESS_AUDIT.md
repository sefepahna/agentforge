# AgentForge final readiness audit

Date: 2026-10-10. Source inspection plus local probes. No Freya calls. No score is claimed.

Probes used the installed policy engine (`parse_briefs`, `prepare_account`, `after_customer`, `after_record`, `after_note`) with mock products. Clock in every probe: `2026-10-14T11:00`.

## What is already solid

Do not rewrite these paths. They are what produced Brief A 9/10 and Brief B 3/3 (`9587edc7-ffbb-47d0-8d22-35987ae642ac`).

- Opening is one disclosure node (`{{disclosure}}`, first entry only) then `{{greet_line}}`. Debt words stay off both lines. `close_call` is an `end_of_call` tool. Promise speech is the text-message sentence, and only after `create_promise` is `ok`.
- Identity uses ISO dates, spoken years, a three-miss cap, and `wrong_answers_left == 0`.
- Products load from node-prefixed keys (`api_account_response.data.products.N.*`).
- Brief B inheritance keeps Brief A holidays, bands, floors, and outcomes, and turns notes and multi-product on. Later files replace a table only when that file contains one.
- One shared read-back, per-product deadlines, `add_note` for products without a promise, and `promise` if any promise was stored, are implemented and covered by `MultiProductTests`.
- Retries of a failed `create_promise` do not append the product id until `ok` is true.

`rules` in the checklist is a catalogue. The runtime never reads it. Policy is the flat blob in `runtime_body.py`.

## Findings

Severity is impact on an unseen brief, not on a named public id. Cost is the size of a safe code change.

### 1. High — read-back ignores dispute, paid, transfer, and hardship

Evidence: `after_customer`, `phase == "confirm"`. A yes with no date calls `start_recording`. A no clears `pending` and treats it as a refusal. Anything else, including a new intent, repeats "Do you confirm?" and returns.

Local probe, one card, past due 420, after "I can pay the full amount today" (phase `confirm`, pending full amount today):

| Utterance | Route | Outcome |
|---|---|---|
| "I need a new payment plan." | `speak` | still confirm, pending kept |
| "This debt is not mine." | `speak` | still confirm |
| "I already paid this." | `speak` | still confirm |

The same plan sentence before confirm routes to `transfer` / `restructuring`.

Impact: rules 32, 39, 40, and 41 do not run once a read-back is open. A customer who disputes or asks for a plan at the confirm step can be talked back into a promise.

Cost: low. Handle those intents inside the confirm branch before the re-ask. Keep a clear yes as the only path into `create_promise`.

### 2. High — a named amount is discarded

Evidence: there is no amount parser. `amount_for` returns `past_due` or, if the text matches `is_too_much`, `floor`.

Local probe, floor 126, past due 420:

| Utterance | Pending amount |
|---|---|
| "I can pay 200 on Friday." | 420.00 |
| "I can only pay 10 dollars on Friday." | 420.00 |
| "Change the amount to 200." during confirm | 420.00, confirm repeated |

Rule 27 says an amount from the floor through the full amount is accepted, and an amount under the floor is rejected once in favor of the floor. Rule 35 says a changed amount is checked and read back again. Both are skipped. "Too much" still offers the floor. That path is covered and should stay.

Impact: unseen customers who name a partial amount get a full-amount read-back. Confirming it stores the wrong promise.

Cost: medium. Parse a money amount, clamp it to the named product, and read it back. Do not treat a date or a product id as money. Lock the existing full-amount and floor tests first.

### 3. High — hardship plus a date does not record the promise

Evidence: `is_hardship` returns before `find_dates`.

Probe: "I lost my job but I can pay the full amount on Friday." Route `speak`, phase `hardship`, no pending row. Rule 32 says a date or amount the customer still names is recorded under sections 7 and 8, and hardship comes before persuasion, not before that recording.

Impact: a payable hardship call becomes a support offer. Public hardship cases that do not name a date are unaffected if the check stays "hardship and no usable date or amount".

Cost: low.

### 4. Medium — "I do not want to talk" is a payment refusal

Evidence: `is_no` matches "i do not want". There is no separate twice-said counter. Rule 45 says two such statements close as `no_promise` / `refused` after verification, and as `not_verified` / `declined` before it. Rule 42 still comes first for a human request.

Probe, late band (two attempts allowed), days late 14:

- First "I do not want to talk." opens attempt 1 (full amount on 16 October).
- Second opens attempt 2 (floor on 23 October). It does not close.

On an early product the second utterance happens to exhaust the one attempt and closes `refused`. That match is accidental.

Impact: late-band calls keep persuading after the customer has asked twice to stop. A fix that treats every "do not want" as rule 45 would also catch "I do not want to pay", which rule 30 says is a flat refusal and must still use persuasion. The matcher has to require "talk".

Cost: low if the phrase is narrow.

### 5. Medium — natural-language rules that are not tables are silent

Evidence: `parse_briefs` copies numbered lines into `rules` and never puts them on the blob. `runtime_body.py` branches on fixed English phrases (`is_paid`, `is_dispute`, `is_restructure`, `is_human`, `is_hardship`, `party_kind`). `_kind` is unused.

A later brief can change a sentence, a queue name that is not in the OpenAPI enum, or a new outcome word. `_roles` only maps names containing `promise`, `paid`, `transfer`, `verif`, or `reach`. The audit in `AGENTFORGE.md` already says other outcome words need a parser change. That limit is still true.

`max_products` is parsed (Brief B: 3) and then dropped. It is not on the blob. A four-product list is all stated (`past due` counted 4). The current OpenAPI enum is still three product types, so this is latent.

Impact: the compiler will validate a workflow that ignores a new sentence in the brief.

Cost: high if every sentence is to be interpreted. Low for a checklist warning when a numbered rule matches none of the implemented detectors.

### 6. Medium — outcome parse also eats the variable table

Evidence: `out/brief-b.checklist.json` outcomes start with `customer_id`, `first_name`, `title`, `now`, then the real six outcomes. Cause: section 1 contains the word "outcome", so `in_table` is already true when section 2's variable table is read (`parser.py`).

`_roles` still resolves `promise`, `paid`, `transferred`, `no_promise`, `not_verified`, `not_reached` for these two briefs. Local roles were not wrong.

Impact: a later brief whose first backticked cell after the word "outcome" looks like an outcome can pollute the map until a real table overwrites the same key. A later file with a non-empty `outcomes` dict replaces the whole map (`_merge`), it does not merge cell by cell.

Cost: low. Start the outcome table only on an Outcome header row.

### 7. Medium — failed `add_note` is still treated as done

Evidence: `mark_note` writes `noted_ids` before the API. `after_note` retries once, then calls `drain_notes_or_close` even when `note_ok` is false.

Probe: promise stored for `p1`, note `refused` armed for `p2`, `note_ok` false twice. Result: route `close`, outcome `promise`, `noted_ids` contains `p2`. The ledger would show the promise and no note.

Impact: Brief B rule 8 fails closed. The promise outcome itself matches rule "promise wins". The missing note is the defect.

Cost: low. On a second failure, close `no_promise` / `service_error` only when nothing was recorded; when a promise exists, keep `promise` but do not pretend the note succeeded. Say the note could not be stored. Do not send a second note for a product already accepted by the API.

### 8. Medium — bad account fields become a real offer

Evidence: `enrich` uses `float(past_due or 0)`. Missing `past_due` produced the coach line "0.00 past due". `days_late` 0 and 60 both become band `unknown`, deadline today, one attempt (`band_for` default).

Impact: a malformed `get_account` can record a zero promise or ignore the real band. An empty product list already closes `service_error`. A present but incomplete product does not.

Cost: low. If `past_due` is missing or `days_late` matches no band, close `service_error` for that product (note it in Brief B) instead of offering 0.

### 9. Low — date and identity parsers still miss common shapes

Measured:

| Input | Result |
|---|---|
| "the twenty sixth of October" | 2026-10-26 |
| "26/10/2026" | 2026-10-26 (day, then month) |
| "10/26/2026" | no date (month 26 is invalid, not swapped) |
| "twenty first of August nineteen ninety two" | 1992-08-21 |
| "the twenty-first of August nineteen ninety-two" | empty, because `take_under_hundred` stops on "the" |

`10/26/2026` is dropped, not read as October. That matches rule 11 (day, then month). The risk is a repeated identity or date question, not a wrong ISO date.

`mentioned` only tags `credit_card`, `personal_loan`, `car_loan`, and `card_last4`. A new product type gets a slug label and is not selected by its name.

`field_prompt` asks for a date of birth for every field other than `phone_last4`. The parser also drops an identity field that is not in the OpenAPI enum (`date_of_birth`, `phone_last4` only). A brief that adds postcode would keep asking the two current questions.

Cost: low for the leading "the" in `parse_dob`. New fields need an OpenAPI change as well as a prompt; do not invent a field the tool rejects.

### 10. Low — workflow weight, not the 18 second turn

Measured from `build_workflow` on the current briefs:

| Workflow | Nodes | Code nodes | Conversation nodes | One code body | JSON size |
|---|---|---|---|---|---|
| Brief A | 22 | 11 | 5 | 64,899 chars | 795,981 bytes |
| Brief B | 24 | 12 | 5 | 64,901 chars | 869,391 bytes |

`runtime_body.py` is copied into every code node so the sandbox can run it. That is why the file is large. Dialogue does not see that source. Routing on these nodes is `equals` on `route` plus `always`, which does not call a model.

Each customer utterance on `greet`, `id_talk`, `present`, or `cb_talk` is still three platform model calls (extraction, routing, dialogue). Code and API nodes are passthrough. One negotiation turn is: those three calls, then `brain_talk`, then maybe one bank call, then TTS of `{{coach}}`.

The Brief B compiler trace (`traces/agentforge-20261010-160352-brief-b.txt`) records a 105 second simulation and does not record per-node timings. The reported median 18 seconds and worst 19 seconds are agent turns. This repo cannot see model queue time. 18 seconds is too large to be the 65 KB code exec or one bank POST with `timeoutMs` 12000 and `maxRetries` 0. Those are the only timings we set. The platform warning about model load fits the trace better than node count.

What we can remove without touching policy: duplicate source in the JSON, if the sandbox allows one shared snippet. That shrinks the upload. It does not remove the three model calls per utterance. Do not shorten the disclosure or skip verification to buy time.

## Hypothetical, not shown as bugs

- The PUB-10 "recorded" disagreement is still an evaluator conflict. The disclosure line is required by Brief A rule 1. No assistant line in the audited code says the promise is recorded before `ok`.
- If `create_promise` stores the row and the response mapping misses `ok`, `after_record` retries once. The bank allows one promise per product, so the retry may fail and become `service_error` after a real store. Not reproduced here.
- Extraction can leave `user_said` empty. The code then repeats the coach line. That depends on the extraction model, which these probes do not run.
- A later brief that restates one band row replaces the whole band list. A later brief that never mentions bands keeps Brief A. Not a bug for A then B.
- `close_with` on a transfer still appends the text-message sentence if a promise was already stored. The outcome is `transferred`. Whether the extra sentence hurts a judge is unknown.

## Do not change

- Disclosure wording and the split between `disclose` and `greet`.
- Third-party callback, deceased, and wrong-number closes.
- "Recorded" only after `create_promise` returns ok, with one retry.
- Brief B: state every product, one confirm, notes only when not transferring, `promise` if any store succeeded.
- `tools/score.py`, `tools/run_cases.py`, and `freya.py`.
- Do not deploy or start another official simulation from this audit.

## Implementation order

1. Add local tests that fail on findings 1, 2, 3, 4, and 7. Use mock products and new wording. No public case ids. No Freya.
2. Fix confirm-phase intents (1) and hardship-plus-date (3). Re-run the existing 22 tests.
3. Add amount parsing (2) with floor and full-amount clamps, including a change during confirm (rule 35).
4. Add a narrow "do not want to talk" counter (4) that does not catch "do not want to pay".
5. Treat a second `add_note` failure and a product with no `past_due` or no band as service errors (7, 8).
6. Stop the outcome scanner on the variable table (6). Add a checklist warning for numbered rules with no detector (5).
7. Accept leading "the" in `parse_dob` (9). Leave US month-first dates as invalid.
8. Regenerate `out/brief-a.workflow.json` and `out/brief-b.workflow.json`, validate both, and diff node names, disclosure, and tool gates against the current files.
9. Ask before any `--deploy` or `--test`.

Findings 1–4 are general defects in Brief A as well as Brief B. They are in scope. They are not a reason to retune the disclosure or the known-good public paths.
