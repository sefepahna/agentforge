# Phase 4C — Reject ambiguous calling-hour ranges

Date: 2026-10-11. Branch `feature/hidden-brief-readiness`.

Phase 3 left SYN-08a as FAIL. This note does not rewrite that result.

## Before

`_parse_one` kept the first `from HH:MM to HH:MM` match. A later distinct range in the same file was dropped. Validation stayed empty, so the workflow was deployable. SYN-08a kept 09:15–16:45 and ignored 08:00–12:00.

The stored fields are still two strings, `callback_start` and `callback_end`. An empty parse leaves the merge defaults 10:00 and 19:00. A later file still replaces that one pair when it states its own range.

## After

Each file is scanned on its own. Policy lines are the lines `_classify_lines` marks `policy`. Example headings and fences opened under them are skipped. An exact repeat of the same captured pair is one range. Two or more distinct pairs append:

`multiple calling-hour ranges are not implemented: 09:15-16:45, 08:00-12:00`

That string is a `deploy_diagnostics` entry. The first pair is still what the blob stores. Deploy is blocked. `9:15` and `09:15` stay distinct. A fence that sits in the policy section is still policy, so a second range there is rejected.

Not rejected: one range, a missing range, an exact duplicate, a later file with its own single range, appointment or service prose that is not `from HH:MM to HH:MM`, and the same phrase under `Example only`.

SYN-08a is SAFE_REJECT. SYN-03 and SYN-07 stay SAFE_REJECT. Public Brief A and Brief B still validate empty. Their workflow JSON matches the files on disk.

Protected hashes were not rewritten:

- Brief A `6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da`
- Brief B `56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf`

No deploy and no simulation.
