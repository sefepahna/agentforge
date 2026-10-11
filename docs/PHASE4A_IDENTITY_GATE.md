# Phase 4A — Reject unsupported identity fields

Date: 2026-10-11. Branch `feature/hidden-brief-readiness`.

Phase 3 left SYN-07 as FAIL. This note does not rewrite that result. It records the fail-closed change after it.

## Before

A brief that asked for `postcode` was parsed, then the OpenAPI enum dropped the name because `verify_identity.field` only allows `date_of_birth` and `phone_last4`. An empty identity list was replaced with those two fields. `field_prompt` then asked for a date of birth. Validation was empty, so the workflow was deployable. That was a silent substitution.

Runtime support, read from the current code and not extended here:

- `field_prompt` has a phone sentence only for `phone_last4`. Every other name, including `postcode`, gets the date-of-birth sentence.
- `after_id_utterance` parses `date_of_birth`. Every other name is read as four phone digits.

## After

`unresolved_configuration` now blocks deploy when a requested identity name is outside that pair. The error is `unsupported identity fields are not implemented: postcode`. A mix of date of birth and postcode is still rejected. Public Brief A and Brief B name only the two supported fields, so their validation stays empty and their workflow JSON matches the files on disk.

SYN-07 classification: FAIL (Phase 3) → SAFE_REJECT (Phase 4A). The runtime still has no postcode prompt or parser. Rejection is not an implementation of postcode.

Protected workflow hashes were not rewritten:

- Brief A `6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da`
- Brief B `56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf`

No deploy and no simulation.
