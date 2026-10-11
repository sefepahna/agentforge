"""Fail closed when a brief names an identity field the runtime cannot ask or parse.

No Freya calls. Public DOB and phone-last-four briefs must stay deployable.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agentforge.cli import build, main
from agentforge.parser import IDENTITY_UNSUPPORTED, SUPPORTED_ID_FIELDS
from agentforge.runtime_body import begin, field_prompt
from agentforge.tests.synthetic_eval import FIXTURES, IDENTITY_LINE, SPEC, base_text
from agentforge.tests.test_regression_harness import (
    BRIEF_A, BRIEF_B, DISCLOSURE, HASH_A, HASH_B, NODES_A, NODES_B, NOW,
)

ROOT = Path(__file__).resolve().parents[2]
POSTCODE_ERROR = IDENTITY_UNSUPPORTED + ": postcode"


def _identity_errors(errors):
    prefix = IDENTITY_UNSUPPORTED + ": "
    return [item[len(prefix):] for item in errors if item.startswith(prefix)]


def _compile_text(text):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "mixed.md"
        path.write_text(text, encoding="utf-8")
        return build([path], SPEC)


class UnsupportedIdentityTests(unittest.TestCase):
    def test_runtime_prompts_only_dob_and_phone(self):
        dob = field_prompt({"id_fields": ["date_of_birth"]}, 0)
        phone = field_prompt({"id_fields": ["phone_last4"]}, 0)
        postcode = field_prompt({"id_fields": ["postcode"]}, 0)
        self.assertEqual(SUPPORTED_ID_FIELDS, ("date_of_birth", "phone_last4"))
        self.assertEqual(dob, "Please tell me your date of birth.")
        self.assertIn("four digits", phone)
        self.assertNotEqual(dob, phone)
        self.assertEqual(postcode, dob)

    def test_postcode_brief_is_not_a_valid_dob_workflow(self):
        policy, workflow, errors = build([FIXTURES / "syn07_postcode.md"], SPEC)
        again = build([FIXTURES / "syn07_postcode.md"], SPEC)
        self.assertEqual(errors, [POSTCODE_ERROR])
        self.assertEqual(again[2], errors)
        self.assertEqual(policy["id_requests"], ["postcode"])
        self.assertEqual(_identity_errors(errors), ["postcode"])
        self.assertNotEqual(errors, [])
        self.assertIn("postcode", policy["rules"][1]["text"])
        self.assertEqual(workflow["initial_node"], "boot")
        self.assertEqual(set(workflow["nodes"]), NODES_A)

    def test_postcode_deploy_is_blocked(self):
        fake = types.ModuleType("freya")

        def save_workflow(*_args, **_kwargs):
            raise AssertionError("deploy should not run")

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.cli.KIT", root):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([
                            str(FIXTURES / "syn07_postcode.md"),
                            "--openapi", str(SPEC),
                            "--deploy",
                        ])
            trace = next((root / "traces").glob("*.txt")).read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("deploy skipped", trace)
        self.assertIn(POSTCODE_ERROR, trace)
        self.assertNotIn("freya workflow_id", trace)

    def test_dob_plus_postcode_is_still_rejected(self):
        mixed = (
            "2. Ask for the date of birth, then the customer postcode. "
            "Three wrong answers in total end the check."
        )
        policy, _workflow, errors = _compile_text(base_text().replace(IDENTITY_LINE, mixed))
        self.assertEqual(policy["id_requests"], ["date_of_birth", "postcode"])
        self.assertEqual(_identity_errors(errors), ["postcode"])
        self.assertNotEqual(errors, [])

    def test_public_dob_and_phone_stay_deployable(self):
        import hashlib
        policy_a, built_a, errors_a = build([BRIEF_A], SPEC)
        policy_b, built_b, errors_b = build([BRIEF_A, BRIEF_B], SPEC)
        disk_a = (ROOT / "out" / "brief-a.workflow.json").read_bytes()
        disk_b = (ROOT / "out" / "brief-b.workflow.json").read_bytes()
        self.assertEqual(errors_a, [])
        self.assertEqual(errors_b, [])
        self.assertEqual(_identity_errors(errors_a), [])
        self.assertEqual(_identity_errors(errors_b), [])
        self.assertEqual(policy_a["id_requests"], ["date_of_birth", "phone_last4"])
        self.assertEqual(policy_b["id_requests"], ["date_of_birth", "phone_last4"])
        self.assertEqual(policy_a["blob"]["id_fields"], ["date_of_birth", "phone_last4"])
        self.assertEqual(policy_b["blob"]["id_fields"], ["date_of_birth", "phone_last4"])
        self.assertEqual(set(built_a["nodes"]), NODES_A)
        self.assertEqual(set(built_b["nodes"]), NODES_B)
        self.assertEqual(built_a["initial_node"], "boot")
        self.assertEqual(built_b["initial_node"], "boot")
        self.assertEqual(built_a, json.loads(disk_a.decode("utf-8")))
        self.assertEqual(built_b, json.loads(disk_b.decode("utf-8")))
        self.assertEqual(hashlib.sha256(disk_a).hexdigest(), HASH_A)
        self.assertEqual(hashlib.sha256(disk_b).hexdigest(), HASH_B)
        variables = {
            "now": NOW,
            "policy_json": json.dumps(policy_a["blob"]),
            "title": "Ms",
            "last_name": "Costa",
        }
        begin(variables)
        self.assertEqual(variables["disclosure"], DISCLOSURE)
        self.assertIn("We are recording this call.", variables["disclosure"])


if __name__ == "__main__":
    unittest.main()
