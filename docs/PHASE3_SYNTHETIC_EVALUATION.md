# Phase 3 — Synthetic brief evaluation

Date: 2026-10-11. Branch `feature/hidden-brief-readiness`. Parent commit `48b2cbb6717007a593ad59af0bd6e6dbbefe6856`.

This phase is diagnostic. It does not change parser, prose extraction, workflow building, runtime, or the public workflows. A synthetic case that the compiler rejects is not a successful implementation of that policy. A synthetic case that validates while dropping a stated limit is a failure.

No live Freya call, simulation, or `save_workflow` ran. Rejected briefs were passed through `main(..., "--deploy")` only with `agentforge.cli.KIT` pointed at a temporary directory and `freya.save_workflow` replaced by a mock that raises if called. The mock was not called.

## How to run

Unique original suite (prose and regression included once via `load_tests`):

```text
python -m unittest agentforge.tests.test_agentforge
```

Result on this phase: 81 tests, OK.

Synthetic diagnostic suite:

```text
python -m unittest agentforge.tests.test_synthetic_briefs
python -m agentforge.tests.synthetic_eval
```

Result: 18 tests, OK. The runner prints the same eight-case matrix.

`python -m unittest discover agentforge/tests` reports 119 because `test_agentforge.load_tests` loads the prose and regression modules again. Those 20 tests are counted twice: 81 + 20 + 18 = 119. The unique total of the two intended commands is 99. Passing the diagnostic suite does not mean an unseen brief is ready.

Public briefs were compiled offline inside the original suite (`PublicBaselineTests`) and the protected file hashes were checked again by the synthetic safety test.

- `out/brief-a.workflow.json`: `6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da`
- `out/brief-b.workflow.json`: `56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf`

Both files were byte-identical after the runs. Tags were not moved.

## Oracle

Every case except SYN-02 is a one-field edit of `syn01_structured.md` (Harbor Mutual, invented bands, holidays, floors, and hours). SYN-02 is a labeled field list with the same invented values and no markdown tables. SYN-08 has two probes because a recognized contradiction and an unrecognized one do not behave the same way.

Ideal means the policy a hidden brief would need. Supported means what this compiler can do today. Classification uses the supported reaction:

| Label | Meaning |
|---|---|
| PASS | Supported syntax compiled to the stated policy and validation was empty. |
| SAFE_REJECT | The compiler refused to deploy and said why. The policy was not applied. |
| FAIL | Validation was empty while a stated rule was omitted or replaced. |
| UNSUPPORTED | The format is outside the reader. Here it overlaps SAFE_REJECT. |

## Case matrix

