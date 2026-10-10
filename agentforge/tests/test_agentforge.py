"""Local policy tests. They do not call Freya and they do not invent benchmark scores."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from agentforge.cli import build
from agentforge.parser import _parse_one, _roles, load_openapi, parse_briefs
from agentforge.runtime_body import (
    add_business, after_callback_api, after_customer, after_greet, after_id_api, after_id_utterance,
    after_note, after_record, attempt_day, begin, drain_notes_or_close, find_dates, is_business, is_no,
    load_products, mark_note, parse_dob, prepare_account,
)
from agentforge.validate import validate_workflow
from agentforge.workflow_builder import build_workflow

KIT = Path(__file__).resolve().parents[2]
NOW = "2026-10-14T11:00"
TODAY = __import__("datetime").date(2026, 10, 14)


def policy(*names):
    spec = load_openapi(KIT / "tools" / "openapi.json")
    return parse_briefs([KIT / "briefs" / name for name in names], spec)


def session(merged, products=None, **extra):
    vars = {
        "now": NOW, "policy_json": json.dumps(merged["blob"]),
        "title": extra.pop("title", "Ms"), "last_name": extra.pop("last_name", "Costa"),
        "first_name": extra.pop("first_name", "Maria"),
    }
    vars.update(extra)
    begin(vars)
    if products is not None:
        vars["products_raw"] = products
        prepare_account(vars)
    return vars


def say(vars, text):
    vars["user_said"] = text
    after_customer(vars)
    return vars["route"], vars.get("coach") or ""


def card(last4, past, days, minimum):
    return {"product_id": "p1", "type": "credit_card", "card_last4": last4, "past_due": past, "days_late": days, "minimum_payment": minimum}


class ParserTests(unittest.TestCase):
    def test_brief_a_tables(self):
        merged = policy("brief-a.md")
        self.assertEqual(merged["holidays"], ["2026-10-26", "2026-11-11", "2026-11-26", "2026-12-25", "2027-01-01"])
        self.assertEqual(merged["bands"][0], "1|7|early|12|1")
        self.assertEqual(merged["bands"][1], "8|45|late|7|2")
        self.assertEqual(merged["blob"]["notes"], "no")
        self.assertEqual(merged["blob"]["multi"], "no")
        self.assertEqual(merged["blob"]["id_fields"], ["date_of_birth", "phone_last4"])
        self.assertIn("collections", merged["blob"]["forbidden"])
        self.assertEqual(merged["blob"]["role_promise"], "promise")
        self.assertEqual(merged["blob"]["reason_hardship"], "hardship")
        self.assertTrue(merged["rules"])
        self.assertEqual(list(merged["outcomes"]), [
            "promise", "paid", "transferred", "no_promise", "not_verified", "not_reached",
        ])
        self.assertNotIn("customer_id", merged["outcomes"])
        self.assertEqual(merged["outcomes"]["no_promise"], ["refused", "hardship", "dispute", "service_error"])

    def test_brief_b_overrides_notes_and_keeps_calendar(self):
        merged = policy("brief-a.md", "brief-b.md")
        alone = policy("brief-a.md")
        self.assertEqual(merged["blob"]["notes"], "yes")
        self.assertEqual(merged["blob"]["multi"], "yes")
        self.assertEqual(merged["holidays"][0], "2026-10-26")
        self.assertEqual(merged["bands"][1], "8|45|late|7|2")
        self.assertEqual(merged["outcomes"], alone["outcomes"])
        self.assertEqual(merged["blob"]["role_promise"], "promise")
        self.assertEqual(merged["blob"]["reason_service_error"], "service_error")


class OutcomeBoundaryTests(unittest.TestCase):
    OUTCOME = """
| Outcome | Reason | When |
|---|---|---|
| `promise` | none | recorded |
| `paid` | none | paid |
| `no_promise` | `refused`, `dispute` | no |
"""
    VARIABLE = """
| Variable | Example | Meaning |
|---|---|---|
| `customer_id` | `c_1` | id |
| `promise` | `maybe` | not an outcome |
| `now` | `2026-10-14T11:00` | clock |
"""

    def outcomes_of(self, text):
        spec = load_openapi(KIT / "tools" / "openapi.json")
        return _parse_one(text, spec)["outcomes"]

    def test_variable_table_before_outcome_table_is_not_an_outcome(self):
        text = (
            "## 1. The job\nClose with the correct outcome.\n"
            "## 2. Call variables\n" + self.VARIABLE +
            "\n## 9. Notes between the tables\n" + self.OUTCOME
        )
        parsed = self.outcomes_of(text)
        self.assertEqual(list(parsed), ["promise", "paid", "no_promise"])
        self.assertEqual(parsed["promise"], [])
        self.assertNotIn("customer_id", parsed)
        self.assertNotIn("now", parsed)

    def test_outcome_table_before_variable_table_keeps_reasons(self):
        text = self.OUTCOME.strip() + "\n" + self.VARIABLE.strip()
        parsed = self.outcomes_of(text)
        self.assertEqual(parsed["promise"], [])
        self.assertEqual(parsed["no_promise"], ["refused", "dispute"])
        self.assertNotIn("customer_id", parsed)
        self.assertNotIn("maybe", json.dumps(parsed))

    def test_heading_that_says_outcome_does_not_reopen_the_table(self):
        text = (
            "## Outcomes\n" + self.OUTCOME +
            "\n## Outcome variables\nThe outcome list is above.\n" + self.VARIABLE
        )
        parsed = self.outcomes_of(text)
        self.assertEqual(list(parsed), ["promise", "paid", "no_promise"])

    def test_unknown_outcome_is_kept_and_malformed_row_is_not(self):
        text = """
