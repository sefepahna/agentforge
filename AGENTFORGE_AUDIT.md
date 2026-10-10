# AgentForge audit

Kit version 3. This audit was written from the files in this starter, not from assumed paths.

## What the platform actually does

A workflow is a graph. After each customer message Freya runs extraction, then routing, then dialogue as three separate model calls. Routing sees only transition conditions. Dialogue sees only the current node's prompt and tools. Deterministic `equals` / `greater_than` checks do not call a model. `equals` compares strings, so booleans from tools must be tested as text or replaced with tokens such as `verified`.

Code nodes and `api_request` nodes should be passthrough and must end with an `always` transition. Code reads and writes `vars`, must not raise, and must not contain `{{` or `}}`. API body fields bake a `default` when the node is entered. `close_call` belongs on the workflow `tools` list with `alwaysRunsAt: ["end_of_call"]`. The scorer reads the bank ledger, not the transcript alone: the last tool must be `close_call`, and `get_account` / `create_promise` before verification fail the case.

`agent_config` must be omitted. The phone-agent model stays the one in `freya.py`.

## The seven tools

From `tools/openapi.json`. The host is `https://freya-bank-mock.freyavoice.workers.dev/v1`. The service records what it is given; it does not enforce the brief.

| Tool | Required body | Notes |
|---|---|---|
| `verify_identity` | `customer_id`, `field`, `answer` | `field` is `date_of_birth` or `phone_last4`. Dates must be `YYYY-MM-DD`. `hint: day_month_swapped` is not a wrong answer. |
| `get_account` | `customer_id` | Refused until both checks pass. Products are `p1`, `p2`, ... |
| `create_promise` | `customer_id`, `product_id`, `amount`, `date` | One promise per product. `ok: true` is the only proof it was stored. |
| `add_note` | `customer_id`, `product_id`, `reason` | Brief B. Reasons: `refused`, `hardship`, `dispute`, `paid`, `service_error`. |
| `schedule_callback` | `customer_id`, `date`, `time` | `time` is `HH:MM`. |
| `transfer_to_agent` | `customer_id`, `queue` | `restructuring`, `general`, `support`. |
| `close_call` | `customer_id`, `outcome` | `reason` omitted for `promise` and `paid`. Must be the last call. |

## Brief A and Brief B

Brief A is one product, 47 numbered rules: recorded opening, no debt talk before verification, two security questions, three wrong answers, business-day deadlines (early 12 / late 7), floors, one or two persuasion attempts, hardship before persuasion, read-back before `create_promise`, and one `close_call`. Holidays and the outcome table are in the brief. Brief A never calls `add_note`.

Brief B keeps Brief A and adds up to three products, per-product deadlines, one shared read-back, `add_note` for products without a promise, and `promise` whenever any promise was stored unless a transfer happens. Transfers write no notes.

Practice customers in `public-test-set.json` cover identity, third parties, dates, amounts, hardship, refusal, tool failure, and multi-product closes. Final briefs can change numbers, question fields, and outcome names. The seven tool names stay; fields may change.

## Where each kind of rule should live

| Kind | Examples | Place |
|---|---|---|
| Code | Holidays, business days, deadlines, floors, attempt counts, callback window, DOB `YYYY-MM-DD`, promise retry | `runtime_body.py`, copied into code nodes with the parsed policy JSON |
| Transitions | Verified vs failed identity, third party vs customer, route to record / note / transfer / close | `route` string compared with `equals` |
| Model speech | Say the line the code wrote, including sympathy and the text-message sentence | TTS `on_enter` of `{{coach}}` / `{{greet_line}}` / `{{id_line}}` |
| Ledger | `create_promise`, `add_note`, `transfer_to_agent`, `schedule_callback`, `close_call` | Passthrough API nodes with baked ids, amounts, dates, and queues |

The dialogue model does not choose product ids, amounts, or dates. It only speaks the coach line. Extraction copies the customer's latest words into `user_said`.

## Example builder weaknesses

`examples/agent_builder.py` asks Claude, with one short skill, to rediscover the workflow format and the brief on every run. That spends the 30 minute budget on reading docs, can bake this brief's numbers into a prompt, and stops after three practice loops. `examples/base-agent.json` verifies identity and takes one promise. It passes only the easiest customers: no third-party branch, no deadline code, no hardship or transfer outcomes, no `add_note`, and it ends by hoping the model says "Have a good day." `null` fields in that file are invalid if sent as new workflow JSON. Tool results are raw, so a failed `create_promise` is easy to describe as recorded.

## AgentForge shape

```
briefs -> parser.py -> flat policy JSON
       -> workflow_builder.py -> out/<brief>.workflow.json
       -> validate.py
       -> freya.save_workflow   (only with --deploy)
       -> tools/run_cases.py    (only with --deploy --test)
```

`runtime_body.py` is the single policy engine. Tests call it directly. The same source is embedded in every code node so Freya does not need this package at call time. Holiday dates, band widths, floors, queues, and outcome tokens are read from the brief and from `tools/openapi.json`. They are not constants in the builder.

Security-sensitive branches are transitions: greeting code cannot target `api_account` or `api_verify`; those nodes are reached only after `after_greet` sets `route` to `verify` and `after_id_api` sets `route` to `account`. Promise speech is the lifecycle farewell `{{promise_line}}`, and that variable is set only after `create_promise` returns ok.

## Risks

- Extraction can miss `user_said`. The code then repeats the coach line.
- A customer who corrects a date in one sentence is handled by taking the last date found. Split dates across turns are only partly covered.
- Final briefs whose outcome words do not match `promise`, `paid`, `transfer`, `verif`, or `reach` need a parser fix, not new literals in the workflow.
- Live practice scores are not known until `FREYA_API_KEY` and `FREYA_BANK_TEAM_KEY` are set. This audit does not claim a score.
- Code is duplicated into each code node so the sandbox can run it. Workflow JSON is large on purpose.

## Implementation plan that was followed

1. Parse briefs into a checklist and a flat policy.
2. Generate the state graph and embed the policy.
3. Validate structure locally.
4. Unit-test identity, third parties, deadlines, floors, refusal, hardship, multi-product notes, API paths, and closing.
5. Deploy and run `tools/run_cases.py` only when credentials exist. Do not edit generated agents by hand.
