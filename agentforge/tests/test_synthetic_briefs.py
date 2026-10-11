"""Diagnostic synthetic briefs. Failures here are evidence, not production defects to patch.

No Freya calls. No writes under the tracked out/ directory. A SAFE_REJECT is not a PASS.
"""
import hashlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agentforge.cli import main
from agentforge.parser import (
    BAND_UNRESOLVED, CALLING_HOURS_AMBIGUOUS, IDENTITY_UNSUPPORTED, MAX_WRONG_UNSUPPORTED,
    OUTCOME_UNRESOLVED,
)
from agentforge.prose_extract import FLOOR_UNBOUND, OUTCOME_REJECTED, WITHDRAWAL_UNAPPLIED
from agentforge.tests.synthetic_eval import (
    CALLBACK_LINE,
    CONFLICTING_CALLBACK,
    DISCLOSURE,
    EXPECTED_BANDS,
    EXPECTED_FLOORS,
    EXPECTED_OUTCOMES,
    FIXTURES,
    SPEC,
    base_text,
    executable,
    labeled_case,
    natural_floor_case,
    outcome_conflict_case,
    postcode_case,
    product_cap_case,
    prose_band_text,
    structured_case,
    variant_texts,
    window_conflict_case,
    withdrawal_case,
    wrong_limit_case,
    zero_wrong_merge,
    compile_paths,
)
from agentforge.tests.test_regression_harness import HASH_A, HASH_B, NODES_A

PUBLIC_A = Path(__file__).resolve().parents[2] / "out" / "brief-a.workflow.json"
PUBLIC_B = Path(__file__).resolve().parents[2] / "out" / "brief-b.workflow.json"


def _rules(policy):
    return [rule["text"] for rule in policy["rules"]]


def _compile_text(text, name):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return compile_paths([path])


class SyntheticCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.structured = structured_case()

    def test_committed_variants_are_the_single_dimension_edits(self):
        expected = variant_texts(base_text())
        for name, text in expected.items():
            self.assertEqual((FIXTURES / name).read_text(encoding="utf-8"), text, name)

    def test_syn01_structured_markdown_binds_the_supported_policy(self):
        observed = self.structured
        signature = observed["signature"]
        self.assertEqual(observed["errors"], [])
        self.assertEqual(signature["bands"], EXPECTED_BANDS)
        self.assertEqual(signature["outcomes"], EXPECTED_OUTCOMES)
        self.assertEqual(signature["floors"], EXPECTED_FLOORS)
        self.assertEqual(signature["holidays"], ["2026-03-17", "2026-07-04"])
        self.assertEqual(signature["bank"], "Harbor Mutual")
        self.assertEqual(signature["sentence"], "A confirmation note will be posted to your account.")
        self.assertEqual(signature["sorry"], "I am sorry to hear that.")
        self.assertEqual(signature["forbidden"], ["collections", "overdue"])
        self.assertEqual(signature["callback_start"], "09:15")
        self.assertEqual(signature["callback_end"], "16:45")
        self.assertEqual(signature["id_fields"], ["date_of_birth", "phone_last4"])
        self.assertEqual(signature["notes"], "no")
        self.assertEqual(signature["multi"], "no")
        self.assertEqual(signature["max_products"], 1)
        self.assertEqual(signature["max_wrong"], 3)
        self.assertFalse(signature["max_products_in_blob"])
        self.assertFalse(signature["max_wrong_in_blob"])
        self.assertEqual(observed["floor"], 40)
        self.assertEqual(observed["disclosure"], DISCLOSURE)
        self.assertEqual(observed["initial"], "boot")
        self.assertEqual(set(observed["workflow"]["nodes"]), NODES_A)
        again = compile_paths([FIXTURES / "syn01_structured.md"])[1]
        self.assertEqual(observed["workflow"], again)

    def test_syn02_labeled_fields_are_rejected_rather_than_bound(self):
        observed = labeled_case()
        signature = observed["signature"]
        self.assertEqual(signature["holidays"], ["2026-03-17", "2026-07-04"])
        self.assertEqual(signature["bands"], [])
        self.assertEqual(signature["outcomes"], {})
        self.assertEqual(signature["floors"], [])
        self.assertEqual(signature["callback_start"], "10:00")
        self.assertEqual(signature["callback_end"], "19:00")
        self.assertEqual(signature["max_wrong"], 3)
        self.assertEqual(signature["max_products"], 1)
        self.assertEqual(observed["policy"]["id_fields"], [])
        self.assertEqual(signature["id_fields"], ["date_of_birth", "phone_last4"])
        self.assertEqual(signature["bank"], "the bank")
        self.assertIn(BAND_UNRESOLVED, observed["errors"])
        self.assertIn(OUTCOME_UNRESOLVED, observed["errors"])
        self.assertTrue(any(item.startswith(FLOOR_UNBOUND) for item in observed["errors"]))
        self.assertEqual(observed["node_count"], len(NODES_A))
        self.assertNotEqual(observed["errors"], [])

    def test_syn03_natural_language_floor_is_rejected(self):
        observed = natural_floor_case()
        floor_errors = [item for item in observed["errors"] if item.startswith(FLOOR_UNBOUND)]
        self.assertEqual(floor_errors, [FLOOR_UNBOUND + " (line 24: credit card, personal loan)"])
        self.assertEqual(observed["signature"]["floors"], [])
        self.assertEqual(observed["signature"]["bands"], EXPECTED_BANDS)
        self.assertNotEqual(observed["errors"], [])

    def test_syn04_withdrawal_blocks_deploy_and_keeps_the_old_bands(self):
        observed = withdrawal_case()
        self.assertEqual(observed["signature"]["bands"], EXPECTED_BANDS)
        self.assertEqual(observed["signature"]["floors"], EXPECTED_FLOORS)
        self.assertTrue(any(item.startswith(WITHDRAWAL_UNAPPLIED) for item in observed["errors"]))
        self.assertNotEqual(observed["errors"], [])

    def test_syn05_two_wrong_answers_are_rejected_and_runtime_still_closes_at_three(self):
        observed = wrong_limit_case()
        misses = observed["misses"]
        self.assertEqual(observed["errors"], [MAX_WRONG_UNSUPPORTED + ": 2"])
        self.assertEqual(observed["signature"]["max_wrong"], 2)
        self.assertFalse(observed["signature"]["max_wrong_in_blob"])
        self.assertEqual(misses[0]["route"], "speak")
        self.assertEqual(misses[0]["id_miss"], "1")
        self.assertIsNone(misses[0]["outcome"])
        self.assertEqual(misses[1]["route"], "speak")
        self.assertEqual(misses[1]["id_miss"], "2")
        self.assertIsNone(misses[1]["outcome"])
        self.assertEqual(misses[2]["route"], "close")
        self.assertEqual(misses[2]["outcome"], "not_verified")
        self.assertEqual(misses[2]["id_miss"], "3")
        zero = zero_wrong_merge()
        self.assertEqual(zero["parsed"], 0)
        self.assertEqual(zero["merged"], 0)
        self.assertFalse(zero["in_blob"])

    def test_syn06_four_product_cap_keeps_every_returned_product(self):
        observed = product_cap_case()
        self.assertEqual(observed["errors"], [])
        self.assertEqual(observed["signature"]["max_products"], 4)
        self.assertEqual(observed["signature"]["multi"], "yes")
        self.assertFalse(observed["signature"]["max_products_in_blob"])
        self.assertEqual(observed["kept_ids"], ["c1", "c2", "c3", "c4", "c5"])
        self.assertEqual(set(observed["workflow"]["nodes"]), NODES_A)

    def test_syn07_postcode_is_rejected_instead_of_accepted(self):
        observed = postcode_case()
        identity = [item for item in observed["errors"] if item.startswith(IDENTITY_UNSUPPORTED)]
        self.assertEqual(identity, [IDENTITY_UNSUPPORTED + ": postcode"])
        self.assertNotEqual(observed["errors"], [])
        self.assertEqual(observed["policy"]["id_requests"], ["postcode"])
        self.assertIn("postcode", observed["rule_text"])

    def test_syn08_distinct_callback_windows_are_rejected(self):
        observed = window_conflict_case()
        hours = CALLING_HOURS_AMBIGUOUS + ": 09:15-16:45, 08:00-12:00"
        self.assertEqual(observed["errors"], [hours])
        self.assertEqual(observed["signature"]["callback_start"], "09:15")
        self.assertEqual(observed["signature"]["callback_end"], "16:45")
        self.assertEqual(observed["signature"]["diagnostics"], [hours])
        self.assertIn("08:00 to 12:00", (FIXTURES / "syn08_window_conflict.md").read_text(encoding="utf-8"))

    def test_syn08_conflicting_outcome_prose_blocks_deployment(self):
        observed = outcome_conflict_case()
        self.assertEqual(observed["signature"]["outcomes"], {})
        self.assertEqual(observed["signature"]["bands"], EXPECTED_BANDS)
        self.assertIn(OUTCOME_UNRESOLVED, observed["errors"])
        self.assertTrue(any(item.startswith(OUTCOME_REJECTED) for item in observed["errors"]))


class MetamorphicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_policy = structured_case()["policy"]
        cls.base_signature = executable(cls.base_policy)

    def test_reordering_independent_sections_keeps_the_executable_policy(self):
        parts = base_text().split("\n## ")
        head, sections = parts[0], parts[1:]
        order = [0, 1, 2, 4, 3, 5, 6]
        reordered = head + "\n## " + "\n## ".join(sections[index] for index in order)
        policy, _workflow, errors = _compile_text(reordered, "reordered.md")
        self.assertEqual(errors, [])
        self.assertEqual(executable(policy), self.base_signature)
        self.assertEqual(set(_rules(policy)), set(_rules(self.base_policy)))
        self.assertNotEqual(_rules(policy), _rules(self.base_policy))

    def test_irrelevant_prose_does_not_change_the_executable_policy(self):
        noisy = base_text().replace(
            "## Opening\n\n",
            "## Opening\n\nThe lobby mural was painted in spring. Visitors may sit in the atrium.\n\n",
        )
        policy, _workflow, errors = _compile_text(noisy, "noisy.md")
        self.assertEqual(errors, [])
        self.assertEqual(executable(policy), self.base_signature)
        self.assertEqual(_rules(policy), _rules(self.base_policy))

    def test_heading_depth_and_blank_lines_keep_the_executable_policy(self):
        spaced = base_text().replace("## ", "### ").replace("\n\n", "\n\n\n")
        policy, _workflow, errors = _compile_text(spaced, "spaced.md")
        self.assertEqual(errors, [])
        self.assertEqual(executable(policy), self.base_signature)
        self.assertEqual(policy["bank"], "Harbor Mutual")

    def test_supported_prose_bands_match_the_markdown_table(self):
        self.assertEqual(
            (FIXTURES / "syn01_prose_bands.md").read_text(encoding="utf-8"),
            prose_band_text(base_text()),
        )
        policy, _workflow, errors = compile_paths([FIXTURES / "syn01_prose_bands.md"])
        self.assertEqual(errors, [])
        self.assertEqual(executable(policy), self.base_signature)
        self.assertEqual(_rules(policy), _rules(self.base_policy))

    def test_callback_file_order_is_not_semantic_equivalence(self):
        later = "The callback window runs from 08:00 to 12:00.\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "later-window.md"
            path.write_text(later, encoding="utf-8")
            forward, _workflow, forward_errors = compile_paths([
                FIXTURES / "syn01_structured.md", path,
            ])
            reverse, _reverse_workflow, reverse_errors = compile_paths([
                path, FIXTURES / "syn01_structured.md",
            ])
        self.assertEqual(forward_errors, [])
        self.assertEqual(reverse_errors, [])
        self.assertEqual(forward["blob"]["callback_start"], "08:00")
        self.assertEqual(forward["blob"]["callback_end"], "12:00")
        self.assertEqual(reverse["blob"]["callback_start"], "09:15")
        self.assertEqual(reverse["blob"]["callback_end"], "16:45")
        self.assertNotEqual(executable(forward), executable(reverse))
        self.assertIn("09:15 to 16:45", CALLBACK_LINE)
        self.assertIn("08:00 to 12:00", CONFLICTING_CALLBACK)


class SyntheticSafetyTests(unittest.TestCase):
    def _deploy(self, paths):
        fake = types.ModuleType("freya")
        calls = []

        def save_workflow(*_args, **_kwargs):
            calls.append(True)
            raise AssertionError("deploy should not run")

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.cli.KIT", root):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([str(path) for path in paths] + ["--openapi", str(SPEC), "--deploy"])
            trace = next((root / "traces").glob("*.txt")).read_text(encoding="utf-8")
        return code, trace, calls

    def test_rejected_synthetics_skip_deploy(self):
        cases = {
            "syn02": [FIXTURES / "syn02_key_value.md"],
            "syn05": [FIXTURES / "syn05_two_wrong.md"],
            "syn04": [FIXTURES / "syn01_structured.md", FIXTURES / "syn04_withdrawal.md"],
            "syn08-window": [FIXTURES / "syn08_window_conflict.md"],
            "syn08-outcome": [FIXTURES / "syn08_outcome_conflict.md"],
        }
        for name, paths in cases.items():
            with self.subTest(case=name):
                code, trace, calls = self._deploy(paths)
                self.assertEqual(code, 1)
                self.assertEqual(calls, [])
                self.assertIn("deploy skipped", trace)
                self.assertNotIn("freya workflow_id", trace)

    def test_supported_compile_writes_only_under_a_temp_kit(self):
        before_a = PUBLIC_A.read_bytes()
        before_b = PUBLIC_B.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.cli.KIT", root):
                code = main([
                    str(FIXTURES / "syn01_structured.md"),
                    "--openapi", str(SPEC),
                    "--out", str(root / "synthetic.json"),
                ])
            trace = next((root / "traces").glob("*.txt")).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn("model none", trace)
        self.assertIn("validation ok", trace)
        self.assertNotIn("freya workflow_id", trace)
        self.assertEqual(PUBLIC_A.read_bytes(), before_a)
        self.assertEqual(PUBLIC_B.read_bytes(), before_b)

    def test_public_workflow_bytes_stay_on_the_protected_hashes(self):
        self.assertEqual(hashlib.sha256(PUBLIC_A.read_bytes()).hexdigest(), HASH_A)
        self.assertEqual(hashlib.sha256(PUBLIC_B.read_bytes()).hexdigest(), HASH_B)


if __name__ == "__main__":
    unittest.main()
