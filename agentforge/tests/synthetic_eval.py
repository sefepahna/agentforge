"""Offline synthetic-brief observations. No Freya calls and no production changes.

The runner prints the Phase 3 diagnostic matrix. Tests assert the same facts.
A safe reject is not reported as a successful policy implementation.
"""
import json
from pathlib import Path

from agentforge.cli import build
from agentforge.parser import load_openapi
from agentforge.runtime_body import after_id_utterance, begin, field_prompt, prepare_account

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic"
SPEC = ROOT / "tools" / "openapi.json"
NOW = "2026-04-02T11:00"
DISCLOSURE = (
    "Hello, this is a digital assistant calling from Harbor Mutual. "
    "We are recording this call."
)
FLOOR_LINE = (
    "3. The floor is `minimum_payment` for a credit card and "
    "`instalment_amount` for a personal loan."
)
NATURAL_FLOOR = (
    "3. A credit card settlement must stay at or above the minimum payment, "
    "and a personal loan settlement must stay at or above the instalment amount."
)
IDENTITY_LINE = (
    "2. Ask two security questions, one at a time: first the date of birth, "
    "then the last four digits of the phone number on file. "
    "Three wrong answers in total end the check."
)
POSTCODE_LINE = (
    "2. Ask one security question: the customer postcode. "
    "Three wrong answers in total end the check."
)
CALLBACK_LINE = (
    "4. A callback is for today or the next business day, from 09:15 to 16:45, both included."
)
CONFLICTING_CALLBACK = (
    "4. A callback is for today or the next business day, from 09:15 to 16:45, both included. "
    "A later desk note sets the window from 08:00 to 12:00."
)
WITHDRAWAL_TEXT = (
    "# Update: Harbor Mutual\n\n"
    "The amber and crimson schedule is withdrawn and no longer applies.\n"
)
LABELED_TEXT = """Policy fields
Holiday: 2026-03-17
Holiday: 2026-07-04
days_late_low: 2
days_late_high: 10
band: amber
deadline_business_day: 9
persuasion_attempts: 1
outcome.promise: none
outcome.no_promise: refused
floor.credit_card: minimum_payment
floor.personal_loan: instalment_amount
identity.field: postcode
max_wrong: 2
max_products: 4
callback_start: 09:15
callback_end: 16:45
notes: no
"""
PROSE_BANDS = (
    "Customers who are 2 to 10 days late are in the amber band. "
    "The deadline is the 9th business day. Persuasion attempts: 1. "
    "Customers who are 11 to 30 days late are in the crimson band. "
    "The deadline is the 4th business day. Persuasion attempts: 2.\n\n"
)
OUTCOME_CONFLICT = (
    "Use outcome promise with no reason. Use outcome promise with reason refused.\n\n"
)
CARD = {
    "product_id": "c1",
    "type": "credit_card",
    "card_last4": "4242",
    "past_due": 200,
    "days_late": 5,
    "minimum_payment": 40,
}
LOAN = {
    "product_id": "c2",
    "type": "personal_loan",
    "past_due": 80,
    "days_late": 5,
    "instalment_amount": 15,
}
EXPECTED_BANDS = ["2|10|amber|9|1", "11|30|crimson|4|2"]
EXPECTED_OUTCOMES = {
    "promise": [],
    "paid": [],
    "transferred": ["support", "human"],
    "no_promise": ["refused", "hardship", "dispute", "service_error"],
    "not_verified": ["failed", "declined"],
    "not_reached": ["callback", "no_callback", "wrong_number", "deceased", "unclear"],
}
EXPECTED_FLOORS = [
    "credit_card|minimum_payment",
    "personal_loan|instalment_amount",
]


def base_text():
    return (FIXTURES / "syn01_structured.md").read_text(encoding="utf-8")


def prose_band_text(text):
    start = text.index("| `days_late` |")
    end = text.index("## Amounts")
    return text[:start] + PROSE_BANDS + text[end:]


def outcome_conflict_text(text):
    start = text.index("| Outcome | Reason | When |")
    end = text.index("Harbor Mutual never uses")
    return text[:start] + OUTCOME_CONFLICT + text[end:]


