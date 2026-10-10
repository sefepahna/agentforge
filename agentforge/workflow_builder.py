"""Compile a parsed brief into a Freya workflow. The model speaks lines the code already decided."""
import json
from pathlib import Path

RUNTIME = Path(__file__).with_name("runtime_body.py").read_text(encoding="utf-8")

STRIP_HEADER = (
    "try:\n"
    "    if isinstance(result, dict):\n"
    "        result.pop('header', None)\n"
    "except Exception:\n"
    "    pass\n"
)

AMOUNT_PRE = (
    "try:\n"
    "    body = config.get('body')\n"
    "    if isinstance(body, dict) and 'amount' in body:\n"
    "        body['amount'] = float(body['amount'])\n"
    "    if isinstance(body, dict) and 'date' in body:\n"
    "        body['date'] = str(body['date'])[:10]\n"
    "except Exception:\n"
    "    pass\n"
)


def _always(target):
    return {"target_node": target, "description": "always", "condition": {"operator": "always"}}


def _eq(value, target):
    return {
        "target_node": target,
        "description": value,
        "condition": {"logic": "or", "conditions": [{"variable": "route", "operator": "equals", "operand": value}]},
    }


def _routes(pairs, default):
    return [_eq(value, target) for value, target in pairs] + [_always(default)]


def _leaf(kind, default, description="", enum=None):
    leaf = {"type": kind, "default": default}
    if description:
        leaf["description"] = description
    if enum:
        leaf["enum"] = enum
    return leaf


def _api(name, url, body, required, pre="", post=""):
    tool = {
        "type": "function",
        "config": {"timeoutMs": 12000, "maxRetries": 0},
        "function": {
            "name": name,
            "handler": "__function__:api_call",
            "description": name,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "default": url},
                    "method": {"type": "string", "default": "POST"},
                    "connect_retries": {"type": "number", "default": 0},
                    "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                    "body": {"type": "object", "required": required, "properties": body},
                },
            },
        },
    }
    if pre:
        tool["pre_process_code"] = pre
    if post:
        tool["post_process_code"] = post
    return tool


def _code(name, call, policy_json, pairs, default):
    source = RUNTIME + "\nvars['policy_json'] = " + json.dumps(policy_json) + "\n" + call + "\n"
    if "{{" in source or "}}" in source:
        raise ValueError("code node " + name + " contains a template brace")
    routes = _routes(pairs, default)
    return {
        "name": name,
        "node_type": "code",
        "passthrough": True,
        "passthrough_default_transition": default,
        "on_enter": {"type": "silent"},
        "disable_inactivity_monitor": True,
        "pre_actions": [{
            "type": "function",
            "function": {
                "name": "code_exec",
                "handler": "__function__:code_exec",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "default": source},
                        "timeout_ms": {"type": "number", "default": 8000},
                    },
                },
            },
        }],
        "transitions": routes,
    }


def _talk(name, line_var, target, task):
    return {
        "name": name,
        "node_type": "conversation",
        "on_enter": {"type": "tts", "text": "{{" + line_var + "}}"},
        "on_enter_first_entry_only": False,
        "task_message": task,
        "extraction_schema": [{
            "name": "user_said",
            "type": "string",
            "description": "Copy the customer's latest message verbatim and replace any older value.",
            "min_confidence": 0.2,
            "max_retries": 1,
        }],
        "max_node_turns": 12,
        "max_turn_transition": "stall",
        "tools": [],
        "transitions": [_always(target)],
    }


def _api_node(name, tool, mapping, target):
    return {
        "name": name,
        "node_type": "api_request",
        "passthrough": True,
        "passthrough_default_transition": target,
        "on_enter": {"type": "silent"},
        "disable_inactivity_monitor": True,
        "pre_actions": [tool],
        "response_mapping": mapping,
        "transitions": [_always(target)],
    }


def _map(path, variable):
    return {"path": path, "variable": variable}


