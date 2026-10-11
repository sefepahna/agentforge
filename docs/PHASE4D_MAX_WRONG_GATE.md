# Phase 4D — Reject unsupported wrong-answer limits

Date: 2026-10-11. Branch `feature/hidden-brief-readiness`.

Phase 3 left SYN-05 as FAIL. This note does not rewrite that result.

## Before

`N wrong answers` was stored on the policy object and omitted from the runtime blob. `after_id_utterance` closes a local identity miss when `id_miss >= 3`, for both date of birth and phone. SYN-05 asked for two and still closed on the third miss. Deploy stayed open.

`wrong_answers_left` is the `verify_identity` response field. `after_id_api` closes when that API value is `0`. It is not the brief limit.

A missing phrase parsed as `0`. `_merge` used `if extra.get("max_wrong")`, so an explicit `0` was dropped and the default `3` remained.

## After

No match is `None` and does not override the default `3`. An explicit integer, including `0`, is kept. `unresolved_configuration` blocks deploy when the merged value is not `3`:

`unsupported wrong-answer limit is not implemented: 2`

The same text is used for `0` and `4`. A later file can replace the number. A later `3` clears the block. `six wrong answers` still does not match the parser, so it stays the default. The value is still absent from the blob. Local misses still close at 3.

SYN-05 is SAFE_REJECT. SYN-03, SYN-07, and SYN-08a stay SAFE_REJECT. Public Brief A and Brief B still validate empty, and their workflow JSON matches the files on disk.

Protected hashes were not rewritten:

- Brief A `6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da`
- Brief B `56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf`

No deploy and no simulation.