def variant_texts(text):
    """Single-dimension edits of the structured base, plus the labeled brief."""
    return {
        "syn02_key_value.md": LABELED_TEXT,
        "syn03_natural_floor.md": text.replace(FLOOR_LINE, NATURAL_FLOOR),
        "syn04_withdrawal.md": WITHDRAWAL_TEXT,
        "syn05_two_wrong.md": text.replace("Three wrong answers", "Two wrong answers"),
        "syn06_four_products.md": text.replace("on one product", "on up to four products"),
        "syn07_postcode.md": text.replace(IDENTITY_LINE, POSTCODE_LINE),
        "syn08_window_conflict.md": text.replace(CALLBACK_LINE, CONFLICTING_CALLBACK),
        "syn08_outcome_conflict.md": outcome_conflict_text(text),
        "syn01_prose_bands.md": prose_band_text(text),
    }


def compile_paths(paths):
    return build([str(path) for path in paths], str(SPEC))


def executable(policy):
    blob = policy["blob"]
    return {
        "bands": list(policy["bands"]),
        "outcomes": policy["outcomes"],
        "floors": list(policy["floors"]),
        "holidays": list(policy["holidays"]),
        "notes": blob["notes"],
        "multi": blob["multi"],
        "bank": blob["bank"],
        "sentence": blob["sentence"],
        "sorry": blob["sorry"],
        "forbidden": list(blob["forbidden"]),
        "callback_start": blob["callback_start"],
        "callback_end": blob["callback_end"],
        "id_fields": list(blob["id_fields"]),
        "max_wrong": policy["max_wrong"],
        "max_products": policy["max_products"],
        "max_wrong_in_blob": "max_wrong" in blob,
        "max_products_in_blob": "max_products" in blob,
        "diagnostics": list(policy.get("deploy_diagnostics") or []),
        "unsupported": list(policy.get("unsupported_outcomes") or []),
    }


def open_session(policy, products):
    variables = {
        "now": NOW,
        "policy_json": json.dumps(policy["blob"]),
        "title": "Mx",
        "last_name": "Adeyemi",
    }
    begin(variables)
    variables["products_raw"] = products
    prepare_account(variables)
    return variables


def product_rows(policy, products):
    variables = open_session(policy, products)
    return json.loads(variables["products_json"]), variables


def local_misses(policy, attempts):
    variables = {
        "now": NOW,
        "policy_json": json.dumps(policy["blob"]),
        "title": "Mx",
        "last_name": "Adeyemi",
    }
    begin(variables)
    trace = []
    for _index in range(attempts):
        variables["user_said"] = "banana"
        after_id_utterance(variables)
        trace.append({
            "route": variables.get("route"),
            "outcome": variables.get("outcome"),
            "id_miss": variables.get("id_miss"),
        })
    return trace


def structured_case():
    policy, workflow, errors = compile_paths([FIXTURES / "syn01_structured.md"])
    rows, variables = product_rows(policy, [CARD])
    return {
        "policy": policy,
        "workflow": workflow,
        "errors": errors,
        "signature": executable(policy),
        "floor": rows[0]["floor"],
        "disclosure": variables["disclosure"],
        "node_count": len(workflow["nodes"]),
        "initial": workflow.get("initial_node"),
    }


def labeled_case():
    policy, workflow, errors = compile_paths([FIXTURES / "syn02_key_value.md"])
    return {
        "policy": policy,
        "workflow": workflow,
        "errors": errors,
        "signature": executable(policy),
        "node_count": len(workflow["nodes"]),
    }


def natural_floor_case():
    policy, workflow, errors = compile_paths([FIXTURES / "syn03_natural_floor.md"])
    rows, _variables = product_rows(policy, [CARD, LOAN])
    return {
        "policy": policy,
        "workflow": workflow,
        "errors": errors,
        "signature": executable(policy),
        "card_floor": rows[0]["floor"],
        "loan_floor": rows[1]["floor"],
    }


def withdrawal_case():
    policy, workflow, errors = compile_paths([
        FIXTURES / "syn01_structured.md",
        FIXTURES / "syn04_withdrawal.md",
    ])
    return {"policy": policy, "workflow": workflow, "errors": errors, "signature": executable(policy)}


