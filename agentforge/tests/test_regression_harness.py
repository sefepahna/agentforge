"""Offline locks for the public 13/13 policy. No Freya calls and no benchmark claims."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agentforge.cli import build, main
from agentforge.parser import load_openapi, parse_briefs
from agentforge.runtime_body import after_customer, after_greet, after_record, begin, prepare_account
from agentforge.validate import validate_workflow
from agentforge.workflow_builder import build_workflow

KIT = Path(__file__).resolve().parents[2]
SPEC = KIT / "tools" / "openapi.json"
BRIEF_A = KIT / "briefs" / "brief-a.md"
BRIEF_B = KIT / "briefs" / "brief-b.md"
NOW = "2026-10-14T11:00"
DISCLOSURE = "Hello, this is a digital assistant calling from Freya Bank. We are recording this call."
HASH_A = "6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da"
HASH_B = "56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf"
NODES_A = {
    "api_account", "api_callback", "api_record", "api_transfer", "api_verify", "boot",
    "brain_cb", "brain_cb_api", "brain_greet", "brain_id", "brain_id_api", "brain_prepare",
    "brain_record", "brain_talk", "brain_transfer", "cb_talk", "disclose", "goodbye",
    "greet", "id_talk", "present", "stall",
}
NODES_B = NODES_A | {"api_note", "brain_note"}
GREET_TARGETS = {"id_talk", "cb_talk", "api_callback", "goodbye", "greet"}


def _policy(*paths):
    return parse_briefs(list(paths), load_openapi(SPEC))


def _card():
    return {
        "product_id": "p1", "type": "credit_card", "card_last4": "4821",
        "past_due": 420, "days_late": 6, "minimum_payment": 126,
    }


def _ready():
    merged = _policy(BRIEF_A)
    vars = {
        "now": NOW, "policy_json": json.dumps(merged["blob"]),
        "title": "Ms", "last_name": "Costa", "first_name": "Maria",
    }
    begin(vars)
    vars["products_raw"] = [_card()]
    prepare_account(vars)
    vars["user_said"] = "I can pay the full amount today."
    after_customer(vars)
    vars["user_said"] = "Yes, I confirm."
    after_customer(vars)
    return vars


def _targets(node):
    return {edge.get("target_node") for edge in node.get("transitions") or []}


class PromiseStateTests(unittest.TestCase):
    def test_explicit_false_retries_once_then_closes_without_a_promise(self):
        vars = _ready()
        self.assertEqual(vars["route"], "record")
        self.assertNotEqual(vars.get("promise_recorded"), "yes")
        vars["promise_ok"] = "false"
        after_record(vars)
        self.assertEqual(vars["route"], "record")
        self.assertEqual(vars["record_tries"], "1")
        self.assertEqual(vars.get("promise_line"), "")
        self.assertNotEqual(vars.get("promise_recorded"), "yes")
        self.assertNotEqual(vars.get("outcome"), "promise")
        vars["promise_ok"] = "false"
        after_record(vars)
        self.assertEqual(vars["route"], "close")
        self.assertEqual(vars["outcome"], "no_promise")
        self.assertEqual(vars["reason"], "service_error")
        self.assertNotEqual(vars.get("promise_recorded"), "yes")
        self.assertNotIn("p1", vars.get("recorded_ids") or "")
        self.assertIn("could not record", vars["farewell"].lower())

    def test_blank_promise_result_retries_once_then_closes(self):
        vars = _ready()
        vars["promise_ok"] = ""
        vars.pop("create_promise_response.data.ok", None)
        after_record(vars)
        self.assertEqual(vars["route"], "record")
        self.assertEqual(vars["record_tries"], "1")
        self.assertNotEqual(vars.get("promise_recorded"), "yes")
        vars["promise_ok"] = ""
        after_record(vars)
        self.assertEqual(vars["route"], "close")
        self.assertEqual(vars["outcome"], "no_promise")
        self.assertEqual(vars["reason"], "service_error")
        self.assertNotEqual(vars.get("promise_recorded"), "yes")

    def test_success_after_failure_records_one_promise(self):
        vars = _ready()
        vars["promise_ok"] = "false"
        after_record(vars)
        vars["promise_ok"] = "true"
        after_record(vars)
        self.assertEqual(vars["route"], "close")
        self.assertEqual(vars["outcome"], "promise")
        self.assertEqual(vars["reason"], "")
        self.assertEqual(vars["promise_recorded"], "yes")
        self.assertEqual(vars["recorded_ids"], "p1")
        self.assertEqual(vars["record_tries"], "0")
        self.assertIn("text message", vars["promise_line"].lower())
        self.assertIn("text message", vars["farewell"].lower())


class IdentityGateTests(unittest.TestCase):
    def test_greeting_cannot_reach_account_tools(self):
        merged = _policy(BRIEF_A)
        workflow = build_workflow(merged, load_openapi(SPEC))
        self.assertEqual(validate_workflow(workflow, merged["server"]), [])
        nodes = workflow["nodes"]
        self.assertEqual(_targets(nodes["brain_greet"]), GREET_TARGETS)
        self.assertNotIn("api_account", _targets(nodes["brain_greet"]))
        self.assertNotIn("api_verify", _targets(nodes["brain_greet"]))
        for name in ("greet", "id_talk", "present", "cb_talk"):
            self.assertEqual(nodes[name].get("tools"), [])

    def test_yes_at_greeting_starts_identity_not_account(self):
        merged = _policy(BRIEF_A)
        vars = {
            "now": NOW, "policy_json": json.dumps(merged["blob"]),
            "title": "Ms", "last_name": "Costa", "first_name": "Maria",
        }
        begin(vars)
        self.assertEqual(vars["disclosure"], DISCLOSURE)
        vars["user_said"] = "yes"
        after_greet(vars)
        self.assertEqual(vars["route"], "verify")
        self.assertFalse(vars.get("products_raw"))
        self.assertFalse(vars.get("rec_product"))


class DeployGateRegressionTests(unittest.TestCase):
    def _run(self, text, name):
        fake = types.ModuleType("freya")

        def save_workflow(*_args, **_kwargs):
            raise AssertionError("deploy should not run")

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            brief = root / name
            brief.write_text(text, encoding="utf-8")
            with patch("agentforge.cli.KIT", root):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([str(brief), "--openapi", str(SPEC), "--deploy"])
            trace = next((root / "traces").glob("*.txt")).read_text(encoding="utf-8")
        return code, trace

    def test_unsupported_outcome_skips_deploy(self):
        text = (
            "| 1 to 7 | early | 12th business day | 1 |\n"
            "| Outcome | Reason |\n|---|---|\n"
            "| `escalated` | `manual` |\n| `promise` | none |\n"
        )
        code, trace = self._run(text, "extra.md")
        self.assertEqual(code, 1)
        self.assertIn("deploy skipped", trace)
        self.assertIn("unsupported outcomes are not implemented: escalated", trace)
        self.assertNotIn("freya workflow_id", trace)

    def test_missing_bands_and_outcomes_skip_deploy(self):
        code, trace = self._run("Holiday 2026-10-26 is closed.\n", "missing.md")
        self.assertEqual(code, 1)
        self.assertIn("deploy skipped", trace)
        self.assertIn("payment bands were not resolved", trace)
        self.assertIn("no supported outcome mapping was resolved", trace)
        self.assertNotIn("freya workflow_id", trace)


class PublicBaselineTests(unittest.TestCase):
    def test_public_briefs_compile_to_the_protected_workflows(self):
        import hashlib
        policy_a, built_a, errors_a = build([BRIEF_A], SPEC)
        policy_b, built_b, errors_b = build([BRIEF_A, BRIEF_B], SPEC)
        again_a = build([BRIEF_A], SPEC)[1]
        again_b = build([BRIEF_A, BRIEF_B], SPEC)[1]
        disk_a = (KIT / "out" / "brief-a.workflow.json").read_bytes()
        disk_b = (KIT / "out" / "brief-b.workflow.json").read_bytes()
        self.assertEqual(errors_a, [])
        self.assertEqual(errors_b, [])
        self.assertEqual(built_a, again_a)
        self.assertEqual(built_b, again_b)
        self.assertEqual(built_a, json.loads(disk_a.decode("utf-8")))
        self.assertEqual(built_b, json.loads(disk_b.decode("utf-8")))
        self.assertEqual(hashlib.sha256(disk_a).hexdigest(), HASH_A)
        self.assertEqual(hashlib.sha256(disk_b).hexdigest(), HASH_B)
        self.assertEqual(set(built_a["nodes"]), NODES_A)
        self.assertEqual(set(built_b["nodes"]), NODES_B)
        self.assertEqual(built_a["initial_node"], "boot")
        self.assertEqual(built_b["initial_node"], "boot")
        self.assertEqual(policy_a["blob"]["notes"], "no")
        self.assertEqual(policy_b["blob"]["notes"], "yes")
        self.assertEqual(policy_a["blob"]["multi"], "no")
        self.assertEqual(policy_b["blob"]["multi"], "yes")
        self.assertEqual(policy_a["bands"], policy_b["bands"])
        self.assertEqual(policy_a["outcomes"], policy_b["outcomes"])
        vars = {"now": NOW, "policy_json": json.dumps(policy_a["blob"]), "title": "Ms", "last_name": "Costa"}
        begin(vars)
        self.assertEqual(vars["disclosure"], DISCLOSURE)
        self.assertNotIn("recorded", built_a["system_prompt"].lower())
        self.assertIn("promise tool succeeded", built_a["system_prompt"])

    def test_cli_compile_writes_only_under_a_temp_kit(self):
        before_a = (KIT / "out" / "brief-a.workflow.json").read_bytes()
        before_b = (KIT / "out" / "brief-b.workflow.json").read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.cli.KIT", root):
                code_a = main([str(BRIEF_A), "--openapi", str(SPEC), "--out", str(root / "a.json")])
                code_b = main(
                    [str(BRIEF_A), str(BRIEF_B), "--openapi", str(SPEC), "--out", str(root / "b.json")],
                )
            trace = next((root / "traces").glob("*brief-a*")).read_text(encoding="utf-8")
            built = json.loads((root / "a.json").read_text(encoding="utf-8"))
        self.assertEqual(code_a, 0)
        self.assertEqual(code_b, 0)
        self.assertIn("model none", trace)
        self.assertIn("validation ok", trace)
        self.assertNotIn("freya ", trace)
        self.assertEqual(built, json.loads(before_a.decode("utf-8")))
        self.assertEqual((KIT / "out" / "brief-a.workflow.json").read_bytes(), before_a)
        self.assertEqual((KIT / "out" / "brief-b.workflow.json").read_bytes(), before_b)
