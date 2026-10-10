# AgentForge Brief A benchmark debug

Before: **1/10** (2026-10-10 15:26:08, 332s). Only PUB-02 passed.
Trace of that run: `traces/agentforge-20261010-152018-brief-a.txt` (compiler log only).
Ledger: `results/log.jsonl`. Workflow validated; the failures are runtime wiring.

The bank mock answered `get_account` correctly. Freya stored the body under the **node id** `api_account_response`, not under the function name `get_account_response`.

## Root causes

| Cause | Evidence | Fix |
| --- | --- | --- |
| Product loader ignored node-prefixed keys | PUB-01/04/05/07/09 reached `get_account` (POST `/v1/get_account`, `customer_id` set, `ok: true`, products present, `account_ok=true`). `prepare_account` saw an empty list and closed `no_promise` / `service_error` with "I could not open the account." | `load_products` now rebuilds products from any `*.products.N.field` key, including `api_account_response.data.products.0.*`. |
| Empty string is not interpolated | PUB-04/05/09 spoke literal `{{promise_line}}`. Farewell was `Thank you. I could not open the account. {{promise_line}} Goodbye.` while `promise_line` was `""`. Non-empty `extra_line` did interpolate. | Terminal speech is only `{{farewell}}`. `close_with` writes one non-empty sentence. |
| Spoken years were rejected | PUB-06/08/10 stayed on `id_talk` → `brain_id` → `id_talk`. Extracted text was `Seventeen May nineteen eighty six.` `parse_dob` never set `id_field` / `id_answer`, so `verify_identity` never ran. `max_node_turns` resets on every hop, so the 12-turn cap did not stop the loop (728 messages on PUB-06). | Word days and `nineteen` / `twenty` / `two thousand` years parse to ISO. Three consecutive misses, or eight identity turns, close `not_verified` / `failed` with the app/branch line. |
| Three wrong answers never reached the API | PUB-03 said `Twelve July nineteen ninety-one.` The parser rejected it, so `wrong_answers_left` never hit 0 and the app/branch line never played. | Same date parser. `after_id_api` also reads `api_verify_response.data.verified`, `all_verified`, `wrong_answers_left`, and `ok` when mapped `id_*` vars are blank. Left = 0 closes `not_verified` / `failed`. |
| Hardship and transfer never ran | PUB-05 and PUB-09 died in `prepare_account` before `present` / `after_customer`. | Once products load, the existing offer, partial, already-paid, hardship, and restructuring paths run. |
| Post-hook claimed a recording on every `ok` | `what_to_do_next` was set to "Recorded. You may say so." on `verify_identity` and `get_account` as well as promises. | Header is stripped only. Promise speech still requires `create_promise` success in code. |

PUB-02 (third party, callback, `close_call`) did not use `get_account` or the date parser. That path is unchanged.

## Later date bug (second official run)

Simulation `ad2c945b-96bc-49a0-8e0c-998babbd38f5`, trace `traces/agentforge-20261010-153438-brief-a.txt`: **9/10**. Only PUB-07 failed.

Customer said `Monday the twenty sixth.` `ordinal_date` matched the shorter word `sixth` inside `twenty sixth`, so the day became 6. That day in November is after the band deadline, and `fit_date` replaced it with the deadline `2026-11-02`. Expected snap: 26 October is a holiday, next business day `2026-10-27`.

Fix: match ordinal phrases longest-first, with word boundaries. A named month in the same sentence selects that month.

## Opening disclosure

PUB-07 and PUB-10 in both 9/10 runs spoke the same first line, once, from node `greet`, before any identity question or tool: `Hello, this is a digital assistant calling from Freya Bank. This call is recorded. Am I speaking with ...?` It was not omitted, duplicated, or late, and it did not mention collections or the debt. The passing PUB-10 judge treated that sentence as the required call disclosure. The failing judge treated the same Message 0 as a promise being recorded early. The wording stays. It now plays from a passthrough `disclose` node (`{{disclosure}}`, first entry only) and the identity question stays on `greet`.

## PUB-10 evaluator

Passing judge (`ad2c945b-96bc-49a0-8e0c-998babbd38f5`) and failing judges (`b7d8e667-e345-42fa-b40e-25530b08e5ad`, `fbdc108e-e2df-424a-b74c-2575f704e11f`) heard the same opening fact: the call is recorded, before identity. The failing text cites Message 0, `This call is recorded`, against "does not say recorded before a successful call". The passing text says that same Message 0 is the call disclosure, and that `I will record` before the tool is future tense. The ledger matched in the pass and the latest fail. No assistant line in the latest fail says the promise was recorded before `create_promise` succeeded. The success line is the brief's text-message sentence. Brief A rule 1 is not a quoted script; rules 2, 9 and 38 are. Rule 1 still requires saying that the call is recorded. A paraphrase that keeps the word `recorded` does not remove the token the failing judge named, so the opening was not changed.

## Fourth official run

Simulation `43ff37c0-9230-437c-b1a5-159189c240fd`, trace `traces/agentforge-20261010-154748-brief-a.txt`: **9/10**. Disclosure was one assistant line, then `Am I speaking with Ms Hoffmann?`, then identity. PUB-10 passed. PUB-04 ledger failed: customer named 6 November, the agent offered 16 October and then the floor on 23 October, the customer refused, close was `no_promise` / `refused`. Expected promise was the full amount on 23 October. The conversation judge marked the case passed; the bank ledger did not.

## Third official run

Simulation `b7d8e667-e345-42fa-b40e-25530b08e5ad`, trace `traces/agentforge-20261010-154003-brief-a.txt`: **9/10**. PUB-07 passed. PUB-10 ledger is correct (failed `create_promise`, one retry, one promise, `close_call`). The judge failed the conversation check because the required opening line says `This call is recorded` before the tool succeeds. The same opening passed PUB-10 on the previous run. The disclosure stays, because Brief A requires it in the first sentence.

## Failed scenarios

- **PUB-01, PUB-04, PUB-05, PUB-07, PUB-09** — node `api_account` succeeded; transition `account` → `brain_prepare` → `prepare_account` → `goodbye`. Request was valid. Failure was `load_products` returning `[]`, then `close_with(..., reason_service_error)`.
- **PUB-04, PUB-05, PUB-09** — node `goodbye` `spoken_message` contained `{{promise_line}}` while that variable was `""`.
- **PUB-05** — no empathy because the call never entered negotiation.
- **PUB-09** — no `transfer_to_agent` for the same reason.
- **PUB-06, PUB-08, PUB-10** — node `brain_id` / `after_id_utterance`, route stayed `speak`. No API request. Unbounded re-entry.
- **PUB-03** — same parser miss, so the three-attempt terminal in `after_id_api` never ran.
- **PUB-02** — passed. Do not change the third-party callback close.
