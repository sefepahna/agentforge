# AgentForge final candidate

Date: 2026-10-10. Verified product commit `9ed4b0c2d6e1d7b91649fd1cf6d3a1483d6b3017`. Case-by-case results are in [docs/AGENTFORGE_VERIFICATION.md](docs/AGENTFORGE_VERIFICATION.md).

AgentForge compiles a bank brief into a Freya collections phone agent. Policy code decides the route, the amount, and the date. The model speaks only the line that code already chose. The compiler makes no model call. A local validation run does not call Freya. `--deploy` updates the existing brief slot and publishes it.

## Brief inheritance

Briefs are merged in the order given. A later file overrides the tables and flags it states.

- Holiday dates accumulate.
- Bands, outcome tables, and amount floors replace the earlier table when the later brief includes one.
- Notes, multi-product mode, identity fields, queues, and spoken lines override when the later brief sets them.
- Rules accumulate.
- Brief B is Brief A plus those overrides. Pass both files, in that order. The output slot is the last brief.

An outcome name must be one of `promise`, `paid`, `transferred`, `no_promise`, `not_verified`, or `not_reached`. Any other name is reported and fails validation.

## Verified results

All 13 public cases passed in the recorded runs: Brief A 10/10 and Brief B 3/3. Each set was run once. These runs do not show that the same agent would pass every later day, every speaking style, or three repeats.

| Brief | Published version | Public result | Workflow | Agent |
|---|---|---|---|---|
| A | 6 | 10/10 | `caa5c9e9-a7e7-4cf4-9770-e6634ccf3cdc` | `226ac592-7f49-4709-af09-5db309bb544d` |
| B | 4 | 3/3 | `160ea9d1-d5f0-4d86-8c80-4157f1eb2700` | `d930ead4-bf47-467c-8ea0-d99aa344c549` |

Every run in those simulations reported `agentVersionNumber` equal to the published version above.

Source fix: `326833ebd2e1f8f93e8572256c422f0bd8aca281` (`fix: scope mixed payment and refusal statements to selected products`).

Generated workflows: `9ed4b0c2d6e1d7b91649fd1cf6d3a1483d6b3017` (`build: refresh verified Brief A and B workflows`).

SHA-256 of the version 6 and version 4 compiler output:

- `out/brief-a.workflow.json`: `09dc5274f09b5c18912c500400e58b0474872ac2757599f519217395007acfbc`
- `out/brief-b.workflow.json`: `64aaf389b10b8544a8d3ca8c46b4d262f518943482342c5d0d975aeeb811c0fd`

The same hashes were recorded before that deploy. After publish, each code body matched the local body at the same node path. Platform defaults and `agent_config` were the only additions. `agentforge-rc1` remains `36e975eb53f7227817a967025a54bab85cda3cd1`.

## Later republish

`58d131df5755e2ef372ae0f316df8e478ecfe88c` keeps the recording disclosure but does not say "recorded" in the opening. The same slots were published again. This is not the version 6 or version 4 evidence.

| Brief | Public result | Simulation |
|---|---|---|
| A | 10/10 | `083995c0-abf2-49c9-879c-81956baebf9f` |
| B | 3/3 | `578efdd9-cd3b-481a-b1ca-48eca4761cb9` |

Current compiler SHA-256:

- `out/brief-a.workflow.json`: `6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da`
- `out/brief-b.workflow.json`: `56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf`

The new published version numbers were not in the trace. The local suite was 72/72. Development is frozen on this commit until the next briefs arrive.

## Evidence

The tracked summary is [docs/AGENTFORGE_VERIFICATION.md](docs/AGENTFORGE_VERIFICATION.md). It holds the version scores, workflow hashes, per-case results, and the PUB-10 and PUB-12 observations. Local `results/` and `traces/` files can supplement that summary. They are gitignored and are not required to read the claims above.

Demonstrated behavior in those runs:

- Brief B PUB-12 recorded one credit-card promise for the day after the case clock and one refused note on each of the other two products. The call did not loop a three-product confirmation.
- Brief A PUB-10 sent two promise requests. The first returned an explicit failure and recorded nothing. The retry wrote one promise. The promise-confirmation sentence came after that successful write. The opening sentence is the call-recording disclosure, not a promise confirmation.

## Three-minute demo

Use the artifacts above. Do not rebuild or redeploy.

1. Show product commit `9ed4b0c` and the two SHA-256 values in [docs/AGENTFORGE_VERIFICATION.md](docs/AGENTFORGE_VERIFICATION.md).
2. Read the per-case tables there. State 10/10 on version 6 and 3/3 on version 4.
3. If the local deploy traces are present, point at validation ok and `model none`. They are optional.
4. For PUB-12, state the ledger shape: one promise on the card, two refused notes, no confirmation loop.
5. For PUB-10, state two promise requests, an explicit failed write, one ledger promise, and the confirmation sentence after the successful write.
6. Close on the limit: one recorded pass of the 13 public cases is the measured result.

## Still missing or unverified

- The kit asks for one trace per brief that includes the practice test, plus the platform export of each phone agent. Those files exist only as gitignored local artifacts. The tracked verification summary records the scores. It is not a substitute for the export the organizers load.
- Final unseen briefs, speaking-style repeats, and the three-run rule were not run.
- An outcome outside the six exact names is unsupported.
- `max_products` is parsed and then omitted from the runtime blob.
- A later outcome table replaces the whole map.

## Limits

Turn time still depends on the platform model calls. `create_promise` and `add_note` have no idempotency key. An explicit `ok: false` is retried once. This candidate does not show what happens when a response is ambiguous, and it does not close the historical date investigation.