def wrong_limit_case():
    policy, workflow, errors = compile_paths([FIXTURES / "syn05_two_wrong.md"])
    return {
        "policy": policy,
        "workflow": workflow,
        "errors": errors,
        "signature": executable(policy),
        "misses": local_misses(policy, 3),
    }


def product_cap_case():
    policy, workflow, errors = compile_paths([FIXTURES / "syn06_four_products.md"])
    products = []
    for number in range(1, 6):
        products.append({
            "product_id": "c%d" % number,
            "type": "credit_card",
            "card_last4": "%04d" % number,
            "past_due": 100 + number,
            "days_late": 5,
            "minimum_payment": 20,
        })
    rows, _variables = product_rows(policy, products)
    return {
        "policy": policy,
        "workflow": workflow,
        "errors": errors,
        "signature": executable(policy),
        "kept_ids": [row["product_id"] for row in rows],
    }


def postcode_case():
    policy, workflow, errors = compile_paths([FIXTURES / "syn07_postcode.md"])
    return {
        "policy": policy,
        "workflow": workflow,
        "errors": errors,
        "signature": executable(policy),
        "prompt": field_prompt(policy["blob"], 0),
        "parsed_fields": list(policy["id_fields"]),
        "rule_text": " ".join(rule["text"] for rule in policy["rules"]),
    }


def window_conflict_case():
    policy, workflow, errors = compile_paths([FIXTURES / "syn08_window_conflict.md"])
    return {"policy": policy, "workflow": workflow, "errors": errors, "signature": executable(policy)}


def outcome_conflict_case():
    policy, workflow, errors = compile_paths([FIXTURES / "syn08_outcome_conflict.md"])
    return {"policy": policy, "workflow": workflow, "errors": errors, "signature": executable(policy)}


def zero_wrong_merge():
    """A zero limit is parsed as 0 and then dropped because the merge treats 0 as missing."""
    from tempfile import TemporaryDirectory

    from agentforge.parser import _parse_one, parse_briefs

    spec = load_openapi(SPEC)
    text = "0 wrong answers end the check.\n"
    parsed = _parse_one(text, spec)
    with TemporaryDirectory() as folder:
        path = Path(folder) / "zero.md"
        path.write_text(text, encoding="utf-8")
        alone = parse_briefs([path], spec)
    return {
        "parsed": parsed["max_wrong"],
        "merged": alone["max_wrong"],
        "in_blob": "max_wrong" in alone["blob"],
    }


def matrix_lines():
    structured = structured_case()
    labeled = labeled_case()
    floor = natural_floor_case()
    withdrawal = withdrawal_case()
    wrong = wrong_limit_case()
    products = product_cap_case()
    postcode = postcode_case()
    window = window_conflict_case()
    outcome = outcome_conflict_case()
    rows = [
        ("SYN-01", "PASS", "structured tables bind; validation empty; floor %s" % structured["floor"]),
        ("SYN-02", "SAFE_REJECT", "errors %s" % len(labeled["errors"])),
        ("SYN-03", "FAIL", "card floor %s loan floor %s errors %s" % (
            floor["card_floor"], floor["loan_floor"], len(floor["errors"]),
        )),
        ("SYN-04", "SAFE_REJECT", "bands kept %s" % (withdrawal["signature"]["bands"] == EXPECTED_BANDS)),
        ("SYN-05", "FAIL", "max_wrong %s misses %s" % (
            wrong["signature"]["max_wrong"], [item["id_miss"] for item in wrong["misses"]],
        )),
        ("SYN-06", "FAIL", "cap %s kept %s" % (products["signature"]["max_products"], products["kept_ids"])),
        ("SYN-07", "SAFE_REJECT", "identity errors %s" % [
            item for item in postcode["errors"] if item.startswith("unsupported identity")
        ]),
        ("SYN-08", "FAIL+SAFE_REJECT", "window %s-%s kept with %s errors; outcome conflict errors %s" % (
            window["signature"]["callback_start"],
            window["signature"]["callback_end"],
            len(window["errors"]),
            len(outcome["errors"]),
        )),
    ]
    return rows


def main():
    for case_id, label, detail in matrix_lines():
        print(case_id + " " + label + " " + detail)


if __name__ == "__main__":
    main()