| Case | Input variation | Ideal policy | Observed | Class |
|---|---|---|---|---|
| SYN-01 | Structured markdown tables, holidays, floors, six outcome names, DOB plus phone, three wrong answers, one product | Bands `2-10 amber / 9 days / 1 attempt` and `11-30 crimson / 4 days / 2 attempts`. Floors `minimum_payment` and `instalment_amount`. Bank Harbor Mutual. Callback 09:15–16:45. | `build` errors empty. 22 nodes, initial `boot`. Credit-card floor applied as 40 against past-due 200. Disclosure is "We are recording this call." `max_wrong` and `max_products` are parsed and absent from the runtime blob. | PASS for the supported table contract. The missing blob fields are measured in SYN-05 and SYN-06. |
| SYN-02 | `holiday:`, `days_late_low:`, `outcome.promise:`, `floor.credit_card:`, `max_wrong: 2`, `identity.field: postcode` | Those labels become the same policy as SYN-01, with a wrong-answer limit of 2 and postcode identity. | Holidays 2026-03-17 and 2026-07-04 were kept. Bands, outcomes, and floors are empty. Callback stays the default 10:00–19:00. `max_wrong` stays 3. Identity blob falls back to date of birth and phone. Deploy errors: unresolved bands, unresolved outcomes, unbound floor lines (the lines start with `floor`). Mocked `--deploy` skipped. | SAFE_REJECT. Format is UNSUPPORTED. Not a successful bind. |
| SYN-03 | Floor sentence without `the floor is` or `` `field` for a product `` | Credit-card floor 40, personal-loan floor 15 | Errors empty. `floors` is `[]`. Runtime floor becomes the past-due amount: 200 and 80. | FAIL. Silent omission. |
| SYN-04 | Second file: the amber and crimson schedule is withdrawn and no longer applies | Amber and crimson bands removed, or replaced by a stated successor | Bands, floors, and outcomes stay equal to SYN-01. Diagnostic `policy withdrawal was detected but cannot be applied`. Mocked `--deploy` skipped. | SAFE_REJECT. Detection is not application. |
| SYN-05 | `Two wrong answers` instead of three | The second unreadable identity answer closes `not_verified`. | Policy `max_wrong` is 2. The key is not in the blob. Errors empty. Local misses on "banana": routes `speak`, `speak`, then `close` on miss 3 with `not_verified`. A separate one-line brief `0 wrong answers` parses as 0 and merges back to the default 3. | FAIL. Silent omission on the local miss counter. |
| SYN-06 | `up to four products` | At most four products are negotiated | Policy `max_products` is 4 and blob `multi` is `yes`. `max_products` is not in the blob. Errors empty. Five account rows all remain after `prepare_account`. Node set stays the 22-node no-note graph. | FAIL. Silent omission. |
| SYN-07 | The only security question is the customer postcode | Ask for postcode, or refuse to deploy because the tool enum has no postcode | Parsed `id_fields` is empty. Blob substitutes `date_of_birth` and `phone_last4`. The first prompt is "Please tell me your date of birth." The numbered rule text still contains "postcode". Errors empty. | FAIL. Silent substitution. |
| SYN-08a | Two callback windows in one file: 09:15–16:45 and 08:00–12:00 | Reject the contradiction | Errors empty. First window wins: 09:15–16:45. No diagnostic. | FAIL. Silent first-match. |
| SYN-08b | Outcome table removed. Prose says promise has no reason and promise uses reason refused | Reject the contradiction | Outcomes `{}`. Errors include unresolved outcomes and `prose outcome statement was ambiguous or conflicting`. Mocked `--deploy` skipped. Bands from the markdown table remain. | SAFE_REJECT. |

## Metamorphic results

Compared on the executable signature: bands, outcomes, floors, holidays, bank, spoken lines, callback, identity fields, notes, multi, parsed limits, and diagnostics. All four equivalent variations matched SYN-01 and validated clean.

| Variation | Result |
|---|---|
| Swap the Amounts and Callback sections | Executable policy matches. Numbered-rule catalogue text is the same set in a different order. Rule order follows file order and is not runtime policy. |
| Irrelevant sentences about a lobby mural | Executable policy and rule order match. |
| `##` changed to `###`, extra blank lines | Executable policy matches. The H1 bank heading still supplies Harbor Mutual. |
| Band table replaced by the supported prose form ("N to M days late are in the amber band" plus a business-day count and persuasion attempts) | Bands match the table exactly. The rest of the signature matches. |

Non-equivalence control: a later file that only says `from 08:00 to 12:00` overrides the base callback. The reverse order keeps 09:15–16:45. File order is precedence, not a paraphrase. That control validated both ways and was not treated as a defect.

## Coverage

Parsing that held:

- Markdown band rows and the supported prose band paragraph
- Outcome tables and the supported "use outcome … with reason" sentences, including an empty reason list
- Backtick floor bindings of the form `` `minimum_payment` for a credit card ``
- Holiday dates on a line that contains "holiday"
- Bank name from the H1 heading
- Callback `from HH:MM to HH:MM` (first match only)
- `N wrong answers` and `up to <word> products` onto the policy object
- DOB and phone last-four into identity fields when those phrases occur and the OpenAPI enum allows them
- Recording disclosure remains "We are recording this call."

Safe rejection that held:

- Missing bands or outcome roles block `unresolved_configuration`
- An unbound line that starts with "floor" or says "the floor is" without a field binding blocks deploy
- Withdrawal wording blocks deploy and does not delete inherited bands
- Conflicting prose outcomes block deploy
- Unsupported outcome names were already covered by the Phase 2 harness and were not re-deployed here

## Confirmed defects and silent omissions

These were executed in this phase.

