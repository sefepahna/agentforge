# Final hidden-brief readiness

Date: 2026-10-11. Offline freeze. No deploy and no simulation.

## Candidate

Branch `feature/hidden-brief-readiness`.

Production candidate, before this note:

`f6e5d4f0c97773e2868013e2560b2b3e9c5e4914`

`agentforge-hidden-ready` points at the documentation commit that adds this file. That commit does not change parser, prose, runtime, or workflows.

## Protected baseline

Tag `agentforge-public-13of13` → `1cced0155309b04e6da918e9165d2cadcc64d8a5`.

Older tag `agentforge-rc1` → `36e975eb53f7227817a967025a54bab85cda3cd1`.

Neither tag was moved. `master` was not updated.

## Public benchmark history

One verified public run, recorded on the protected baseline:

- Brief A: 10/10
- Brief B: 3/3
- Total: 13/13

That run is not a proof that a future hidden brief, or a repeat of the same public set, will score the same.

Published agents were not touched:

- Brief A agent `226ac592-7f49-4709-af09-5db309bb544d`
- Brief B agent `d930ead4-bf47-467c-8ea0-d99aa344c549`

## Offline suite

Command:

`python -m unittest discover -s agentforge/tests -q`

Result: 154 discovered tests, all passed. Discovery counts subtests inside a method. Unique test methods, counted from `def test_` in `agentforge/tests/test_*.py`: 134, all distinct names. 134/134 passed. No test was weakened.

Synthetic matrix from `agentforge.tests.synthetic_eval`:

| Case | Result |
| --- | --- |
| SYN-01 | PASS |
| SYN-02 | SAFE_REJECT |
| SYN-03 | SAFE_REJECT |
| SYN-04 | SAFE_REJECT |
| SYN-05 | SAFE_REJECT |
| SYN-06 | FAIL |
| SYN-07 | SAFE_REJECT |
| SYN-08a | SAFE_REJECT |
| SYN-08b | SAFE_REJECT |

SYN-06 stays FAIL. A brief that says four products still keeps five returned rows. That is an accepted limitation of this freeze.

## Public compatibility

Compiled in memory from `briefs/brief-a.md` and `briefs/brief-a.md` plus `briefs/brief-b.md`. Nothing was written under `out/`.

- Brief A: 22 nodes, initial `boot`, validation empty
- Brief B: 24 nodes, initial `boot`, validation empty
- Disclosure: `We are recording this call.`
- In-memory workflow objects equal the JSON parsed from the protected files

On-disk hashes, not rewritten:

- Brief A `6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da`
- Brief B `56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf`

## Improvements since the public baseline

Fail-closed only. Runtime behavior was not retargeted.

- SYN-07 unsupported identity fields → SAFE_REJECT (`b557b39`, `parser.py`)
- SYN-03 unbound natural-language floor → SAFE_REJECT (`7e1626e`, `prose_extract.py`)
- SYN-08a multiple calling-hour ranges in one file → SAFE_REJECT (`132c0c2`, `parser.py`)
- SYN-05 explicit wrong-answer limit other than 3 → SAFE_REJECT (`f6e5d4f`, `parser.py`)

Already safe before those gates, and still safe:

- SYN-02 labeled key-value form
- SYN-04 withdrawal detected but not applied
- SYN-08b conflicting outcome prose

`runtime_body.py`, `workflow_builder.py`, `freya.py`, and `agentforge/cli.py` are unchanged since `agentforge-public-13of13`. Workflow topology, promise retry, notes, payment math, negotiation, identity runtime, product execution, recording disclosure, and the Freya model setting were not edited.

## Known limitations

- SYN-06: `max_products` can be parsed, including Brief B's three, and is not a general cap. A gate that rejects every value other than 1 would block public Brief B. Not added.
- Configurable `max_wrong` is not implemented. The local miss counter remains 3. Any other explicit value is rejected.
- Policy withdrawal is detected and blocks deploy. It does not rewrite inherited tables.
- Generic key-value policy text is not parsed. Deploy is blocked when required tables are missing.
- Identity fields other than `date_of_birth` and `phone_last4` are rejected.
- More than one distinct calling-hour range in one file is rejected. A later file may still replace the single window.
- Natural-language floors that are not in the supported form are rejected, not bound.
- `create_promise` has no idempotency key. The single retry remains the Phase 2 behavior.
- Persuasion attempts come from the band row and are counted per product. There is no separate global conversation turn budget.

## Hidden brief response

When a hidden brief arrives:

1. Save it under a new stem.
2. Do not overwrite public Brief A or Brief B.
3. Compile it offline first.
4. Read the diagnostics.
5. If it is supported, inspect the generated workflow.
6. Only then decide whether a deploy is appropriate.
7. Change only what that brief's evidence requires.
8. Rerun the full offline suite before any deploy.

Do not redeploy the published public agents.
