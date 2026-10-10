# AgentForge verification

Documentation only. It does not change the phone agents. The verified product commit is `9ed4b0c2d6e1d7b91649fd1cf6d3a1483d6b3017`. The source fix is `326833ebd2e1f8f93e8572256c422f0bd8aca281`.

Each public set was run once on the published agent built from that product. All 13 public cases passed. One pass is not a claim of universal reliability.

## Scores

| Brief | Published version | Result |
|---|---|---|
| A | 6 | 10/10 |
| B | 4 | 3/3 |

SHA-256 of the compiler workflows in the product commit:

- Brief A `out/brief-a.workflow.json`: `09dc5274f09b5c18912c500400e58b0474872ac2757599f519217395007acfbc`
- Brief B `out/brief-b.workflow.json`: `64aaf389b10b8544a8d3ca8c46b4d262f518943482342c5d0d975aeeb811c0fd`

Those hashes matched the files deployed for the version 6 and version 4 runs below. Every run in each of those simulations reported `agentVersionNumber` equal to that brief's published version.

## Later republish

Commit `58d131df5755e2ef372ae0f316df8e478ecfe88c` changes the opening disclosure to "We are recording this call." The same workflow slots were published again on 2026-10-10. These runs are separate from version 6 and version 4. The trace did not record the new `agentVersionNumber`.

| Brief | Result | Simulation |
|---|---|---|
| A | 10/10 | `083995c0-abf2-49c9-879c-81956baebf9f` |
| B | 3/3 | `578efdd9-cd3b-481a-b1ca-48eca4761cb9` |

SHA-256 of the compiler workflows in that commit:

- Brief A `out/brief-a.workflow.json`: `6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da`
- Brief B `out/brief-b.workflow.json`: `56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf`

The local suite at that commit was 72/72. PUB-10 still shows one failed promise write, one successful retry, and the confirmation sentence after the successful write. The opening no longer uses the word "recorded".

## Brief A cases

| Case | Result |
|---|---|
| PUB-01 | pass |
| PUB-02 | pass |
| PUB-03 | pass |
| PUB-04 | pass |
| PUB-05 | pass |
| PUB-06 | pass |
| PUB-07 | pass |
| PUB-08 | pass |
| PUB-09 | pass |
| PUB-10 | pass |

## Brief B cases

| Case | Result |
|---|---|
| PUB-11 | pass |
| PUB-12 | pass |
| PUB-13 | pass |

## PUB-10

The promise tool was called twice for the same agreed card amount and date. The first response was an explicit failure and recorded nothing. The retry wrote one promise, and the ledger held that single promise. The sentence confirming the promise came after the successful write. The opening sentence only discloses that the call is recorded.

This run does not show an ambiguous tool response or server-side deduplication.

## PUB-12

The customer promised the credit card and refused the other two products. The ledger held one card promise for the day after the case clock, plus one refused note for each refused product. The call did not repeat a three-product confirmation.

This run does not close the historical date investigation. Offer fields can still show a different date from the recorded promise.

## Limitations

Speaking-style repeats and the organizer's three-run rule were not part of these recordings. Outcome names outside the six exact roles stay unsupported. Promise and note writes have no idempotency key.
