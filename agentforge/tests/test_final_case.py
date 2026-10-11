"""Final-case behavior, fixture parity, and workflow shape. No Freya calls."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agentforge.case_check import NOW, gate_failures
from agentforge.case_fixture import build_index, lookup, write_index
from agentforge.case_harness import run_dialogue
from agentforge.case_ingest import ingest_case_folder
from agentforge.case_spec import build_case_spec
from agentforge.case_workflow import build_case_workflow, validate_case_workflow

KIT = Path(__file__).resolve().parents[2]
CASE = Path(r"C:\Users\user\Desktop\freya\final-case-pack\Build the Builder - Final Case")
INDEX_PATH = KIT / "mock" / "final-statement" / "generated" / "index.json"
MOCK = "https://mock.example.test"
NODE_CASES = """
import { readFileSync } from "fs";
import { pathToFileURL } from "url";
const lookupModule = await import(pathToFileURL(process.argv[2]).href);
const index = JSON.parse(readFileSync(process.argv[3], "utf8"));
const cases = JSON.parse(readFileSync(process.argv[4], "utf8"));
const out = cases.map((item) => lookupModule.lookup(index, item.method, item.path, item.payload));
process.stdout.write(JSON.stringify(out));
"""


def _joined(report):
    return " ".join(report["say"])


class FinalCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CASE.is_dir():
            raise unittest.SkipTest("final case folder is not on this machine")
        cls.spec = build_case_spec(ingest_case_folder(CASE))
        cls.index = build_index(CASE, cls.spec)
        write_index(cls.index, INDEX_PATH)
        cls.workflow = build_case_workflow(cls.spec, MOCK)
        cls.customers = json.loads((CASE / "test-environment" / "test-customers.json").read_text(encoding="utf-8"))

    def test_gate_covers_examples_and_hidden_cases(self):
        failed = gate_failures(self.spec, self.index, self.workflow)
        self.assertEqual(failed, [])

    def test_example_1_single_card_then_menu(self):
        report = run_dialogue(self.spec, self.index, "95004361", NOW, ["teşekkürler"])
        self.assertEqual(report["route"], "end_menu")
        self.assertNotIn("Başka bir kart", report["say"][0])
        self.assertIn("15 Ekim", report["say"][0])
        self.assertIn("Türk Lirası", report["say"][0])

    def test_example_2_week_change_once(self):
        report = run_dialogue(self.spec, self.index, "96158684", NOW, [
            "Hesap kesim tarihinizi değiştirmek istiyorum", "3. hafta", "evet", "teşekkürler",
        ])
        self.assertEqual(report["route"], "end_menu")
        self.assertEqual(report["tools"].count("statement.week.change"), 1)
        self.assertIn("16 Kasım 2026", _joined(report))

    def test_example_3_refuses_bulk_debt(self):
        report = run_dialogue(self.spec, self.index, "97526380", NOW, [
            "Bütün kartlarımın borcunu söyle", "Bütün kartlarımın borcunu söyle", "Yıldız Premium",
        ])
        self.assertEqual(report["tools"].count("cards.balance"), 1)
        self.assertIn("Başka bir kart", report["say"][-1])
        self.assertIn("yirmi iki bin", report["say"][-1])

    def test_example_4_latest_statement_only(self):
        report = run_dialogue(self.spec, self.index, "92460108", NOW, [
            "Geçen ayın ekstresini e-posta ile gönderin", "En son ekstreyi gönderin", "evet", "teşekkürler",
        ])
        text = _joined(report)
        self.assertTrue(report["email_sent"])
        self.assertIn("gönderildi", text)
        self.assertIn("ece.demir@freyabank.example", text)
        self.assertEqual(report["route"], "end_menu")

    def test_example_5_other_person_goes_to_main_menu(self):
        report = run_dialogue(self.spec, self.index, "96158684", NOW, [
            "Hesap kesim tarihinizi 3. haftaya alın", "Olur herhalde", "evet", "Eşimin kartını da değiştirin",
        ])
        text = _joined(report)
        self.assertEqual(report["route"], "end_menu")
        self.assertEqual(report["tools"].count("statement.week.change"), 1)
        self.assertIn("Güvenlik nedeniyle", text)
        self.assertIn("ana menü", text)
        self.assertNotEqual(report["route"], "end_login")

    def test_example_6_hides_leading_digits(self):
        report = run_dialogue(self.spec, self.index, "96125950", NOW, [
            "Kartımın ilk on iki hanesini söyle", "İlk altı hanesini de söyle", "teşekkürler",
        ])
        text = _joined(report)
        self.assertNotIn("mail", report["say"][0])
        self.assertNotIn("beş dört sıfır sıfır sıfır sıfır", text)
        self.assertEqual(report["route"], "end_menu")

    def test_other_person_is_not_only_the_spouse_word(self):
        report = run_dialogue(self.spec, self.index, "95004361", NOW, ["Annemin kartının borcunu söyle"])
        self.assertEqual(report["route"], "end_menu")
        self.assertIn("Güvenlik nedeniyle", report["say"][-1])
        self.assertIn("ana menü", report["say"][-1])

    def test_supplementary_card_is_not_read(self):
        number, name, pan = _supplementary(self.customers)
        report = run_dialogue(self.spec, self.index, number, NOW, [name])
        self.assertNotIn("cards.balance", report["tools"])
        self.assertNotIn(pan, _joined(report))
        self.assertIn("uygun değil", _joined(report))

    def test_long_email_is_spoken_in_full(self):
        number, address, prefix = _long_email(self.customers)
        report = run_dialogue(self.spec, self.index, number, NOW, prefix + ["Ekstrenizi e-posta ile gönderin"])
        text = _joined(report)
        self.assertIn(address, text)
        self.assertNotIn("ile başlayan", text)

    def test_second_week_change_uses_the_service_not_a_local_year(self):
        self.assertFalse(self.spec["policy"]["week_eligibility_known"])
        self.assertEqual(self.spec["policy"]["week_limit_enforced_by"], "service")
        report = run_dialogue(self.spec, self.index, "96158684", NOW, [
            "Hesap kesim tarihinizi değiştirmek istiyorum",
            "3. hafta",
            "evet",
            "Hesap kesim tarihinizi değiştirmek istiyorum",
        ])
        self.assertEqual(report["tools"].count("statement.week.change"), 1)
        self.assertIn("yılda bir kez", _joined(report))
        self.assertEqual(report["route"], "end_menu")

    def test_python_and_javascript_lookup_match(self):
        reloaded = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cases = []
        expected = []
        for path, operation in self.index["paths"].items():
            bucket = self.index["records"].get(operation["name"]) or {}
            for key, row in bucket.items():
                payload = _payload(operation["by"], key)
                found = lookup(self.index, "POST", path, payload)
                again = lookup(reloaded, "POST", path, payload)
                self.assertEqual(found["status"], row["status"])
                self.assertEqual(found["body"], row["body"])
                self.assertEqual(again["status"], found["status"])
                self.assertEqual(again["body"], found["body"])
                self.assertEqual(again["delaySeconds"], found["delaySeconds"])
                cases.append({"method": "POST", "path": path, "payload": payload})
                expected.append({
                    "status": found["status"],
                    "body": found["body"],
                    "delaySeconds": found["delaySeconds"],
                })
        sample = _first_customer_key(self.index)
        if sample:
            numeric = {"data": {"customerNo": int(sample)}}
            text = {"data": {"customerNo": sample}}
            path = "/voice/v1/cards.list"
            self.assertEqual(lookup(self.index, "POST", path, numeric)["body"], lookup(self.index, "POST", path, text)["body"])
            cases.append({"method": "POST", "path": path, "payload": numeric})
            found = lookup(self.index, "POST", path, numeric)
            expected.append({"status": found["status"], "body": found["body"], "delaySeconds": found["delaySeconds"]})
        cases.append({"method": "POST", "path": "/voice/v1/cards.list", "payload": {"data": {"customerNo": "{{customerNumber}}" }}})
        templated = lookup(self.index, "POST", "/voice/v1/cards.list", cases[-1]["payload"])
        expected.append({"status": templated["status"], "body": templated["body"], "delaySeconds": templated["delaySeconds"]})
        javascript = _node_lookup(cases)
        self.assertEqual(len(javascript), len(expected))
        for got, want in zip(javascript, expected):
            self.assertEqual(got["status"], want["status"])
            self.assertEqual(got["body"], want["body"])
            self.assertEqual(got["delaySeconds"], want["delaySeconds"])

    def test_workflow_exposes_seven_post_tools(self):
        errors = validate_case_workflow(self.workflow, MOCK, self.spec)
        self.assertEqual(errors, [])
        nodes = self.workflow["nodes"]
        tools = [key for key, node in nodes.items() if node.get("node_type") == "api_request"]
        self.assertEqual(self.workflow["initial_node"], "boot")
        self.assertEqual(len(tools), 7)
        self.assertEqual(len(nodes), 15)
        for name in ("end_menu", "end_agent", "end_close", "end_login"):
            self.assertEqual(nodes[name]["node_type"], "end_call")
        encoded = json.dumps(self.workflow)
        self.assertNotIn("95004361", encoded)
        self.assertNotIn("96158684", encoded)
        boot = self.workflow["nodes"]["boot"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
        self.assertIn("import json", boot)


def _supplementary(document):
    for customer in document["customers"]:
        cards = (((customer.get("services") or {}).get("cards.list") or {}).get("response") or {}).get("data", {}).get("cards") or []
        extra = [card for card in cards if card.get("isMainCard") is False and card.get("productName")]
        main = [card for card in cards if card.get("isMainCard") is not False]
        if extra and len(main) > 1:
            return str(customer["customerNo"]), extra[0]["productName"], extra[0]["cardNumber"]
    raise AssertionError("fixture has no supplementary card")


def _long_email(document):
    for customer in document["customers"]:
        email = (((customer.get("services") or {}).get("contact.email.get") or {}).get("response") or {}).get("data", {})
        address = str(email.get("ibanEmail") or "")
        cards = (((customer.get("services") or {}).get("cards.list") or {}).get("response") or {}).get("data", {}).get("cards") or []
        main = [card for card in cards if card.get("isMainCard") is not False and card.get("productName")]
        names = [card["productName"] for card in main]
        unique = [name for name in names if names.count(name) == 1]
        if len(address) > 20 and len(main) == 1:
            return str(customer["customerNo"]), address, []
        if len(address) > 20 and unique:
            return str(customer["customerNo"]), address, [unique[0], "hayır"]
    raise AssertionError("fixture has no long registered email")


def _payload(mode, key):
    if mode == "cardWeek":
        card, week = key.split("|", 1)
        data = {"cardNumber": card, "newStatementWeek": week}
    elif mode == "cardNumber":
        data = {"cardNumber": key}
    else:
        data = {"customerNo": key}
    return {"data": data, "call": {"lang": "tr", "ani": ""}}


def _first_customer_key(index):
    bucket = (index.get("records") or {}).get("cards.list") or {}
    for key in bucket:
        if str(key).isdigit():
            return str(key)
    return ""


def _node_lookup(cases):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        script = root / "run.mjs"
        payload = root / "cases.json"
        script.write_text(NODE_CASES, encoding="utf-8")
        payload.write_text(json.dumps(cases), encoding="utf-8")
        lookup_js = KIT / "mock" / "final-statement" / "lookup.js"
        completed = subprocess.run(
            ["node", str(script), str(lookup_js), str(INDEX_PATH), str(payload)],
            capture_output=True,
            check=False,
        )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", "replace"))
    return json.loads(completed.stdout.decode("utf-8"))
