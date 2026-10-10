# AgentForge RC1

Date: 2026-10-10. Local validation only. Freya was not called. No official simulation was run.

Scope: Brief A and Brief B. A brief that needs an outcome name outside the six exact roles below is not covered by this candidate.

## Test results

`python -m unittest agentforge.tests.test_agentforge -v`

**55/55 passed.**

Included probes:

- `days_late` 0, 46, 60, and 99 on Brief A bands 1–7 and 8–45 close `no_promise` / `service_error`. No `create_promise` route after a yes.
- Band edges 1, 7, 8, and 45 still offer and reach `create_promise` only after a clear yes. A false `ok` does not mark the promise recorded.
- A brief band `0|3` accepts day 0 and rejects day 4. A brief band `10|20` accepts 10 and 20 and rejects 9 and 21.
- `side_promise`, prefixes, and suffixes do not replace `promise`. `escalated` stays unsupported. The six Brief A/B roles stay exact.
- Missing, null, malformed, and negative balances do not become a payment amount.

Brief A compile: `traces/agentforge-20261010-171027-brief-a.txt`, validation ok.
Brief B compile: `traces/agentforge-20261010-171027-brief-b.txt`, validation ok.

## Root causes and files

P0-1. `band_for` in `agentforge/runtime_body.py` invented an `unknown` band with deadline today and one attempt. `enrich` now leaves an unmatched `days_late` unusable. No due date, floor, or attempt count is invented. Closure is the existing `no_promise` / `service_error` path. Day 0 is offered only when a parsed band contains 0.

P0-2. `_roles` in `agentforge/parser.py` matched `promise`, `transfer`, `verif`, and `reach` by prefix or substring, so `side_promise` could replace `promise`. Roles are now the exact normalized names `promise`, `paid`, `transferred`, `no_promise`, `not_verified`, and `not_reached`. The first exact name wins. Other names are listed as `unsupported_outcomes` and are not copied into the runtime policy blob.

`agentforge/cli.py` adds `unsupported outcomes are not implemented` to validation and writes that list on the checklist. `close_call` still enumerates only the resolved roles.

Changed for these two fixes:

- `agentforge/runtime_body.py`
- `agentforge/parser.py`
- `agentforge/cli.py`
- `agentforge/tests/test_agentforge.py`
- `out/brief-a.workflow.json`, `out/brief-b.workflow.json`
- `out/brief-a.checklist.json`, `out/brief-b.checklist.json`

This tree also contains the earlier local fixes that the last official scores do not cover: confirm-stage intents, spoken amounts, hardship with a proposal, stop-the-call, missing balances, failed `add_note`, and outcome-table boundaries.

## Workflow hashes

SHA-256 after the 17:10 compile:

- Brief A `out/brief-a.workflow.json`: `e8be09f651d9e075f05ea27bf663abd54e33f9343aec03623d9aae7611af66f7`
- Brief B `out/brief-b.workflow.json`: `880dec37789e72f9b4f70d3d6a6f93bdd162851d49caeaef37252b0831ef268d`

Previous local workflows, before this band and role fix:

- Brief A: `84f25fab45c63fd455d56dbf147f3b30629031b26231ac97f79501eb1b44b63e`
- Brief B: `96651b2106e3cf13b4ac038343aa0cd1f61652e2c9e542cff9380ebd765b0fd3`

Node names, transitions, tool URLs, `{{disclosure}}`, `{{greet_line}}`, `{{farewell}}`, and `close_call` at `end_of_call` are unchanged. The hash changed because `runtime_body.py` is embedded in every code node. Close enum remains `promise`, `paid`, `transferred`, `no_promise`, `not_verified`, `not_reached`. Both checklists report `unsupported_outcomes: []`.

## Known unsupported features

- An outcome name that is not one of the six exact roles is kept in the parsed table, reported as unsupported, omitted from `close_call`, and fails validation. The CLI still writes the workflow file. A brief that requires that outcome is a release blocker. This is not a new outcome engine.
- Variables are not a separate catalogue.
- An outcome header cell must contain the word `outcome`. A row with no backticks ends that table.
- A later brief with any outcome table replaces the whole map.
- `max_products` is parsed and then dropped from the runtime blob.
- A verified caller is not sent to `schedule_callback`.

## Remaining risks

- No official simulation has scored this runtime. The recorded Brief A 9/10 and Brief B 3/3 (`9587edc7-ffbb-47d0-8d22-35987ae642ac`) predate these fixes.
- A matched band whose own day count is 0 still uses today. That value comes from the brief row, not from an unmatched day.
- `add_note` and `create_promise` have no idempotency key. A timeout is not retried. An explicit `ok: false` is retried once.
- Turn time is dominated by platform model calls. This candidate does not change that.

## Git

`master` has no commits. `git rev-parse HEAD` fails. The working tree is untracked, including the starter kit and AgentForge. `env.sh` is gitignored and was not read. No release commit was created.

## Rollback

There is no commit to check out. Do not deploy these workflows if this candidate is rejected. The previous local workflow hashes are listed above; those files were overwritten by the 17:10 compile. Restoring them requires a copy taken before that compile. Do not use `git reset` or `git checkout` until a commit exists.

## Official commands

Not run. From `build-the-builder`, only after an explicit decision to score this candidate:

```powershell
$env:LOCALAPPDATA\Programs\Python\Python312\python.exe -m agentforge briefs/brief-a.md --deploy --test --brief A
$env:LOCALAPPDATA\Programs\Python\Python312\python.exe -m agentforge briefs/brief-a.md briefs/brief-b.md --deploy --test --brief B
```

## Recommendation

Brief A and Brief B are locally ready for one controlled official benchmark. Do not treat a brief with any other outcome name as ready. Do not describe the older 9/10 or 3/3 as scores for this runtime.
