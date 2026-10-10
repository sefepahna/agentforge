"""Prose extraction and the CLI deploy gate. No network and no workflow rewrite."""
import hashlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agentforge.cli import build, main
from agentforge.parser import load_openapi, parse_briefs, unresolved_configuration
from agentforge.prose_extract import (
    BAND_REJECTED, FLOOR_UNBOUND, WITHDRAWAL_UNAPPLIED,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "tools" / "openapi.json"
BRIEF_A = ROOT / "briefs" / "brief-a.md"
BRIEF_B = ROOT / "briefs" / "brief-b.md"
EMAIL = MEMO = PROSE = REGIONS = CONFLICT = FLOOR = WITHDRAWAL = None
_FIXTURES = None

EMAIL_TEXT = """From: Collections Policy <policy@freyabank.example>
To: Agent operations
Subject: Early-stage collections, one product
Date: 10 October 2026

Freya Bank calls customers who are 1 to 45 days late on one product. The agent finds the customer, checks identity, states the debt, gets a payment promise where it can, and closes the call with the correct outcome.

Every call starts with customer_id, first_name, last_name, title, and now. The example clock in the specification is 2026-10-14T11:00. All date rules use now, never the real clock.

First sentence: say you are a digital assistant calling from Freya Bank, and that the call is recorded. Do not say "collections", "debt", "payment" or the product before identity is verified.

Ask "Am I speaking with {title} {last_name}?". Only "yes", "that's me", "speaking" or the customer's own name counts as confirmation. If it is still unclear after the second ask, close as not_reached / unclear.

If the customer asks whether you are a robot or an AI, say that you are Freya Bank's digital assistant and continue.

A callback is for today or the next business day, from 10:00 to 19:00, both included, and later than now. Call schedule_callback with the date and the time, then close as not_reached / callback. If the person offers a day or a time outside that window, ask once for another time. If that is also outside it, do not schedule. Close as not_reached / no_callback. If the person says the number does not belong to the customer, close as not_reached / wrong_number. If the person says the customer has died, say "I am sorry for your loss.", ask nothing else, and close as not_reached / deceased.

Ask two security questions, one at a time: first the date of birth, then the last four digits of the phone number on file. Call verify_identity with the answer. Send a date of birth as YYYY-MM-DD. Three wrong answers in total end the check. If the customer gives day and month the other way round, verify_identity returns hint day_month_swapped. Ask them to say the month as a word. That retry does not count as a wrong answer. After three wrong answers, do not state the debt. Tell the customer to use the mobile app or a branch. Close as not_verified / failed. If the customer does not want to answer, explain once. If they still decline, close as not_verified / declined.

After both questions pass, call get_account. Say that you are calling from the collections team about a late payment. Name the product in words.

Business days are Monday to Friday, except Freya Bank holidays: 2026-10-26, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01.

The deadline depends on how late the customer is. Customers 1 to 7 days late are in the early band. Their deadline is the 12th business day after today, and they receive 1 persuasion attempt. Customers 8 to 45 days late are in the late band. Their deadline is the 7th business day after today, and they receive 2 persuasion attempts.

A promise date must be today or later, a business day, and not after the deadline. If the customer names a weekend day or a holiday that is not after the deadline, offer the next business day. If the customer gives a vague period, ask once for the exact day. If they still give none, propose the deadline. Next weekday means that weekday in the following calendar week. This weekday means the one in the current week. If the customer asks for a date after the deadline, offer the deadline. If the customer refuses the deadline, treat it as a flat refusal.

Ask for the full past-due amount first. The floor is `minimum_payment` for a credit card and `instalment_amount` for a personal loan or a car loan. If the customer says the full amount is too much, offer the floor, once. If the customer proposes an amount from the floor up to the full amount, both included, accept it.

First ask: "Can you make this payment today?". A flat refusal uses one persuasion attempt. Attempt 1 proposes the last business day of this week. Attempt 2, late band only, proposes the floor amount on the deadline. When the attempts are used up, close as no_promise / refused.

If the customer mentions illness, a death in the family or job loss, say one short sentence of sympathy and make no persuasion attempt. If they accept, call transfer_to_agent with queue support and close as transferred / support. If they decline, close as no_promise / hardship.

Read the product, the amount and the date back and ask "Do you confirm?". Call create_promise only after a clear yes. One promise per product. Say the promise is recorded only after create_promise returns ok: true. If it fails, try once more. If it fails again, say you could not record it and close as no_promise / service_error. After a recorded promise, say this sentence: "You will receive a text message confirming this promise."

I already paid: say that payments can take one business day to appear, take no promise, and close as paid. This debt is not mine: close as no_promise / dispute. A request for a new payment plan: call transfer_to_agent with queue restructuring and close as transferred / restructuring. A request for a human: call transfer_to_agent with queue general and close as transferred / human.

Every call ends with exactly one close_call. Use outcome promise with no reason when at least one promise was recorded. Use outcome paid with no reason for an already-paid claim. Use outcome transferred with reason restructuring, human, or support. Use outcome no_promise with reason refused, hardship, dispute, or service_error. Use outcome not_verified with reason failed or declined. Use outcome not_reached with reason callback, no_callback, wrong_number, deceased, or unclear.

This specification never uses add_note.

Thank the customer and say goodbye before close_call.
"""

MEMO_TEXT = """MEMORANDUM
To: Collections operations
From: Freya Bank policy desk
Subject: Customers who can be late on up to three products
Date: 10 October 2026

This memo changes the earlier one-product specification. Every rule of that specification applies unless a paragraph below replaces it.

get_account returns one to three products. Each has its own past_due, days_late and floor. State every late product, one sentence each, before asking for anything. The band and the deadline are per product, from that product's days_late. Two products of the same customer can have different deadlines.

First ask whether the customer can pay all of them today. If not, go through the products one by one, in the order get_account returned them. Do not ask about today again for each product. Start each product at attempt 1. Persuasion attempts are counted per product.

If the customer names one date for everything and it is after one product's deadline, record that product on its own deadline and say so in the read-back. The other products keep the date the customer named.

Read all promises back together and ask for one confirmation. Then call create_promise once per product.

The customer may promise some products and refuse others. For each product without a promise call add_note with that product_id and a reason: refused, hardship, dispute, paid or service_error. This also applies when no product gets a promise.

A dispute or an already paid claim on one product does not end the call. Note it and continue with the others.

A restructuring request still transfers the call. Promises recorded before the request stay. Promises agreed but not yet recorded are not recorded. Close as transferred / restructuring. On any transfer (restructuring, support, human) add no notes at all, before or after it.

If one create_promise fails twice, keep the promises that were recorded and call add_note with reason service_error for the failed product.

The outcome table of the earlier specification applies. With no promise recorded: if every product is noted paid, close as paid. Otherwise close as no_promise with the reason of the first product, in get_account order, whose note is not paid. With several products, promise wins whenever at least one promise was recorded, except the transfer rule above.
"""

PROSE_TEXT = """Calls are made for Freya Bank.

Accounts that are 1 to 7 days late sit in the early band. Deadline: the 12th business day after today. They get 1 persuasion attempt.

Accounts that are 8 to 45 days late sit in the late band. Deadline: the 7th business day after today. They get 2 persuasion attempts.

The promise outcome has no reason.
The paid outcome has no reason.
The transferred outcome uses reasons restructuring, human, and support.
The no_promise outcome uses reasons refused, hardship, dispute, and service_error.
The not_verified outcome uses reasons failed and declined.
The not_reached outcome uses reasons callback, no_callback, wrong_number, deceased, and unclear.

The floor is `minimum_payment` for a credit card and `instalment_amount` for a personal loan or a car loan.

Do not say "collections", "debt", or "payment" before identity is verified. A promise date must be a business day and not after the deadline.
"""

REGIONS_TEXT = """Example only:

```
Customers 3 to 4 days late are in the sample band. Their deadline is the 2nd business day after today, and they receive 9 persuasion attempts.
```

    Customers 5 to 6 days late are in the draft band. Their deadline is the 3rd business day after today, and they receive 8 persuasion attempts.

Policy schedule:

```
Customers 1 to 7 days late are in the early band. Their deadline is the 12th business day after today, and they receive 1 persuasion attempt.
Customers 8 to 45 days late are in the late band. Their deadline is the 7th business day after today, and they receive 2 persuasion attempts.
```

Schedule:

    Customers 1 to 7 days late are in the early band. Their deadline is the 12th business day after today, and they receive 1 persuasion attempt.
    Customers 8 to 45 days late are in the late band. Their deadline is the 7th business day after today, and they receive 2 persuasion attempts.

Calls are made for Freya Bank.

The promise outcome has no reason.
The paid outcome has no reason.
The transferred outcome uses reasons restructuring, human, and support.
The no_promise outcome uses reasons refused, hardship, dispute, and service_error.
The not_verified outcome uses reasons failed and declined.
The not_reached outcome uses reasons callback, no_callback, wrong_number, deceased, and unclear.
"""

CONFLICT_TEXT = (
    "Customers 1 to 7 days late are in the early band. Their deadline is the 12th business day "
    "after today, and they receive 1 persuasion attempt. Their deadline is the 9th business day "
    "after today, and they receive 1 persuasion attempt.\n"
)

FLOOR_TEXT = """Calls are made for Freya Bank.

Accounts that are 1 to 7 days late sit in the early band. Deadline: the 12th business day after today. They get 1 persuasion attempt.

Accounts that are 8 to 45 days late sit in the late band. Deadline: the 7th business day after today. They get 2 persuasion attempts.

The promise outcome has no reason.
The paid outcome has no reason.
The transferred outcome uses reasons restructuring, human, and support.
The no_promise outcome uses reasons refused, hardship, dispute, and service_error.
The not_verified outcome uses reasons failed and declined.
The not_reached outcome uses reasons callback, no_callback, wrong_number, deceased, and unclear.

The floor is the minimum payment for a credit card and the instalment amount for a personal loan or a car loan.
"""

WITHDRAWAL_TEXT = """This amendment withdraws the late band.

Customers 8 to 45 days late are in the late band. Their deadline is the 7th business day after today, and they receive 2 persuasion attempts.
"""

MARKDOWN_CONFLICT_TEXT = """| 1 to 7 | early | the 12th business day after today | 1 |
| 8 to 45 | late | the 7th business day after today | 2 |
| Outcome | Reason |
|---|---|
| `promise` | none |

Customers 1 to 7 days late are in the early band. Their deadline is the 12th business day after today, and they receive 1 persuasion attempt. Their deadline is the 9th business day after today, and they receive 1 persuasion attempt.
"""


def _materialize(folder, name, text):
    path = Path(folder) / name
    path.write_text(text, encoding="utf-8")
    return path


def setUpModule():
    global _FIXTURES, EMAIL, MEMO, PROSE, REGIONS, CONFLICT, FLOOR, WITHDRAWAL
    _FIXTURES = tempfile.TemporaryDirectory()
    root = Path(_FIXTURES.name)
    EMAIL = _materialize(root, "email-a.md", EMAIL_TEXT)
    MEMO = _materialize(root, "memo-b.md", MEMO_TEXT)
    PROSE = _materialize(root, "eval_prose.md", PROSE_TEXT)
    REGIONS = _materialize(root, "eval_regions.md", REGIONS_TEXT)
    CONFLICT = _materialize(root, "eval_conflict.md", CONFLICT_TEXT)
    FLOOR = _materialize(root, "eval_floor_unreadable.md", FLOOR_TEXT)
    WITHDRAWAL = _materialize(root, "eval_withdrawal.md", WITHDRAWAL_TEXT)


def tearDownModule():
    if _FIXTURES is not None:
        _FIXTURES.cleanup()
HASH_A = "09dc5274f09b5c18912c500400e58b0474872ac2757599f519217395007acfbc"
HASH_B = "64aaf389b10b8544a8d3ca8c46b4d262f518943482342c5d0d975aeeb811c0fd"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class ProseFixtureTests(unittest.TestCase):
    def test_email_and_memo_fill_bands_outcomes_and_bank(self):
        policy, _workflow, errors = build([EMAIL, MEMO], SPEC)
        self.assertEqual(errors, [])
        self.assertEqual(policy["bands"], ["1|7|early|12|1", "8|45|late|7|2"])
        self.assertEqual(policy["outcomes"]["promise"], [])
        self.assertEqual(
            policy["outcomes"]["no_promise"],
            ["refused", "hardship", "dispute", "service_error"],
        )
        self.assertEqual(policy["outcomes"]["not_reached"][-1], "unclear")
        self.assertEqual(policy["blob"]["bank"], "Freya Bank")
        self.assertEqual(policy["blob"]["notes"], "yes")
        self.assertEqual(policy["floors"][:1], ["credit_card|minimum_payment"])
        self.assertEqual(policy["blob"]["id_fields"], ["date_of_birth", "phone_last4"])
        self.assertEqual(policy["blob"]["callback_start"], "10:00")
        self.assertIn("collections", policy["blob"]["forbidden"])
        self.assertEqual(unresolved_configuration(policy), [])

    def test_ordinary_negation_does_not_block_the_email(self):
        _policy, _workflow, errors = build([EMAIL], SPEC)
        self.assertEqual(errors, [])
        self.assertNotIn(WITHDRAWAL_UNAPPLIED, " ".join(errors))

    def test_independent_prose_matches_public_requirements(self):
        policy, _workflow, errors = build([PROSE], SPEC)
        self.assertEqual(errors, [])
        self.assertEqual(policy["bands"], ["1|7|early|12|1", "8|45|late|7|2"])
        self.assertEqual(set(policy["outcomes"]), {
            "promise", "paid", "transferred", "no_promise", "not_verified", "not_reached",
        })
        self.assertEqual(policy["floors"], [
            "credit_card|minimum_payment",
            "personal_loan|instalment_amount",
            "car_loan|instalment_amount",
        ])
        self.assertEqual(policy["blob"]["bank"], "Freya Bank")

    def test_example_sections_do_not_supply_bands(self):
        policy, _workflow, errors = build([REGIONS], SPEC)
        self.assertEqual(errors, [])
        self.assertEqual(policy["bands"], ["1|7|early|12|1", "8|45|late|7|2"])
        packed = " ".join(policy["bands"])
        self.assertNotIn("sample", packed)
        self.assertNotIn("draft", packed)

    def test_conflicting_band_statement_is_not_applied(self):
        policy, _workflow, errors = build([CONFLICT], SPEC)
        self.assertEqual(policy["bands"], [])
        self.assertTrue(any(item.startswith(BAND_REJECTED) for item in errors))
        inherited, _inherited_workflow, inherited_errors = build([EMAIL, CONFLICT], SPEC)
        self.assertEqual(inherited["bands"], ["1|7|early|12|1", "8|45|late|7|2"])
        self.assertEqual(unresolved_configuration(inherited), [])
        self.assertTrue(any(item.startswith(BAND_REJECTED) for item in inherited_errors))
        with tempfile.TemporaryDirectory() as folder:
            markdown = _materialize(folder, "markdown-conflict.md", MARKDOWN_CONFLICT_TEXT)
            kept, _kept_workflow, kept_errors = build([markdown], SPEC)
        self.assertEqual(kept["bands"], ["1|7|early|12|1", "8|45|late|7|2"])
        self.assertEqual(unresolved_configuration(kept), [])
        self.assertTrue(any(item.startswith(BAND_REJECTED) for item in kept_errors))

    def test_unbound_floor_blocks_even_when_bands_resolve(self):
        policy, _workflow, errors = build([FLOOR], SPEC)
        self.assertEqual(policy["bands"], ["1|7|early|12|1", "8|45|late|7|2"])
        self.assertTrue(policy["outcomes"])
        self.assertEqual(policy["floors"], [])
        self.assertEqual(unresolved_configuration(policy), [])
        self.assertTrue(any(item.startswith(FLOOR_UNBOUND) for item in errors))

    def test_withdrawal_blocks_without_deleting_inherited_bands(self):
        policy, _workflow, errors = build([EMAIL, WITHDRAWAL], SPEC)
        self.assertEqual(policy["bands"], ["1|7|early|12|1", "8|45|late|7|2"])
        self.assertTrue(any(item.startswith(WITHDRAWAL_UNAPPLIED) for item in errors))
        fake = types.ModuleType("freya")

        def save_workflow(*_args, **_kwargs):
            raise AssertionError("deploy should not run")

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            with patch("agentforge.cli.KIT", Path(folder)):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([str(EMAIL), str(WITHDRAWAL), "--openapi", str(SPEC), "--deploy"])
            trace = next((Path(folder) / "traces").glob("*.txt")).read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("deploy skipped", trace)
        self.assertIn(WITHDRAWAL_UNAPPLIED, trace)
        self.assertNotIn("freya workflow_id", trace)

    def test_markdown_briefs_keep_their_configuration(self):
        alone = parse_briefs([BRIEF_A], load_openapi(SPEC))
        policy, _workflow, errors = build([BRIEF_A], SPEC)
        merged, _workflow_b, merged_errors = build([BRIEF_A, BRIEF_B], SPEC)
        self.assertEqual(errors, [])
        self.assertEqual(merged_errors, [])
        self.assertEqual(policy["bands"], ["1|7|early|12|1", "8|45|late|7|2"])
        self.assertEqual(merged["bands"], policy["bands"])
        self.assertEqual(merged["outcomes"], policy["outcomes"])
        self.assertEqual(merged["blob"]["notes"], "yes")
        self.assertEqual(policy["blob"]["notes"], "no")
        self.assertEqual(policy["deploy_diagnostics"], [])
        self.assertEqual(alone["bands"], policy["bands"])


class WorkflowObjectTests(unittest.TestCase):
    def test_committed_workflows_match_in_memory_objects(self):
        """json.loads ignores CRLF. Byte hashes are a separate check and are not rewritten."""
        _policy_a, built_a, errors_a = build([BRIEF_A], SPEC)
        _policy_b, built_b, errors_b = build([BRIEF_A, BRIEF_B], SPEC)
        disk_a = (ROOT / "out" / "brief-a.workflow.json").read_bytes()
        disk_b = (ROOT / "out" / "brief-b.workflow.json").read_bytes()
        self.assertEqual(errors_a, [])
        self.assertEqual(errors_b, [])
        self.assertEqual(built_a, _load(ROOT / "out" / "brief-a.workflow.json"))
        self.assertEqual(built_b, _load(ROOT / "out" / "brief-b.workflow.json"))
        self.assertEqual(hashlib.sha256(disk_a).hexdigest(), HASH_A)
        self.assertEqual(hashlib.sha256(disk_b).hexdigest(), HASH_B)
        memory_a = json.dumps(built_a, indent=1).encode("utf-8")
        self.assertNotEqual(hashlib.sha256(memory_a).hexdigest(), HASH_A)
        self.assertEqual(disk_a.replace(b"\r\n", b"\n"), memory_a)


class DeployGateTests(unittest.TestCase):
    def test_unbound_floor_skips_deploy_without_calling_freya(self):
        fake = types.ModuleType("freya")

        def save_workflow(*_args, **_kwargs):
            raise AssertionError("deploy should not run")

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            with patch("agentforge.cli.KIT", Path(folder)):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([str(FLOOR), "--openapi", str(SPEC), "--deploy"])
            trace = next((Path(folder) / "traces").glob("*.txt"))
            text = trace.read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("deploy skipped", text)
        self.assertIn(FLOOR_UNBOUND, text)
        self.assertNotIn("freya workflow_id", text)

    def test_resolved_email_reaches_the_save_call_under_a_mock(self):
        fake = types.ModuleType("freya")
        calls = []

        def save_workflow(slot, _workflow):
            calls.append(slot)
            return {"workflow_id": "wf", "agent_id": "ag"}

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            with patch("agentforge.cli.KIT", Path(folder)):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([str(EMAIL), "--openapi", str(SPEC), "--deploy"])
            trace = next((Path(folder) / "traces").glob("*.txt")).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["email-a"])
        self.assertIn("freya workflow_id wf", trace)
        self.assertNotIn("deploy skipped", trace)


if __name__ == "__main__":
    unittest.main()
