# AgentForge hidden-brief runbook

Baseline to preserve: `bfabb8a3d53383c6bfaa67bb1f41530a74ad48c4`. The public result is 13/13 on that candidate. It is not the hidden-brief submission.

Run from `build-the-builder`.

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
```

`FREYA_API_KEY` is required to deploy. `FREYA_BANK_TEAM_KEY` is required only for a practice run. Do not print either value. Do not change `AGENT_LLM` in `freya.py`.

A bug fix may change general builder behavior. It may not copy a hidden brief's dates, amounts, names, or outcome words into code or prompts. Do not edit a generated workflow by hand.

## Where the new files go

Keep `briefs/brief-a.md`, `briefs/brief-b.md`, and `tools/openapi.json` unchanged.

Place each released brief and its tool API under new names, for example:

- `briefs/hidden/one.md`
- `briefs/hidden/one.openapi.json`
- `briefs/hidden/two.md`
- `briefs/hidden/two.openapi.json`

The last brief's file stem is the Freya slot. `brief-a` and `brief-b` already belong to the verified agents. A file with either stem updates that published agent. Use a new stem, and reuse that same stem if you run again, so the slot is updated instead of creating another workflow.

## Build

Supported CLI flags are the brief paths, `--openapi`, `--out`, `--deploy`, `--test`, and `--brief`. There is no hidden-customer flag.

One brief, no Freya call:

```powershell
& $py -m agentforge briefs/hidden/one.md --openapi briefs/hidden/one.openapi.json
```

A later brief overrides tables and flags it states. Holiday dates accumulate. Bands, outcome tables, and floors replace the earlier table. Notes, multi-product mode, identity fields, queues, and spoken lines override when set. Rules accumulate. Pass the files in that order, with the API file for this run. The CLI accepts one `--openapi` per command.

```powershell
& $py -m agentforge briefs/hidden/one.md briefs/hidden/two.md --openapi briefs/hidden/two.openapi.json
```

This writes `out/<last-stem>.workflow.json`, `out/<last-stem>.checklist.json`, and `traces/agentforge-<time>-<stem>.txt`. Confirm `validation ok` and `model none`.

## Before deploy

`37da5b9` adds a locally tested check: unresolved payment bands, or no supported outcome mapping, block deployment. The 13/13 result stays on the earlier published agents, Brief A version 6 and Brief B version 4. It is not evidence for this check.

`validation ok` is incomplete. A default is not proof that an explicit requirement was read. Compare the brief with `out/<stem>.checklist.json` before `--deploy`.

- Numbered rules are copied, not executed. A rule that is not in the effective configuration is unsupported.
- Holidays and minimum amounts must appear in the checklist when the brief states them. A missing list is not a parsed empty list.
- Identity fields and the wrong-answer limit must match the brief. Unstated values fall back to date of birth, phone last four, and three tries.
- Calling hours and the bank name must match. Unstated values fall back to 10:00–19:00 and `the bank`.
- Outcome mappings, inherited bands, and later overrides must be the ones the brief states. An empty reason list on a resolved outcome is valid. A later brief replaces an outcome map only when it states one.
- The `--openapi` file must allow the tools and enum values the brief uses. One command takes one API file.

If a requirement is unsupported or only partly parsed, stop and name it. Do not deploy that gap, and do not hardcode the hidden brief into the builder.

## Deploy

Repeat the same command with `--deploy` and without `--test`. Check that the second file hash matches the first. The trace must contain `freya workflow_id` and `freya agent_id` for the new stem. Those ids must not be the verified public agents.

The CLI does not print `versionNumber`. `save_workflow` publishes. A plain update that is not published leaves calls on the old version.

## Practice test

`--test` runs `tools/run_cases.py` on `public-test-set.json`. `--brief A` or `--brief B` selects those public cases. The letter comes from `--brief` or from a final path ending in `a`, `-a`, `b`, or `-b`. This is not access to the hidden customers. The organizers score those customers. A public failure can be a real regression or a rule that exists only in the new brief. Do not treat a public score as the hidden result.

`--test` runs only in the same command as a successful `--deploy`. It does not accept `--cases`, `--only`, `--out`, `--style`, or `--reps`. The trace records the command and `test_exit`, not the per-case lines.

`run_cases.py` itself supports `--cases`, `--only`, `--out`, `--reps`, `--style`, and `--rerun-if-slow` against the public file. `--style` choices are `asks_back`, `corrects`, `in_words`, `pieces`, and `talkative`. None of these loads a hidden suite.

## Traces and exports

Keep the trace the CLI writes for that run. It is the authentic compile record: start, end, `model none`, brief paths, validation, Freya ids, and the practice command if `--test` ran. `traces/` is gitignored. Copy the chosen trace out of that directory for submission. One trace per final brief.

After deploy, export what the platform stored. The CLI does not do this.

```powershell
& $py -c "import freya; print(freya.export_workflow('WORKFLOW_ID', 'one.workflow.json'))"
```

Use the workflow id from the trace. The organizers load this export. The compiler file in `out/` is not that file: the platform adds `agent_config` and default node fields. Compare code bodies at the same node path before submitting. Do not require different nodes' bodies to match each other.

## Troubleshooting

1. Parser. Open the checklist, not the call log. Empty bands, holidays, or outcomes mean the text did not match the tables the parser reads. `unsupported_outcomes` means a name outside `promise`, `paid`, `transferred`, `no_promise`, `not_verified`, and `not_reached`. An outcome header must contain the word `outcome`. A row without backticks ends that table. Any outcome table in a later brief replaces the whole map. `max_products` is parsed and then omitted from the runtime blob.
2. Validation. The trace says `validation failed`, lists `error` lines, and says `deploy skipped`. The workflow file is still written. Do not deploy it. Nulls, `agent_config`, a missing initial node, or a transition to an unknown node are structural failures.
3. Deployment. `deploy blocked: FREYA_API_KEY is not set` happens before any save. An HTTP error means the save did not finish. A missing `freya workflow_id` means there is no agent to test. If a later practice score does not move, the published version was not the one just saved.
4. Runtime. This applies only after a real `run_cases.py` run. Ledger mismatches are policy results. `customer-ended-call` with a slow median is a platform delay. Speech that says a promise is recorded before the tool succeeds is a runtime honesty failure. A public-case miss after a hidden brief is not evidence about the hidden customers.

A raw mail, memo, or code list is a supported kind of final brief in the kit rules. This parser still reads markdown tables and dated holiday lines. If that form does not fill the checklist, the fix has to be general parsing, not values copied from the brief.

## Submission checks

For each final brief, the bundle needs:

- the builder code, without hidden-brief answers added to it
- the one trace for the run you submit
- the platform export from `export_workflow`

Also confirm:

- the trace stem is not `brief-a` or `brief-b`
- validation in that trace is ok
- the trace says `model none`
- the export's workflow id matches the trace
- the agent was not edited after `save_workflow`
- the run, including any practice test, stayed within 30 minutes
- `out/brief-a.workflow.json` and `out/brief-b.workflow.json` are still the baseline files

Do not send `env.sh`, `.freya-agents.json`, or `.personas.json`.
