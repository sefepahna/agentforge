# AgentForge

Builds a Freya collections workflow from a brief. Python 3.10+. No extra packages.

The starter kit (`freya.py`, `tools/`, `briefs/`, `examples/`, `docs/`) is unchanged.

## Run

From `build-the-builder`:

```bash
python -m agentforge briefs/brief-a.md
python -m agentforge briefs/brief-a.md briefs/brief-b.md
```

Writes:

- `out/<last-brief>.workflow.json`
- `out/<last-brief>.checklist.json`
- `traces/agentforge-<time>.txt`

Local validation does not call Freya.

## Environment

Copy `env.example` to `env.sh` or set the variables in the shell. Do not commit them.

| Variable | Role |
|---|---|
| `FREYA_API_KEY` | Workspace key (`fak_...`). Required only to save a workflow. |
| `FREYA_API_URL` | Defaults to `https://staging-app.freyavoice.ai`. |
| `FREYA_BANK_TEAM_KEY` | Any secret of 16+ characters, same value every run. Required for practice scoring. |
| `FREYA_WORKSPACE_ID` | Optional. `freya.py` uses the first workspace otherwise. |

Do not change `AGENT_LLM` in `freya.py`.

## Deploy and practice test

```bash
python -m agentforge briefs/brief-a.md --deploy --test --brief A
python -m agentforge briefs/brief-a.md briefs/brief-b.md --deploy --test --brief B
```

`--deploy` calls `freya.save_workflow`, which updates the same slot and publishes it. `--test` runs `tools/run_cases.py`. A 10-customer run takes about 3 to 11 minutes. One simulation at a time.

Export the agent you will submit:

```bash
python -c "import freya; print(freya.export_workflow('WORKFLOW_ID', 'brief-a.workflow.json'))"
```

Submit the exported workflow, this code, and the trace file. The trace lists start and end time, that the compiler made no model call, the Freya ids, and the practice command if one ran.

## Tests

```bash
python -m unittest agentforge.tests.test_agentforge -v
```

These tests execute the policy engine and check workflow JSON. They do not produce a benchmark score.

## Layout

| Path | Role |
|---|---|
| `agentforge/parser.py` | Brief text to a policy and a checklist |
| `agentforge/runtime_body.py` | Dates, amounts, identity, third parties, promises |
| `agentforge/workflow_builder.py` | Freya workflow JSON |
| `agentforge/validate.py` | Structure check before save |
| `agentforge/cli.py` | `python -m agentforge` |
| `AGENTFORGE_AUDIT.md` | Architecture and risks |
