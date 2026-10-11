"""Offline dialogue harness. It calls the fixture index, not Freya."""
import json

from agentforge.case_engine import begin, on_service, on_user, request_body
from agentforge.case_fixture import lookup


def run_dialogue(spec, index, customer_number, now, turns):
    """Apply service calls until the agent speaks, then each caller turn."""
    state = begin(spec, customer_number, now)
    state = _pump(state, spec, index)
    spoken = []
    if state.get("say"):
        spoken.append(state.get("say") or "")
    for turn in turns:
        if str(state.get("route") or "").startswith("end_"):
            break
        state = on_user(state, spec, turn)
        state = _pump(state, spec, index)
        spoken.append(state.get("say") or "")
    report = {}
    report["route"] = state.get("route") or ""
    report["say"] = list(spoken)
    report["tools"] = list(state.get("tools") or [])
    report["side_effect"] = state.get("side_effect") or ""
    report["facts"] = state.get("facts") or {}
    report["email_sent"] = bool(state.get("email_sent"))
    report["week_changed"] = bool(state.get("week_changed"))
    report["paraphrase"] = state.get("paraphrase") or ""
    report["phase"] = state.get("phase") or ""
    return report


def _pump(state, spec, index):
    guard = 0
    while str(state.get("route") or "").startswith("api_"):
        guard += 1
        if guard > 8:
            state["route"] = "end_agent"
            state["say"] = "service loop stopped"
            return state
        pending = state.get("pending") or ""
        operation = _operation(spec, pending)
        hit = lookup(index, operation["method"], operation["path"], request_body(state, spec))
        payload = json.loads(hit["body"])
        state = on_service(state, spec, hit["status"], payload)
    return state


def _operation(spec, name):
    for operation in spec["operations"]:
        if operation["name"] == name:
            return operation
    raise KeyError(name)