def build_workflow(policy, spec):
    """Return a workflow dict. `policy` is the merged brief from parse_briefs."""
    blob = policy["blob"]
    server = policy["server"].rstrip("/")
    enums = policy["enums"]
    field_enum = (enums.get("verify_identity") or {}).get("field") or blob.get("id_fields") or []
    queue_enum = (enums.get("transfer_to_agent") or {}).get("queue") or []
    note_enum = (enums.get("add_note") or {}).get("reason") or []
    outcome_names = [name for name in [
        blob.get("role_promise"), blob.get("role_paid"), blob.get("role_transferred"),
        blob.get("role_no_promise"), blob.get("role_not_verified"), blob.get("role_not_reached"),
    ] if name]
    no_reason = tuple(name for name in (blob.get("role_promise"), blob.get("role_paid")) if name)
    close_pre = (
        "try:\n"
        "    body = config.get('body')\n"
        "    drop = " + repr(no_reason) + "\n"
        "    if isinstance(body, dict):\n"
        "        reason = str(body.get('reason') or '')\n"
        "        outcome = str(body.get('outcome') or '')\n"
        "        if reason in ('', 'none', 'null') or outcome in drop:\n"
        "            body.pop('reason', None)\n"
        "except Exception:\n"
        "    pass\n"
    )
    customer = _leaf("string", "{{customer_id}}", "Call variable customer_id.")
    nodes = {}
    nodes["boot"] = _code("boot", "begin(vars)", blob, [("greet", "disclose")], "disclose")
    nodes["disclose"] = {
        "name": "disclose",
        "node_type": "conversation",
        "passthrough": True,
        "passthrough_default_transition": "greet",
        "on_enter": {"type": "tts", "text": "{{disclosure}}"},
        "on_enter_first_entry_only": True,
        "task_message": "Do not speak. The recording disclosure was already spoken.",
        "extraction_schema": [],
        "tools": [],
        "transitions": [_always("greet")],
    }
    nodes["greet"] = _talk(
        "greet", "greet_line", "brain_greet",
        "The recording disclosure was already spoken. Do not repeat it. Do not mention collections, debt, payment, or a product. Do not call a tool.",
    )
    nodes["brain_greet"] = _code(
        "brain_greet", "after_greet(vars)", blob,
        [("verify", "id_talk"), ("callback", "cb_talk"), ("callback_api", "api_callback"), ("close", "goodbye"), ("greet", "greet")],
        "greet",
    )
    nodes["id_talk"] = _talk(
        "id_talk", "id_line", "brain_id",
        "Say only the identity line. Do not state the balance or the product. Do not call a tool.",
    )
    nodes["brain_id"] = _code(
        "brain_id", "after_id_utterance(vars)", blob,
        [("verify_api", "api_verify"), ("speak", "id_talk"), ("close", "goodbye"), ("account", "api_account")],
        "id_talk",
    )
    nodes["api_verify"] = _api_node(
        "api_verify",
        _api(
            "verify_identity", server + "/verify_identity",
            {
                "customer_id": customer,
                "field": _leaf("string", "{{id_field}}", "Security field.", field_enum),
                "answer": _leaf("string", "{{id_answer}}", "Date as YYYY-MM-DD or four digits."),
            },
            ["customer_id", "field", "answer"],
            post=STRIP_HEADER,
        ),
        [
            _map("data.ok", "id_ok"), _map("data.verified", "id_verified"), _map("data.all_verified", "id_all"),
            _map("data.wrong_answers_left", "id_left"), _map("data.hint", "id_hint"),
        ],
        "brain_id_api",
    )
    nodes["brain_id_api"] = _code(
        "brain_id_api", "after_id_api(vars)", blob,
        [("account", "api_account"), ("speak", "id_talk"), ("close", "goodbye"), ("verify_api", "api_verify")],
        "id_talk",
    )
    nodes["api_account"] = _api_node(
        "api_account",
        _api("get_account", server + "/get_account", {"customer_id": customer}, ["customer_id"], post=STRIP_HEADER),
        [_map("data.products", "products_raw"), _map("data.ok", "account_ok")],
        "brain_prepare",
    )
    nodes["brain_prepare"] = _code("brain_prepare", "prepare_account(vars)", blob, [("speak", "present"), ("close", "goodbye")], "present")
    nodes["present"] = _talk(
        "present", "coach", "brain_talk",
        "Say only the coach line. Never ask how much the customer can pay. Never say a promise is recorded. Do not call a tool.",
    )
    talk_routes = [
        ("speak", "present"), ("record", "api_record"), ("transfer", "api_transfer"), ("close", "goodbye"),
    ]
    if blob.get("notes") == "yes":
        talk_routes.append(("note", "api_note"))
    nodes["brain_talk"] = _code("brain_talk", "after_customer(vars)", blob, talk_routes, "present")
    nodes["api_record"] = _api_node(
        "api_record",
        _api(
            "create_promise", server + "/create_promise",
            {
                "customer_id": customer,
                "product_id": _leaf("string", "{{rec_product}}", "Product id from get_account."),
                "amount": _leaf("number", "{{rec_amount}}", "Amount approved by policy."),
                "date": _leaf("string", "{{rec_date}}", "Date approved by policy, YYYY-MM-DD."),
            },
            ["customer_id", "product_id", "amount", "date"],
            pre=AMOUNT_PRE, post=STRIP_HEADER,
        ),
        [_map("data.ok", "promise_ok"), _map("data.error", "promise_error")],
        "brain_record",
    )
    nodes["brain_record"] = _code("brain_record", "after_record(vars)", blob, talk_routes, "present")
    nodes["api_transfer"] = _api_node(
        "api_transfer",
        _api(
            "transfer_to_agent", server + "/transfer_to_agent",
            {"customer_id": customer, "queue": _leaf("string", "{{transfer_queue}}", "Queue from the brief.", queue_enum)},
            ["customer_id", "queue"],
            post=STRIP_HEADER,
        ),
        [_map("data.ok", "transfer_ok")],
        "brain_transfer",
    )
    nodes["brain_transfer"] = _code(
        "brain_transfer", "after_transfer(vars)", blob,
        [("transfer", "api_transfer"), ("close", "goodbye")],
        "goodbye",
    )
    if blob.get("notes") == "yes":
        nodes["api_note"] = _api_node(
            "api_note",
            _api(
                "add_note", server + "/add_note",
                {
                    "customer_id": customer,
                    "product_id": _leaf("string", "{{note_product}}", "Product id."),
                    "reason": _leaf("string", "{{note_reason}}", "Note reason.", note_enum),
                    "text": _leaf("string", "{{note_text}}", "Short note."),
                },
                ["customer_id", "product_id", "reason"],
                post=STRIP_HEADER,
            ),
            [_map("data.ok", "note_ok")],
            "brain_note",
        )
        nodes["brain_note"] = _code("brain_note", "after_note(vars)", blob, talk_routes, "present")
    nodes["cb_talk"] = _talk(
        "cb_talk", "coach", "brain_cb",
        "Say only the callback line. Do not say why the bank is calling, and do not name a product, a balance, or a debt. Do not call a tool.",
    )
    nodes["brain_cb"] = _code(
        "brain_cb", "after_callback_utterance(vars)", blob,
        [("callback_api", "api_callback"), ("callback", "cb_talk"), ("close", "goodbye")],
        "cb_talk",
    )
    nodes["api_callback"] = _api_node(
        "api_callback",
        _api(
            "schedule_callback", server + "/schedule_callback",
            {
                "customer_id": customer,
                "date": _leaf("string", "{{cb_date}}", "Callback date YYYY-MM-DD."),
                "time": _leaf("string", "{{cb_time}}", "Callback time HH:MM."),
            },
            ["customer_id", "date", "time"],
            post=STRIP_HEADER,
        ),
        [_map("data.ok", "callback_ok")],
        "brain_cb_api",
    )
    nodes["brain_cb_api"] = _code(
        "brain_cb_api", "after_callback_api(vars)", blob,
        [("callback_api", "api_callback"), ("close", "goodbye"), ("callback", "cb_talk")],
        "goodbye",
    )
    nodes["stall"] = _code("stall", "stall(vars)", blob, [("close", "goodbye")], "goodbye")
    nodes["goodbye"] = {
        "name": "goodbye",
        "node_type": "end_call",
        "on_enter": {"type": "silent"},
        "disable_inactivity_monitor": True,
        "transitions": [],
        "terminal": {
            "type": "function",
            "function": {
                "name": "call_finished",
                "handler": "__function__:end_call",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_mode": {"type": "string", "default": "custom"},
                        "spoken_message": {"type": "string", "default": "{{farewell}}"},
                    },
                },
            },
        },
    }
    forbidden = ", ".join(blob.get("forbidden") or [])
    bank = blob.get("bank") or "the bank"
    close_tool = _api(
        "close_call", server + "/close_call",
        {
            "customer_id": customer,
            "outcome": _leaf("string", "{{outcome}}", "Outcome from the brief.", outcome_names),
            "reason": _leaf("string", "{{reason}}", "Reason from the brief. Empty when the outcome has none."),
        },
        ["customer_id", "outcome"],
        pre=close_pre,
    )
    close_tool["config"]["alwaysRunsAt"] = ["end_of_call"]
    return {
        "initial_node": "boot",
        "system_prompt": (
            "You are " + bank + "'s digital assistant on a recorded call. Speak English. "
            "Before identity is verified, do not say these words: " + (forbidden or "the balance") + ". "
            "Do not name the product or the amount before verification. "
            "Never say a payment promise was recorded unless it was recorded. "
            "Never offer a discount, a waiver, or a plan the brief does not allow. "
            "The clock for this call is {{now}}."
        ),
        "test_variables": {
            "customer_id": "c_test",
            "first_name": "Dana",
            "last_name": "Reed",
            "title": "Ms",
            "now": policy.get("example_now") or "2026-01-01T10:00",
        },
        "global_nodes": {},
        "nodes": nodes,
        "tools": [close_tool],
    }