1. Natural-language amount floors that do not match `` `field` for a product `` or "the floor is" are dropped. Validation passes. `prepare_account` then uses the past-due amount as the floor (SYN-03: 200 instead of 40, 80 instead of 15).
2. `max_wrong` is not copied into the runtime blob. The local unreadable-answer counter in `after_id_utterance` closes on the third miss (`id_miss >= 3`), including when the brief says two. This run did not send `wrong_answers_left` from `verify_identity`; that server-driven path was not re-measured.
3. `0 wrong answers` is parsed as 0 and then ignored, because the merge uses `if extra.get("max_wrong")`. The merged value stays 3, and 3 is still not in the blob.
4. `max_products` is not copied into the blob. Five products remain when the brief says four (SYN-06). Inspection of `runtime_body.py` found no read of `multi` either. The behavioral proof in this phase is the five-product run, not a separate one-product overflow test.
5. A requested identity field outside the OpenAPI enum (`date_of_birth`, `phone_last4`) is dropped. An empty field list is replaced with those two defaults, and the prompt asks for a date of birth (SYN-07).
6. A second callback window in the same file does not produce a diagnostic. `re.search` keeps the first window (SYN-08a).

## Intentionally unsupported, safely rejected

1. Labeled key-value codelists are not a general reader (SYN-02). Deploy stops because bands and outcomes are missing. Some labels are misread on the way: holiday dates are harvested, and a line beginning with `floor` is reported as an unbound floor rather than bound.
2. Withdrawals are detected and block deploy. They do not edit the inherited tables (SYN-04).
3. Contradictory outcome prose is discarded and blocks deploy (SYN-08b). Markdown tables still win when both are present; that conflict path was already in the prose suite and was not the SYN-08 fixture.

## Hypothetical risks not measured here

- `create_promise` still has no idempotency key. Phase 2 already locks the single retry. This phase did not add a new promise-write case.
- Post-verification callbacks are still absent. No synthetic case asked for one.
- Numbered rules are stored and not executed. SYN-07 shows a postcode rule surviving in the catalogue while the runtime asks for a date of birth. A full rule interpreter was not tested.
- Whether `multi: no` refuses a second product was not executed. The runtime source does not consult `multi`.
- Hidden-brief wording is not in these fixtures. Matching SYN-01 does not predict an unseen brief.

## Phase 4 fixes, by severity then regression risk

Do not start these without an explicit phase approval. Public briefs use three wrong answers, the backtick floor form, and DOB plus phone, so a narrow gate is safer than a new general parser.

1. SYN-07, high severity, lower regression risk. If the brief names an identity field that the enum drops, fail validation instead of substituting date of birth and phone. Public briefs name fields the enum allows, so they should stay deployable.
2. SYN-03, high severity, medium risk. Treat a clear minimum-payment or instalment sentence that did not bind as an unbound floor diagnostic, or bind the known field names. A wide net could block a public sentence that only mentions those words in passing. Keep the existing `` `field` for a product `` path unchanged and add a regression on Brief A floors.
3. SYN-05, high severity, medium risk. Put `max_wrong` in the blob, including 0, and make the local miss counter use it. Public text says three, which matches today's hard-coded 3, so the public path should be unchanged if the parser still reads "three". Add a test that three still closes on the third miss. Leave the server `wrong_answers_left` path under its existing tests.
4. SYN-08a, medium severity, lower risk. A second `from HH:MM to HH:MM` in one file should be a deploy diagnostic. Do not change later-file precedence: a later brief may replace the window on purpose.
5. SYN-06, high severity, higher regression risk. A numeric cap changes negotiation for every extra account row. Public Brief B is "one to three products" and the runtime currently keeps whatever `get_account` returns. Thread `max_products` only with tests that one product still negotiates the single row and three products still all appear. Do not infer the cap from the unused `multi` flag alone.
6. SYN-04, medium severity, higher risk. Applying a withdrawal can delete a good inherited table. Keep the current blocker until there is a precise replacement syntax with tests. Safe reject is already the deploy behavior.
7. SYN-02, format gap, highest parser risk. A general key-value reader would touch holidays, bands, outcomes, floors, and identity at once. Prefer the safe reject until a hidden brief shows a real labeled shape. A later narrow reader should still refuse a file that leaves bands or outcomes unresolved.

## What stayed untouched

Production modules, `runtime_body.py`, `out/brief-a.workflow.json`, `out/brief-b.workflow.json`, tags `agentforge-public-13of13` and `agentforge-rc1`, and `master` were not modified. Untracked `baseline/` and `_phase_a_scratch/` were left untracked. Published agents were not redeployed:

- Brief A agent `226ac592-7f49-4709-af09-5db309bb544d`, workflow `caa5c9e9-a7e7-4cf4-9770-e6634ccf3cdc`
- Brief B agent `d930ead4-bf47-467c-8ea0-d99aa344c549`, workflow `160ea9d1-d5f0-4d86-8c80-4157f1eb2700`