| Outcome | Reason |
|---|---|
| `promise` | none |
| promise | `refused` |
| `escalated` | `manual` |
| `paid` | none |
"""
        parsed = self.outcomes_of(text)
        self.assertEqual(parsed["promise"], [])
        self.assertEqual(parsed["escalated"], ["manual"])
        self.assertEqual(parsed["paid"], [])
        self.assertNotIn("refused", parsed["promise"])

    def test_later_brief_without_an_outcome_table_keeps_the_map(self):
        spec = load_openapi(KIT / "tools" / "openapi.json")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "base.md"
            second = root / "extra.md"
            first.write_text("Holiday 2026-10-26 is closed.\n" + self.OUTCOME, encoding="utf-8")
            second.write_text(
                "The previous outcome still applies.\n" + self.VARIABLE + "\nNew field `account_ref`.\n",
                encoding="utf-8",
            )
            merged = parse_briefs([first, second], spec)
        self.assertEqual(list(merged["outcomes"]), ["promise", "paid", "no_promise"])
        self.assertEqual(merged["outcomes"]["promise"], [])
        self.assertIn("2026-10-26", merged["holidays"])
        self.assertNotIn("variables", merged)

    def test_later_outcome_table_replaces_the_whole_map(self):
        spec = load_openapi(KIT / "tools" / "openapi.json")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "base.md"
            second = root / "extra.md"
            first.write_text("Holiday 2026-10-26 is closed.\n" + self.OUTCOME, encoding="utf-8")
            second.write_text(
                "| Outcome | Reason |\n|---|---|\n| `escalated` | `manual` |\n",
                encoding="utf-8",
            )
            merged = parse_briefs([first, second], spec)
        self.assertEqual(merged["outcomes"], {"escalated": ["manual"]})
        self.assertIn("2026-10-26", merged["holidays"])


def session_with_bands(merged, bands, products):
    blob = json.loads(json.dumps(merged["blob"]))
    blob["bands"] = bands
    vars = {
        "now": NOW, "policy_json": json.dumps(blob),
        "title": "Ms", "last_name": "Costa", "first_name": "Maria",
    }
    begin(vars)
    vars["products_raw"] = products
    prepare_account(vars)
    return vars


class ReleaseSafetyTests(unittest.TestCase):
    def setUp(self):
        self.single = policy("brief-a.md")
        self.multi = policy("brief-a.md", "brief-b.md")

    def test_unmatched_days_late_does_not_record_a_promise(self):
        for days in (0, 46, 60, 99):
            vars = session(self.single, [card("1111", 420, days, 100)])
            self.assertEqual(vars["route"], "close", days)
            self.assertEqual(vars["outcome"], "no_promise", days)
            self.assertEqual(vars["reason"], "service_error", days)
            self.assertNotEqual(vars.get("promise_recorded"), "yes", days)
            self.assertFalse(vars.get("rec_product"), days)
            spoken = (vars.get("coach") or "") + " " + (vars.get("farewell") or "")
            self.assertNotIn("420.00", spoken, days)
            say(vars, "Yes, I can pay today.")
            say(vars, "Yes, I confirm.")
            self.assertNotEqual(vars["route"], "record", days)
            self.assertNotEqual(vars.get("promise_recorded"), "yes", days)

    def test_configured_band_edges_still_offer(self):
        expected = {1: "early", 7: "early", 8: "late", 45: "late"}
        for days, band in expected.items():
            vars = session(self.single, [card("1111", 420, days, 100)])
            item = json.loads(vars["products_json"])[0]
            self.assertEqual(vars["route"], "speak", days)
            self.assertEqual(item["band"], band, days)
            self.assertNotEqual(item["deadline"], "", days)
            say(vars, "Yes, I can pay today.")
            say(vars, "Yes, I confirm.")
            self.assertEqual(vars["route"], "record", days)
            self.assertEqual(vars["rec_amount"], "420.00", days)
            vars["promise_ok"] = "false"
            after_record(vars)
            self.assertNotEqual(vars.get("promise_recorded"), "yes", days)

    def test_alternative_brief_bands_and_authorized_zero(self):
        product = card("1111", 420, 0, 100)
        allowed = session_with_bands(self.single, ["0|3|fresh|2|1"], [product])
        self.assertEqual(allowed["route"], "speak")
        self.assertEqual(json.loads(allowed["products_json"])[0]["band"], "fresh")
        blocked = session_with_bands(self.single, ["0|3|fresh|2|1"], [card("1111", 420, 4, 100)])
        self.assertEqual(blocked["route"], "close")
        self.assertEqual(blocked["reason"], "service_error")
        self.assertNotEqual(blocked.get("promise_recorded"), "yes")
        low = session_with_bands(self.single, ["10|20|mid|3|1"], [card("1111", 420, 10, 100)])
        high = session_with_bands(self.single, ["10|20|mid|3|1"], [card("1111", 420, 20, 100)])
        below = session_with_bands(self.single, ["10|20|mid|3|1"], [card("1111", 420, 9, 100)])
        above = session_with_bands(self.single, ["10|20|mid|3|1"], [card("1111", 420, 21, 100)])
        self.assertEqual(json.loads(low["products_json"])[0]["band"], "mid")
        self.assertEqual(json.loads(high["products_json"])[0]["band"], "mid")
        self.assertEqual(below["route"], "close")
        self.assertEqual(above["route"], "close")
        self.assertNotEqual(below.get("promise_recorded"), "yes")
        self.assertNotEqual(above.get("promise_recorded"), "yes")

    def test_outcome_roles_use_exact_names(self):
        outcomes = {
            "side_promise": [],
            "promise": [],
            "pre_promise": [],
            "promised": [],
            "no_promise_extra": ["refused"],
            "no_promise": ["refused"],
            "prepaid": [],
            "paid": [],
            "transfer": ["human"],
            "transferred": ["human"],
            "verified": ["failed"],
            "not_verified_extra": ["failed"],
            "not_verified": ["failed"],
            "reached": ["unclear"],
            "not_reached_now": ["unclear"],
            "not_reached": ["unclear"],
            "escalated": ["manual"],
        }
        roles = _roles(outcomes, ["support", "general", "restructuring"])
        self.assertEqual(roles["role_promise"], "promise")
        self.assertEqual(roles["role_no_promise"], "no_promise")
        self.assertEqual(roles["role_paid"], "paid")
        self.assertEqual(roles["role_transferred"], "transferred")
        self.assertEqual(roles["role_not_verified"], "not_verified")
        self.assertEqual(roles["role_not_reached"], "not_reached")
        self.assertEqual(roles["unsupported_outcomes"], ["side_promise", "pre_promise", "promised", "no_promise_extra", "prepaid", "transfer", "verified", "not_verified_extra", "reached", "not_reached_now", "escalated"])
        only = _roles({"escalated": ["manual"], "side_promise": []}, [])
        self.assertEqual(only["role_promise"], "")
        self.assertEqual(only["unsupported_outcomes"], ["escalated", "side_promise"])
        brief = policy("brief-a.md", "brief-b.md")
        self.assertEqual(brief["unsupported_outcomes"], [])
        self.assertEqual(brief["blob"]["role_promise"], "promise")
        self.assertNotIn("unsupported_outcomes", brief["blob"])

    def test_unsupported_outcome_is_not_a_close_enum(self):
        spec = load_openapi(KIT / "tools" / "openapi.json")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "extra.md"
            path.write_text("| Outcome | Reason |\n|---|---|\n| `escalated` | `manual` |\n| `promise` | none |\n", encoding="utf-8")
            policy_out, workflow, errors = build([path], KIT / "tools" / "openapi.json")
        self.assertIn("escalated", policy_out["unsupported_outcomes"])
        self.assertEqual(policy_out["blob"]["role_promise"], "promise")
        self.assertTrue(any("escalated" in error for error in errors))
        encoded = json.dumps(workflow)
        self.assertNotIn('"escalated"', encoded)


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.merged = policy("brief-a.md")
        self.holidays = set(self.merged["holidays"])

    def test_business_days_and_holiday(self):
        self.assertFalse(is_business(TODAY.replace(day=26), self.holidays))
        self.assertEqual(add_business(TODAY, 7, self.holidays).isoformat(), "2026-10-23")
        self.assertEqual(add_business(TODAY, 12, self.holidays).isoformat(), "2026-11-02")
        self.assertEqual(attempt_day(TODAY, self.holidays).isoformat(), "2026-10-16")

    def test_deadlines_and_floor_on_products(self):
        late = session(self.merged, [card("4821", 1250, 14, 400)])
        product = json.loads(late["products_json"])[0]
        self.assertEqual(product["deadline"], "2026-10-23")
        self.assertEqual(product["floor"], 400)
        early = session(self.merged, [{"product_id": "p1", "type": "personal_loan", "past_due": 540, "days_late": 5, "instalment_amount": 180}])
        product = json.loads(early["products_json"])[0]
        self.assertEqual(product["deadline"], "2026-11-02")
        self.assertEqual(product["floor"], 180)
        self.assertIn("collections", early["coach"])
        self.assertNotIn("how much can you", early["coach"].lower())


class IdentityAndThirdPartyTests(unittest.TestCase):
    def setUp(self):
        self.merged = policy("brief-a.md")

    def test_opening_hides_the_debt(self):
        vars = session(self.merged)
        for word in ("collections", "debt", "payment", "recorded"):
            self.assertNotIn(word, vars["greet_line"].lower())
        self.assertEqual(vars["disclosure"].count("recorded"), 1)
        self.assertIn("digital assistant", vars["disclosure"].lower())
        self.assertIn("this call is recorded", vars["disclosure"].lower())
        for word in ("collections", "debt", "payment", "card", "loan"):
            self.assertNotIn(word, vars["disclosure"].lower())
        vars["user_said"] = "who is this"
        after_greet(vars)
        self.assertEqual(vars["route"], "greet")
        self.assertNotIn("recorded", vars["greet_line"].lower())
        self.assertEqual(vars["disclosure"].count("recorded"), 1)

    def test_relative_callback_does_not_verify(self):
        vars = session(self.merged, products=None, title="Ms", last_name="Costa")
        vars["user_said"] = "I am her husband. What is this about? I can pay. Maria can be reached tomorrow morning around eleven."
        after_greet(vars)
        self.assertEqual(vars["route"], "callback_api")
        self.assertEqual(vars["cb_date"], "2026-10-15")
        self.assertEqual(vars["cb_time"], "11:00")
        self.assertNotIn("verify", vars["route"])
        blob = json.dumps(vars)
        self.assertNotIn("past_due", blob)

    def test_three_wrong_answers_do_not_disclose(self):
        vars = session(self.merged)
        vars["user_said"] = "yes"
        after_greet(vars)
        self.assertEqual(vars["route"], "verify")
        vars["user_said"] = "12 July 1991"
        after_id_utterance(vars)
        self.assertEqual(vars["id_answer"], "1991-07-12")
        vars["id_verified"] = "false"
        vars["id_left"] = "0"
        vars["id_ok"] = "true"
        after_id_api(vars)
        self.assertEqual(vars["outcome"], "not_verified")
        self.assertEqual(vars["reason"], "failed")
        self.assertIn("app", vars["extra_line"].lower())
        self.assertNotIn("4821", vars["extra_line"])

    def test_deceased_and_decline(self):
        vars = session(self.merged)
        vars["user_said"] = "I am sorry, he passed away."
        after_greet(vars)
        self.assertEqual(vars["reason"], "deceased")
        self.assertIn("sorry", vars["extra_line"].lower())
        vars = session(self.merged)
        vars["user_said"] = "yes"
        after_greet(vars)
        vars["user_said"] = "Why do you need that?"
        after_id_utterance(vars)
        self.assertEqual(vars["route"], "speak")
        vars["user_said"] = "I still will not answer. What is this about?"
        after_id_utterance(vars)
        self.assertEqual(vars["reason"], "declined")


class NegotiationTests(unittest.TestCase):
    def setUp(self):
        self.merged = policy("brief-a.md")

    def test_pay_today_needs_confirmation_and_api_success(self):
        vars = session(self.merged, [card("4821", 420, 6, 126)])
        route, coach = say(vars, "I can pay the full amount today.")
        self.assertEqual(route, "speak")
        self.assertIn("Do you confirm?", coach)
        self.assertNotIn("recorded", coach.lower())
        route, _coach = say(vars, "Yes, I confirm.")
        self.assertEqual(route, "record")
        self.assertEqual(vars["rec_amount"], "420.00")
        self.assertEqual(vars["rec_date"], "2026-10-14")
        vars["promise_ok"] = "false"
        after_record(vars)
        self.assertEqual(vars["route"], "record")
        self.assertEqual(vars["promise_line"], "")
        vars["promise_ok"] = "true"
        after_record(vars)
        self.assertEqual(vars["outcome"], "promise")
        self.assertEqual(vars["reason"], "")
        self.assertIn("text message", vars["promise_line"])
        self.assertNotIn("call is recorded", vars["farewell"].lower())

    def test_opening_disclosure_is_not_a_promise_claim(self):
        vars = session(self.merged)
        self.assertIn("digital assistant", vars["disclosure"].lower())
        self.assertIn("this call is recorded", vars["disclosure"].lower())
        self.assertNotIn("promise", vars["disclosure"].lower())
        self.assertNotIn("quality and compliance", vars["disclosure"].lower())
        workflow = build_workflow(self.merged, load_openapi(KIT / "tools" / "openapi.json"))
        self.assertEqual(workflow["nodes"]["disclose"]["transitions"][0]["target_node"], "greet")
        id_targets = [edge["target_node"] for edge in workflow["nodes"]["disclose"]["transitions"]]
        self.assertNotIn("id_talk", id_targets)
        vars = session(self.merged, [card("7740", 365, 8, 109.5)])
        _route, coach = say(vars, "I can pay the full amount this Friday.")
        self.assertIn("I will record", coach)
        self.assertNotIn("recorded", coach.lower())
        self.assertNotIn("is recorded", vars.get("farewell", "").lower())
        vars["promise_ok"] = "false"
        after_record(vars)
        self.assertEqual(vars["route"], "record")
        self.assertNotEqual(vars.get("outcome"), "promise")
        vars["promise_ok"] = "true"
        after_record(vars)
        self.assertIn("text message confirming this promise", vars["farewell"].lower())

    def test_deadline_holiday_floor_refusal_hardship(self):
        vars = session(self.merged, [{"product_id": "p1", "type": "car_loan", "past_due": 1250, "days_late": 14, "instalment_amount": 400}])
        _route, coach = say(vars, "My salary arrives on 6 November. Are you a robot?")
        self.assertIn("digital assistant", coach.lower())
        self.assertIn("23 October", coach)
        self.assertIn("Do you confirm?", coach)
        vars = session(self.merged, [{"product_id": "p1", "type": "personal_loan", "past_due": 540, "days_late": 5, "instalment_amount": 180}])
        say(vars, "I cannot pay today.")
        say(vars, "The week after next.")
        _route, coach = say(vars, "Monday the 26th.")
        self.assertIn("27 October", coach)
        self.assertNotIn("26 October", coach.split("not a business day")[-1] if "not a business day" in coach else coach)
        vars = session(self.merged, [card("1903", 2125.1, 12, 637.5)])
        _route, coach = say(vars, "The full amount is too much right now.")
        self.assertNotIn("how much can you", coach.lower())
        self.assertIn("637.50", coach)
        self.assertIn("rest stays overdue", coach.lower())
        self.assertIn("16 October", coach)
        vars = session(self.merged, [{"product_id": "p1", "type": "personal_loan", "past_due": 780, "days_late": 21, "instalment_amount": 260}])
        _route, coach = say(vars, "I lost my job and I cannot pay anything. Can I get a discount?")
        self.assertIn("sorry", coach.lower())
        self.assertIn("support", coach.lower())
        self.assertIn("cannot offer a discount", coach.lower())
        say(vars, "No, do not transfer me.")
        self.assertEqual(vars["outcome"], "no_promise")
        self.assertEqual(vars["reason"], "hardship")
        self.assertNotEqual(vars["route"], "transfer")

    def test_spoken_date_past_deadline_offers_full_amount(self):
        product = {"product_id": "p1", "type": "car_loan", "past_due": 880, "days_late": 14, "instalment_amount": 300}
        vars = session(self.merged, [product])
        item = json.loads(vars["products_json"])[0]
        self.assertFalse(is_no("My salary arrives on six November and I can pay then."))
        self.assertEqual(find_dates("six November", TODAY), [__import__("datetime").date(2026, 11, 6)])
        _route, coach = say(vars, "My salary arrives on six November and I can pay then.")
        self.assertIn(item["deadline"], vars.get("pending") or "")
        self.assertIn("880.00", coach)
        self.assertNotIn("300.00", coach)
        self.assertIn("latest date", coach.lower())
        self.assertIn("Do you confirm?", coach)
        self.assertNotEqual(vars["route"], "record")
        say(vars, "Yes, I confirm.")
        self.assertEqual(vars["route"], "record")
        self.assertEqual(vars["rec_amount"], "880.00")
        self.assertEqual(vars["rec_date"], item["deadline"])

    def test_rejecting_a_readback_does_not_record(self):
        product = {"product_id": "p1", "type": "car_loan", "past_due": 880, "days_late": 14, "instalment_amount": 300}
        vars = session(self.merged, [product])
        say(vars, "I can pay on the sixth of November.")
        self.assertEqual(vars["neg_phase"], "confirm")
        say(vars, "No, I do not confirm.")
        self.assertNotEqual(vars["route"], "record")
        self.assertNotEqual(vars.get("outcome"), "promise")
        self.assertIn("?", vars["coach"])

    def test_refusal_uses_the_attempt_limit(self):
        vars = session(self.merged, [card("0377", 95, 4, 28.5)])
        say(vars, "I cannot pay today.")
        self.assertEqual(vars["offer_open"], "yes")
        say(vars, "No.")
        self.assertEqual(vars["outcome"], "no_promise")
        self.assertEqual(vars["reason"], "refused")


class MultiProductTests(unittest.TestCase):
    def setUp(self):
        self.merged = policy("brief-a.md", "brief-b.md")

    def test_one_date_and_split_deadlines(self):
        products = [
            card("2288", 220, 9, 66),
            {"product_id": "p2", "type": "personal_loan", "past_due": 640, "days_late": 9, "instalment_amount": 213},
            {"product_id": "p3", "type": "car_loan", "past_due": 75, "days_late": 3, "instalment_amount": 25},
        ]
        vars = session(self.merged, products, title="Ms", last_name="Almeida")
        self.assertEqual(vars["coach"].lower().count("past due"), 3)
        _route, coach = say(vars, "I cannot pay today, but I can pay all three this Friday.")
        self.assertIn("220.00", coach)
        self.assertIn("640.00", coach)
        self.assertIn("75.00", coach)
        self.assertEqual(coach.lower().count("do you confirm?"), 1)
        say(vars, "Yes, I confirm.")
        self.assertEqual(vars["route"], "record")
        dates = [bit.split("|")[2] for bit in vars["queue"].split(";")]
        self.assertEqual(dates, ["2026-10-16", "2026-10-16", "2026-10-16"])
        pair = [
            card("6604", 300, 4, 90),
            {"product_id": "p2", "type": "personal_loan", "past_due": 900, "days_late": 20, "instalment_amount": 300},
        ]
        vars = session(self.merged, pair)
        _route, coach = say(vars, "I cannot pay today. I want to pay both on 30 October.")
        self.assertIn("30 October", coach)
        self.assertIn("23 October", coach)

    def test_one_promise_and_refused_notes(self):
        products = [
            card("9015", 510, 16, 153),
            {"product_id": "p2", "type": "personal_loan", "past_due": 1320, "days_late": 16, "instalment_amount": 440},
            {"product_id": "p3", "type": "car_loan", "past_due": 140, "days_late": 7, "instalment_amount": 46},
        ]
        vars = session(self.merged, products)
        say(vars, "I will pay the credit card tomorrow, but I refuse the personal loan and the car loan.")
        self.assertEqual(vars["route"], "speak")
        self.assertIn("personal loan", vars["coach"])
        say(vars, "No.")
        self.assertIn("personal loan", vars["coach"])
        say(vars, "No.")
        self.assertIn("car loan", vars["coach"])
        say(vars, "No.")
        self.assertIn("Do you confirm?", vars["coach"])
        self.assertIn("510.00", vars["coach"])
        say(vars, "Yes, I confirm.")
        self.assertEqual(vars["rec_product"], "p1")
        self.assertEqual(vars["rec_date"], "2026-10-15")
        vars["promise_ok"] = "true"
        after_record(vars)
        self.assertEqual(vars["route"], "note")
        noted = []
        for _ in range(4):
            if vars["route"] != "note":
                break
            noted.append((vars["note_product"], vars["note_reason"]))
            vars["note_ok"] = "true"
            from agentforge.runtime_body import after_note
            after_note(vars)
        self.assertIn(("p2", "refused"), noted)
        self.assertIn(("p3", "refused"), noted)
        self.assertEqual(vars["outcome"], "promise")


class BenchmarkRegressionTests(unittest.TestCase):
    def test_spoken_dates_and_unparsed_cap(self):
        self.assertEqual(parse_dob("Seventeenth May nineteen eighty six."), "1986-05-17")
        self.assertEqual(parse_dob("Twelve July nineteen ninety-one."), "1991-07-12")
        self.assertEqual(parse_dob("Twenty-one August nineteen ninety-two."), "1992-08-21")
        merged = policy("brief-a.md")
        vars = session(merged)
        vars["user_said"] = "yes"
        after_greet(vars)
        vars["user_said"] = "not a date"
        after_id_utterance(vars)
        after_id_utterance(vars)
        after_id_utterance(vars)
        self.assertEqual(vars["route"], "close")
        self.assertEqual(vars["reason"], "failed")
        self.assertIn("app", vars["farewell"].lower())
        self.assertNotIn("{{", vars["farewell"])

    def test_account_products_use_node_response_keys(self):
        merged = policy("brief-a.md")
        vars = session(merged, products=None)
        vars["account_ok"] = "true"
        vars["api_account_response.data.products.0.product_id"] = "p9"
        vars["api_account_response.data.products.0.type"] = "credit_card"
        vars["api_account_response.data.products.0.card_last4"] = "1111"
        vars["api_account_response.data.products.0.past_due"] = 50
        vars["api_account_response.data.products.0.days_late"] = 6
        vars["api_account_response.data.products.0.minimum_payment"] = 15
        self.assertEqual(load_products(vars)[0]["product_id"], "p9")
        prepare_account(vars)
        self.assertEqual(vars["route"], "speak")
        self.assertIn("credit card ending 1111", vars["coach"])
        self.assertNotEqual(vars["outcome"] if "outcome" in vars else "", "no_promise")

    def test_farewell_has_no_empty_placeholder(self):
        spec = load_openapi(KIT / "tools" / "openapi.json")
        workflow = build_workflow(policy("brief-a.md"), spec)
        spoken = workflow["nodes"]["goodbye"]["terminal"]["function"]["parameters"]["properties"]["spoken_message"]["default"]
        self.assertEqual(spoken, "{{farewell}}")
        self.assertNotIn("promise_line", spoken)
        merged = policy("brief-a.md")
        vars = session(merged)
        vars["user_said"] = "he passed away"
        after_greet(vars)
        self.assertNotIn("{{", vars["farewell"])
        self.assertTrue(vars["farewell"].strip())

    def test_three_spoken_wrong_dates_reach_the_checker(self):
        merged = policy("brief-a.md")
        vars = session(merged)
        vars["user_said"] = "yes this is me"
        after_greet(vars)
        vars["user_said"] = "Twelve July nineteen ninety-one."
        after_id_utterance(vars)
        self.assertEqual(vars["route"], "verify_api")
        self.assertEqual(vars["id_answer"], "1991-07-12")
        vars["api_verify_response.data.verified"] = "false"
        vars["api_verify_response.data.ok"] = "true"
        vars["api_verify_response.data.wrong_answers_left"] = 0
        vars["api_verify_response.data.all_verified"] = "false"
        after_id_api(vars)
        self.assertEqual(vars["reason"], "failed")
        self.assertIn("branch", vars["farewell"].lower())

    def test_compound_ordinal_does_not_use_the_short_word(self):
        self.assertEqual(find_dates("Monday the twenty sixth.", TODAY), [TODAY.replace(day=26)])
        self.assertEqual(find_dates("the sixth", TODAY), [__import__("datetime").date(2026, 11, 6)])
        merged = policy("brief-a.md")
        product = {
            "product_id": "p1", "type": "personal_loan", "past_due": 540, "days_late": 5, "instalment_amount": 180,
        }
        vars = session(merged, products=[product])
        say(vars, "No, I cannot pay today. I can pay the week after next.")
        self.assertIn("exact day", vars["coach"].lower())
        say(vars, "Monday the twenty sixth.")
        self.assertIn("27 October 2026", vars["coach"])
        self.assertNotIn("2 November", vars["coach"])
        self.assertIn("2026-10-27", vars.get("pending") or "")


class ProposalTests(unittest.TestCase):
    """Amounts, confirm-stage intents, and hardship proposals. No public case ids."""

    def setUp(self):
        self.merged = policy("brief-a.md")
        self.multi = policy("brief-a.md", "brief-b.md")

    def test_explicit_amount_is_not_replaced_by_the_balance(self):
        vars = session(self.merged, [card("4821", 420, 6, 126)])
        route, coach = say(vars, "I can pay 200 on Friday.")
        self.assertEqual(route, "speak")
        self.assertIn("200.00", coach)
        self.assertNotIn("420.00", coach)
        self.assertIn("Do you confirm?", coach)
        self.assertNotIn("recorded", coach.lower())
        self.assertNotEqual(vars.get("promise_recorded"), "yes")
        route, _coach = say(vars, "Yes, I confirm.")
        self.assertEqual(route, "record")
        self.assertEqual(vars["rec_amount"], "200.00")
        self.assertEqual(vars["rec_date"], "2026-10-16")
        self.assertNotEqual(vars.get("outcome"), "promise")
        vars["promise_ok"] = "false"
        after_record(vars)
        self.assertNotEqual(vars.get("outcome"), "promise")
        self.assertNotIn("text message", (vars.get("promise_line") or "").lower())
        self.assertEqual(vars["route"], "record")
        vars["promise_ok"] = "true"
        after_record(vars)
        self.assertEqual(vars["outcome"], "promise")
        self.assertIn("text message", vars["farewell"].lower())

    def test_amount_without_a_date_is_held(self):
        vars = session(self.merged, [card("4821", 420, 6, 126)])
        route, coach = say(vars, "I can pay 200.")
        self.assertEqual(route, "speak")
        self.assertIn("200.00", coach)
        self.assertNotIn("420.00", coach)
        self.assertNotEqual(route, "record")
        route, coach = say(vars, "Friday.")
        self.assertIn("200.00", coach)
        self.assertNotIn("420.00", coach)
        self.assertIn("Do you confirm?", coach)
        self.assertNotEqual(route, "record")

    def test_revised_amount_and_date_drop_the_previous_proposal(self):
        vars = session(self.merged, [card("4821", 420, 6, 126)])
        say(vars, "I can pay the full amount today.")
        self.assertIn("420.00", vars["pending"])
        route, coach = say(vars, "Change the amount to 200.")
        self.assertEqual(route, "speak")
        self.assertIn("200.00", coach)
        self.assertNotIn("420.00", vars.get("pending") or "")
        self.assertNotEqual(route, "record")
        route, coach = say(vars, "Can we do Friday instead?")
        self.assertIn("200.00", coach)
        self.assertIn("16 October", coach)
        self.assertNotEqual(route, "record")
        say(vars, "Yes, I confirm.")
        self.assertEqual(vars["route"], "record")
        self.assertEqual(vars["rec_amount"], "200.00")
        self.assertEqual(vars["rec_date"], "2026-10-16")

    def test_conditional_acceptance_does_not_record_the_old_amount(self):
        vars = session(self.merged, [card("4821", 420, 6, 126)])
        say(vars, "I can pay the full amount today.")
        route, coach = say(vars, "I accept, but only 200.")
        self.assertEqual(route, "speak")
        self.assertIn("200.00", coach)
        self.assertNotIn("420.00", vars.get("pending") or "")
        self.assertNotEqual(route, "record")

    def test_discussion_is_not_acceptance(self):
        vars = session(self.merged, [card("4821", 420, 6, 126)])
        route, coach = say(vars, "What about 200 on Friday?")
        self.assertEqual(route, "speak")
        self.assertIn("200.00", coach)
        self.assertIn("Do you confirm?", coach)
        self.assertNotEqual(route, "record")
        self.assertNotEqual(vars.get("outcome"), "promise")

    def test_below_floor_is_not_replaced_with_the_balance(self):
        vars = session(self.merged, [card("4821", 420, 6, 126)])
        route, coach = say(vars, "I can only pay 10 dollars on Friday.")
        self.assertEqual(route, "speak")
        self.assertIn("10.00", coach)
        self.assertIn("126.00", coach)
        self.assertNotIn("420.00", coach)
        self.assertNotIn("420.00", vars.get("pending") or "")
        self.assertNotEqual(route, "record")
        say(vars, "Yes.")
        self.assertIn("126.00", vars["coach"])
        self.assertIn("Do you confirm?", vars["coach"])
        self.assertNotEqual(vars["route"], "record")
        say(vars, "Yes, I confirm.")
        self.assertEqual(vars["route"], "record")
        self.assertEqual(vars["rec_amount"], "126.00")
        high = session(self.merged, [card("4821", 420, 6, 126)])
        route, coach = say(high, "I can pay 900 on Friday.")
        self.assertEqual(route, "speak")
        self.assertIn("cannot record 900.00", coach)
        self.assertIn("420.00", coach)
        self.assertEqual(high.get("pending") or "", "")
        self.assertNotEqual(route, "record")

    def test_confirm_stage_dispute_paid_plan_and_hardship(self):
        dispute = session(self.merged, [card("4821", 420, 6, 126)])
        say(dispute, "I can pay the full amount today.")
        say(dispute, "This debt is not mine.")
        self.assertEqual(dispute["outcome"], "no_promise")
        self.assertEqual(dispute["reason"], "dispute")
        self.assertNotEqual(dispute["route"], "record")
        self.assertEqual(dispute.get("pending") or "", "")

        paid = session(self.merged, [card("4821", 420, 6, 126)])
        say(paid, "I can pay the full amount today.")
        say(paid, "I already paid this.")
        self.assertEqual(paid["outcome"], "paid")
        self.assertEqual(paid["reason"], "")
        self.assertNotEqual(paid["route"], "record")

        plan = session(self.merged, [card("4821", 420, 6, 126)])
        say(plan, "I can pay the full amount today.")
        say(plan, "I need a new payment plan.")
        self.assertEqual(plan["route"], "transfer")
        self.assertEqual(plan["transfer_queue"], "restructuring")
        self.assertNotEqual(plan.get("outcome"), "promise")
        self.assertEqual(plan.get("pending") or "", "")

        hardship = session(self.merged, [card("4821", 420, 14, 126)])
        say(hardship, "I can pay the full amount today.")
        route, coach = say(hardship, "I lost my job.")
        self.assertEqual(route, "speak")
        self.assertIn("sorry", coach.lower())
        self.assertIn("support", coach.lower())
        self.assertNotEqual(route, "record")
        self.assertNotEqual(hardship.get("outcome"), "promise")

    def test_hardship_with_and_without_a_proposal(self):
        bare = session(self.merged, [card("4821", 420, 14, 126)])
        route, coach = say(bare, "I lost my job and I cannot pay anything.")
        self.assertEqual(route, "speak")
        self.assertIn("sorry", coach.lower())
        self.assertIn("support", coach.lower())
        self.assertNotEqual(bare.get("outcome"), "promise")

        tentative = session(self.merged, [card("4821", 420, 14, 126)])
        route, coach = say(tentative, "I lost my job. Maybe next week.")
        self.assertEqual(route, "speak")
        self.assertIn("sorry", coach.lower())
        self.assertIn("exact day", coach.lower())
        self.assertNotEqual(route, "transfer")
        self.assertNotEqual(tentative.get("outcome"), "promise")

        proposed = session(self.merged, [card("4821", 420, 14, 126)])
        route, coach = say(proposed, "I lost my job but I can pay 200 on Friday.")
        self.assertEqual(route, "speak")
        self.assertIn("sorry", coach.lower())
        self.assertIn("200.00", coach)
        self.assertNotIn("420.00", coach)
        self.assertIn("Do you confirm?", coach)
        self.assertNotIn("support", coach.lower())
        self.assertNotEqual(route, "record")
        say(proposed, "Yes, I confirm.")
        self.assertEqual(proposed["route"], "record")
        self.assertEqual(proposed["rec_amount"], "200.00")
        self.assertNotEqual(proposed.get("outcome"), "promise")

    def test_multi_product_amounts_stay_on_the_named_accounts(self):
        products = [
            card("1111", 500, 10, 100),
            {"product_id": "p2", "type": "personal_loan", "past_due": 900, "days_late": 20, "instalment_amount": 300},
        ]
        vars = session(self.multi, products)
        route, coach = say(vars, "I can pay 200 on the credit card and 400 on the personal loan on Friday.")
        self.assertEqual(route, "speak")
        self.assertIn("200.00", coach)
        self.assertIn("400.00", coach)
        self.assertNotIn("500.00", coach)
        self.assertNotIn("900.00", coach)
        self.assertEqual(coach.lower().count("do you confirm?"), 1)
        self.assertNotEqual(route, "record")
        say(vars, "Yes, I confirm.")
        self.assertEqual(vars["route"], "record")
        self.assertEqual(vars["rec_product"], "p1")
        self.assertEqual(vars["rec_amount"], "200.00")
        amounts = [bit.split("|")[1] for bit in vars["queue"].split(";")]
        self.assertEqual(amounts, ["200.00", "400.00"])

class TerminationTests(unittest.TestCase):
    def setUp(self):
        self.merged = policy("brief-a.md")
        self.multi = policy("brief-a.md", "brief-b.md")

    def test_first_and_repeated_termination_do_not_persuade(self):
        late = session(self.merged, [card("4821", 420, 14, 126)])
        before = late.get("attempt_map") or ""
        route, coach = say(late, "I do not want to talk.")
        self.assertEqual(route, "speak")
        self.assertNotEqual(late.get("offer_open"), "yes")
        self.assertNotIn("126.00", coach)
        self.assertNotIn("420.00", coach)
        self.assertEqual(late.get("attempt_map") or "", before)
        self.assertNotEqual(late.get("outcome"), "no_promise")
        route, coach = say(late, "I do not want to talk.")
        self.assertEqual(route, "close")
        self.assertEqual(late["outcome"], "no_promise")
        self.assertEqual(late["reason"], "refused")
        self.assertNotIn("126.00", coach)
        self.assertNotEqual(late.get("promise_recorded"), "yes")
        self.assertEqual(late.get("attempt_map") or "", before)

    def test_termination_after_discussion_confirm_and_revision(self):
        discussed = session(self.merged, [card("4821", 420, 6, 126)])
        say(discussed, "I can pay 200 on Friday.")
        self.assertIn("200.00", discussed.get("pending") or "")
        route, coach = say(discussed, "I do not want to continue.")
        self.assertEqual(route, "speak")
        self.assertNotEqual(route, "record")
        self.assertEqual(discussed.get("pending") or "", "")
        self.assertNotIn("200.00", coach)
        say(discussed, "I do not want to continue.")
        self.assertEqual(discussed["route"], "close")
        self.assertEqual(discussed["outcome"], "no_promise")
        self.assertEqual(discussed["reason"], "refused")

        revised = session(self.merged, [card("4821", 420, 6, 126)])
        say(revised, "I can pay the full amount today.")
        say(revised, "Change the amount to 200.")
        self.assertEqual(revised["neg_phase"], "confirm")
        say(revised, "I do not want to talk.")
        self.assertNotEqual(revised["route"], "record")
        self.assertEqual(revised.get("pending") or "", "")
        say(revised, "End the call.")
        self.assertEqual(revised["route"], "close")
        self.assertEqual(revised["outcome"], "no_promise")
        self.assertEqual(revised["reason"], "refused")
        self.assertNotEqual(revised.get("promise_recorded"), "yes")

    def test_payment_refusal_still_uses_attempts(self):
        late = session(self.merged, [card("4821", 420, 14, 126)])
        say(late, "I do not want to pay.")
        self.assertEqual(late["offer_open"], "yes")
        self.assertIn("420.00", late["coach"])
        self.assertNotEqual(late.get("outcome"), "no_promise")
        say(late, "No.")
        self.assertIn("126.00", late["coach"])
        self.assertNotEqual(late.get("outcome"), "no_promise")
        used = late.get("attempt_map") or ""
        say(late, "I cannot pay that.")
        self.assertEqual(late["route"], "close")
        self.assertEqual(late["outcome"], "no_promise")
        self.assertEqual(late["reason"], "refused")
        self.assertEqual(late.get("attempt_map") or "", used)

    def test_callback_and_hardship_are_not_termination(self):
        relative = session(self.merged, products=None, title="Ms", last_name="Costa")
        relative["user_said"] = "I am her husband. Maria can be reached tomorrow morning around eleven."
        after_greet(relative)
        self.assertEqual(relative["route"], "callback_api")
        self.assertEqual(relative["cb_time"], "11:00")
        self.assertNotEqual(relative.get("outcome"), "no_promise")

        busy = session(self.merged, [card("4821", 420, 14, 126)])
        route, coach = say(busy, "I can't talk right now. Please call me back tomorrow at eleven.")
        self.assertEqual(route, "speak")
        self.assertNotEqual(busy.get("offer_open"), "yes")
        self.assertNotIn("420.00", coach)
        self.assertNotIn("126.00", coach)
        self.assertEqual(busy.get("pending") or "", "")
        self.assertNotEqual(busy.get("outcome"), "no_promise")
        route, coach = say(busy, "Tomorrow at eleven.")
        self.assertNotEqual(route, "record")
        self.assertEqual(busy.get("pending") or "", "")
        self.assertNotIn("420.00", coach)

        hardship = session(self.merged, [card("4821", 420, 14, 126)])
        route, coach = say(hardship, "I lost my job and I cannot pay anything.")
        self.assertEqual(route, "speak")
        self.assertIn("support", coach.lower())
        self.assertNotEqual(hardship.get("outcome"), "no_promise")

        dispute = session(self.merged, [card("4821", 420, 6, 126)])
        say(dispute, "This debt is not mine.")
        self.assertEqual(dispute["route"], "close")
        self.assertEqual(dispute["outcome"], "no_promise")
        self.assertEqual(dispute["reason"], "dispute")

    def test_termination_before_verification_and_multi_close(self):
        greet = session(self.merged)
        greet["user_said"] = "I do not want to talk."
        after_greet(greet)
        self.assertNotEqual(greet["route"], "verify")
        self.assertNotIn("payment", greet["greet_line"].lower())
        greet["user_said"] = "I do not want to talk."
        after_greet(greet)
        self.assertEqual(greet["route"], "close")
        self.assertEqual(greet["outcome"], "not_verified")
        self.assertEqual(greet["reason"], "declined")

        products = [
            card("1111", 500, 10, 100),
            {"product_id": "p2", "type": "personal_loan", "past_due": 900, "days_late": 20, "instalment_amount": 300},
        ]
        multi = session(self.multi, products)
        say(multi, "I do not want to talk.")
        say(multi, "I do not want to talk.")
        self.assertEqual(multi["route"], "note")
        self.assertEqual(multi["note_reason"], "refused")
        self.assertNotEqual(multi.get("promise_recorded"), "yes")
        noted = []
        for _ in range(4):
            if multi["route"] != "note":
                break
            noted.append(multi["note_product"])
            multi["note_ok"] = "true"
            from agentforge.runtime_body import after_note
            after_note(multi)
        self.assertEqual(noted, ["p1", "p2"])
        self.assertEqual(multi["route"], "close")
        self.assertEqual(multi["outcome"], "no_promise")
        self.assertEqual(multi["reason"], "refused")


class WorkflowTests(unittest.TestCase):
    def test_workflow_is_valid_and_gates_tools(self):
        spec = load_openapi(KIT / "tools" / "openapi.json")
        for names, uses_notes in ((("brief-a.md",), False), (("brief-a.md", "brief-b.md"), True)):
            merged = policy(*names)
            workflow = build_workflow(merged, spec)
            errors = validate_workflow(workflow, merged["server"])
            self.assertEqual(errors, [], errors)
            blob = json.dumps(workflow)
            self.assertIn("/close_call", blob)
            self.assertIn("end_of_call", blob)
            self.assertNotIn("agent_config", workflow)
            self.assertEqual(("api_note" in workflow["nodes"]), uses_notes)
            self.assertNotIn("{{", workflow["nodes"]["boot"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"])
            disclose = workflow["nodes"]["disclose"]
            self.assertEqual(disclose["on_enter"], {"type": "tts", "text": "{{disclosure}}"})
            self.assertTrue(disclose["passthrough"])
            self.assertTrue(disclose["on_enter_first_entry_only"])
            self.assertEqual(disclose["transitions"][0]["target_node"], "greet")
            self.assertEqual(workflow["nodes"]["boot"]["transitions"][0]["target_node"], "disclose")
            self.assertEqual(workflow["nodes"]["greet"]["on_enter"]["text"], "{{greet_line}}")
            entered_from = [
                name for name, node in workflow["nodes"].items()
                for edge in node.get("transitions") or [] if edge.get("target_node") == "disclose"
            ]
            self.assertEqual(set(entered_from), {"boot"})
        callback = session(policy("brief-a.md"))
        callback["callback_ok"] = "true"
        callback["cb_date"] = "2026-10-15"
        after_callback_api(callback)
        self.assertEqual(callback["outcome"], "not_reached")
        self.assertEqual(callback["reason"], "callback")


class DataIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.single = policy("brief-a.md")
        self.multi = policy("brief-a.md", "brief-b.md")

    def test_missing_null_and_malformed_balances_are_not_offered(self):
        cases = [
            {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "days_late": 6, "minimum_payment": 40},
            {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "past_due": None, "days_late": 6, "minimum_payment": 40},
            {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "past_due": "", "days_late": 6, "minimum_payment": 40},
            {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "past_due": "not-a-number", "days_late": 6, "minimum_payment": 40},
            {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "past_due": 420, "minimum_payment": 40},
            {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "past_due": 420, "days_late": None, "minimum_payment": 40},
            {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "past_due": 420, "days_late": "later", "minimum_payment": 40},
        ]
        for raw in cases:
            vars = session(self.single, [raw])
            self.assertEqual(vars["route"], "close", raw)
            self.assertEqual(vars["outcome"], "no_promise", raw)
            self.assertEqual(vars["reason"], "service_error", raw)
            spoken = (vars.get("coach") or "") + " " + (vars.get("farewell") or "")
            self.assertNotIn("0.00", spoken, raw)
            self.assertNotIn("40.00", spoken, raw)
            self.assertNotIn("420.00", spoken, raw)
            self.assertEqual(json.loads(vars["products_json"]), [], raw)

    def test_real_zero_balance_is_not_treated_as_missing(self):
        raw = {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "past_due": 0, "days_late": 6, "minimum_payment": 0}
        vars = session(self.single, [raw])
        self.assertEqual(vars["route"], "speak")
        self.assertIn("0.00 past due", vars["coach"])
        self.assertNotEqual(vars.get("outcome"), "no_promise")
        stored = json.loads(vars["products_json"])[0]
        self.assertEqual(stored["past_due"], 0)
        self.assertEqual(stored["past_kind"], "ok")

    def test_api_rejection_ignores_a_valid_balance(self):
        vars = session(self.single)
        vars["account_ok"] = "false"
        vars["products_raw"] = [card("1111", 420, 6, 100)]
        prepare_account(vars)
        self.assertEqual(vars["route"], "close")
        self.assertEqual(vars["reason"], "service_error")
        self.assertIn("could not open the account", vars["farewell"].lower())
        self.assertNotIn("420.00", vars["farewell"])
        self.assertEqual(json.loads(vars["products_json"]), [])

    def test_floor_fields_do_not_replace_a_missing_balance(self):
        card_raw = {"product_id": "p1", "type": "credit_card", "card_last4": "1111", "days_late": 6, "minimum_payment": 80}
        loan_raw = {"product_id": "p2", "type": "personal_loan", "days_late": 9, "instalment_amount": 60, "past_due": None}
        vars = session(self.multi, [card_raw, loan_raw, {"product_id": "p3", "type": "car_loan", "past_due": 180, "days_late": 9, "instalment_amount": 50}])
        self.assertEqual(vars["route"], "speak")
        amounts = set(re.findall(r"\d+\.\d{2}", vars["coach"]))
        self.assertEqual(amounts, {"180.00"})
        self.assertIn("could not read the balance", vars["coach"].lower())
        self.assertIn("p1|service_error", vars["notes_queue"])
        self.assertIn("p2|service_error", vars["notes_queue"])
        self.assertNotIn("p1", vars["noted_ids"])
        self.assertNotIn("p2", vars["noted_ids"])
        self.assertEqual([item["product_id"] for item in json.loads(vars["products_json"])], ["p3"])

    def test_note_is_complete_only_after_ok(self):
        products = [
            card("9015", 510, 16, 153),
            {"product_id": "p2", "type": "personal_loan", "past_due": 1320, "days_late": 16, "instalment_amount": 440},
        ]
        vars = session(self.multi, products)
        vars["recorded_ids"] = "p1"
        vars["promise_recorded"] = "yes"
        mark_note(vars, "p2", "refused")
        self.assertNotIn("p2", vars["noted_ids"])
        self.assertNotIn("p2", vars.get("done_notes") or "")
        drain_notes_or_close(vars, json.loads(vars["products_json"]), self.multi["blob"])
        self.assertEqual(vars["route"], "note")
        self.assertEqual(vars["note_product"], "p2")
        self.assertNotIn("p2", vars["noted_ids"])
        vars["note_ok"] = "false"
        after_note(vars)
        self.assertEqual(vars["route"], "note")
        self.assertEqual(vars["note_tries"], "1")
        self.assertNotIn("p2", vars["noted_ids"])
        vars["note_ok"] = "true"
        after_note(vars)
        self.assertIn("p2", vars["noted_ids"])
        self.assertIn("p2|refused", vars["done_notes"])
        self.assertEqual(vars["outcome"], "promise")
        self.assertNotIn("could not store", vars["farewell"].lower())

    def test_second_note_failure_does_not_count_as_done(self):
        products = [
            card("9015", 510, 16, 153),
            {"product_id": "p2", "type": "personal_loan", "past_due": 1320, "days_late": 16, "instalment_amount": 440},
        ]
        vars = session(self.multi, products)
        vars["recorded_ids"] = "p1"
        vars["promise_recorded"] = "yes"
        mark_note(vars, "p2", "refused")
        drain_notes_or_close(vars, json.loads(vars["products_json"]), self.multi["blob"])
        vars["note_ok"] = "false"
        after_note(vars)
        vars["note_ok"] = "false"
        after_note(vars)
        self.assertEqual(vars["route"], "close")
        self.assertEqual(vars["outcome"], "promise")
        self.assertEqual(vars["reason"], "")
        self.assertNotIn("p2", vars["noted_ids"])
        self.assertNotIn("refused", vars.get("done_notes") or "")
        self.assertIn("p2", vars["note_blocked"])
        self.assertIn("could not store that note", vars["farewell"].lower())
        self.assertNotEqual(vars["route"], "note")

    def test_ambiguous_note_result_is_not_retried(self):
        products = [
            card("9015", 510, 16, 153),
            {"product_id": "p2", "type": "personal_loan", "past_due": 1320, "days_late": 16, "instalment_amount": 440},
        ]
        vars = session(self.multi, products)
        vars["recorded_ids"] = "p1"
        vars["promise_recorded"] = "yes"
        mark_note(vars, "p2", "refused")
        drain_notes_or_close(vars, json.loads(vars["products_json"]), self.multi["blob"])
        vars["note_ok"] = ""
        vars["add_note_response.data.ok"] = ""
        after_note(vars)
        self.assertEqual(vars["route"], "close")
        self.assertEqual(vars["note_tries"], "0")
        self.assertEqual(vars["note_fault"], "yes")
        self.assertNotIn("p2", vars["noted_ids"])
        self.assertIn("p2", vars["note_blocked"])
        self.assertEqual(vars["outcome"], "promise")

    def test_stale_success_does_not_complete_the_next_note(self):
        products = [
            card("9015", 510, 16, 153),
            {"product_id": "p2", "type": "personal_loan", "past_due": 1320, "days_late": 16, "instalment_amount": 440},
            {"product_id": "p3", "type": "car_loan", "past_due": 140, "days_late": 7, "instalment_amount": 46},
        ]
        vars = session(self.multi, products)
        mark_note(vars, "p1", "refused")
        mark_note(vars, "p2", "dispute")
        mark_note(vars, "p3", "hardship")
        drain_notes_or_close(vars, json.loads(vars["products_json"]), self.multi["blob"])
        vars["note_ok"] = "true"
        vars["add_note_response.data.ok"] = "true"
        after_note(vars)
        self.assertEqual(vars["note_product"], "p2")
        self.assertEqual(vars["note_ok"], "")
        self.assertEqual(vars["add_note_response.data.ok"], "")
        self.assertIn("p1", vars["noted_ids"])
        self.assertNotIn("p2", vars["noted_ids"])
        after_note(vars)
        self.assertEqual(vars["route"], "note")
        self.assertEqual(vars["note_product"], "p3")
        self.assertNotIn("p2", vars["noted_ids"])
        self.assertIn("p2", vars["note_blocked"])
        self.assertEqual(vars["note_fault"], "yes")


if __name__ == "__main__":
    unittest.main()
