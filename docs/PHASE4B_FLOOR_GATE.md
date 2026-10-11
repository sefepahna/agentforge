# Phase 4B — Reject unbound natural-language floors

Date: 2026-10-11. Branch `feature/hidden-brief-readiness`.

Phase 3 left SYN-03 as FAIL. This note does not rewrite that result.

## Before

SYN-03 says a credit-card settlement must stay at or above the minimum payment, and the same for a personal-loan instalment. That sentence does not match `the floor is` and it does not match `` `field` for a product ``. No diagnostic was emitted. `prepare_account` then used the past-due balance as the floor (200 and 80 in the Phase 3 run). Deploy stayed open.

## After

`_unbound_floor` still uses the old `the floor is` / leading `FLOOR` check. It also rejects a policy line where a lower-bound phrase (`at or above`, `no less than`, `not below`, `cannot be less than`, and the same with "lower") sits within 48 characters of `minimum payment` or `instalment amount`, and the backtick binder did not take the line. The diagnostic stays `explicit floor statement was not bound to configuration`, now with the line and product names.

SYN-03 is SAFE_REJECT: `line 24: credit card, personal loan`. The floor is still not parsed. A product-free "at or above the minimum payment" line is also rejected. Public Brief A and Brief B still validate empty, and their workflow JSON matches the files on disk.

Not rejected: `ground floor`, a bare `minimum`, `instalment plan`, a backtick floor, and the same lower-bound sentence under an `Example only` heading. A lower bound and an amount far apart on one line are not treated as one rule.

Protected hashes were not rewritten:

- Brief A `6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da`
- Brief B `56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf`

No deploy and no simulation.
