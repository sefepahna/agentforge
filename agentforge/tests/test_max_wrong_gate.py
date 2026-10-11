"""Fail closed when a brief requests a wrong-answer limit other than 3.

No Freya calls. The runtime counter stays at three. Missing text keeps that default.
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agentforge.cli import build, main
from agentforge.parser import MAX_WRONG_UNSUPPORTED, SUPPORTED_MAX_WRONG
from agentforge.tests.synthetic_eval import FIXTURES, SPEC, base_text, local_misses
from agentforge.tests.test_regression_harness import BRIEF_A, BRIEF_B, NODES_A, NODES_B

SYN05 = FIXTURES / "syn05_two_wrong.md"
TWO_ERROR = MAX_WRONG_UNSUPPORTED + ": 2"
ZERO_ERROR = MAX_WRONG_UNSUPPORTED + ": 0"
FOUR_ERROR = MAX_WRONG_UNSUPPORTED + ": 4"
THREE_LINE = "Three wrong answers in total end the check."


def _compile_text(text, name="wrong.md"):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return build([str(path)], str(SPEC))


def _compile_files(paths):
    return build([str(path) for path in paths], str(SPEC))


class MaxWrongGateTests(unittest.TestCase):
    def test_syn05_two_wrong_answers_are_rejected(self):
        policy, _workflow, errors = _compile_files([SYN05])
        again = _compile_files([SYN05])[2]
        self.assertEqual(errors, [TWO_ERROR])
        self.assertEqual(again, errors)
        self.assertEqual(policy["max_wrong"], 2)
        self.assertNotIn("max_wrong", policy["blob"])
        self.assertEqual(SUPPORTED_MAX_WRONG, 3)

    def test_syn05_deploy_is_blocked_and_runtime_still_closes_at_three(self):
        policy, _workflow, _errors = _compile_files([SYN05])
        misses = local_misses(policy, 3)
        self.assertEqual(misses[2]["route"], "close")
        self.assertEqual(misses[2]["id_miss"], "3")
        fake = types.ModuleType("freya")

        def save_workflow(*_args, **_kwargs):
            raise AssertionError("deploy should not run")

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.cli.KIT", root):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([str(SYN05), "--openapi", str(SPEC), "--deploy"])
            trace = next((root / "traces").glob("*.txt")).read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("deploy skipped", trace)
        self.assertIn(TWO_ERROR, trace)
        self.assertNotIn("freya workflow_id", trace)

    def test_explicit_three_stays_deployable(self):
        policy, _workflow, errors = _compile_files([FIXTURES / "syn01_structured.md"])
        self.assertEqual(errors, [])
        self.assertEqual(policy["max_wrong"], 3)
        self.assertNotIn("max_wrong", policy["blob"])

    def test_missing_limit_keeps_the_default(self):
        text = base_text().replace(" " + THREE_LINE, "")
        policy, _workflow, errors = _compile_text(text, "missing-limit.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["max_wrong"], 3)

    def test_explicit_zero_is_rejected(self):
        text = base_text().replace(THREE_LINE, "0 wrong answers in total end the check.")
        policy, _workflow, errors = _compile_text(text, "zero-limit.md")
        again = _compile_text(text, "zero-limit.md")[2]
        self.assertEqual(policy["max_wrong"], 0)
        self.assertEqual(errors, [ZERO_ERROR])
        self.assertEqual(again, errors)
        self.assertNotIn("max_wrong", policy["blob"])

    def test_one_line_zero_is_not_rewritten_to_three(self):
        policy, _workflow, errors = _compile_text("0 wrong answers end the check.\n", "zero-only.md")
        self.assertEqual(policy["max_wrong"], 0)
        self.assertIn(ZERO_ERROR, errors)

    def test_four_wrong_answers_are_rejected(self):
        text = base_text().replace(THREE_LINE, "4 wrong answers in total end the check.")
        policy, _workflow, errors = _compile_text(text, "four-limit.md")
        again = _compile_text(text, "four-limit.md")[2]
        self.assertEqual(policy["max_wrong"], 4)
        self.assertEqual(errors, [FOUR_ERROR])
        self.assertEqual(again, errors)

    def test_later_file_overrides_the_limit(self):
        two = "Two wrong answers end the check.\n"
        three = "Three wrong answers end the check.\n"
        zero = "0 wrong answers end the check.\n"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            two_path = root / "two.md"
            three_path = root / "three.md"
            zero_path = root / "zero.md"
            two_path.write_text(two, encoding="utf-8")
            three_path.write_text(three, encoding="utf-8")
            zero_path.write_text(zero, encoding="utf-8")
            base = FIXTURES / "syn01_structured.md"
            restored, _workflow, restored_errors = _compile_files([two_path, base])
            replaced, _replaced_workflow, replaced_errors = _compile_files([base, two_path])
            zeroed, _zero_workflow, zero_errors = _compile_files([base, zero_path])
            cleared, _cleared_workflow, cleared_errors = _compile_files([zero_path, three_path, base])
        self.assertEqual(restored["max_wrong"], 3)
        self.assertEqual(restored_errors, [])
        self.assertEqual(replaced["max_wrong"], 2)
        self.assertEqual(replaced_errors, [TWO_ERROR])
        self.assertEqual(zeroed["max_wrong"], 0)
        self.assertEqual(zero_errors, [ZERO_ERROR])
        self.assertEqual(cleared["max_wrong"], 3)
        self.assertEqual(cleared_errors, [])

    def test_unparsed_word_is_not_a_new_limit(self):
        text = base_text().replace(THREE_LINE, "six wrong answers in total end the check.")
        policy, _workflow, errors = _compile_text(text, "six-limit.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["max_wrong"], 3)

    def test_public_briefs_keep_three(self):
        policy_a, built_a, errors_a = build([str(BRIEF_A)], str(SPEC))
        policy_b, built_b, errors_b = build([str(BRIEF_A), str(BRIEF_B)], str(SPEC))
        self.assertEqual(errors_a, [])
        self.assertEqual(errors_b, [])
        self.assertEqual(policy_a["max_wrong"], 3)
        self.assertEqual(policy_b["max_wrong"], 3)
        self.assertNotIn("max_wrong", policy_a["blob"])
        self.assertNotIn("max_wrong", policy_b["blob"])
        self.assertEqual(set(built_a["nodes"]), NODES_A)
        self.assertEqual(set(built_b["nodes"]), NODES_B)
        self.assertEqual(built_a["initial_node"], "boot")
        self.assertEqual(built_b["initial_node"], "boot")


if __name__ == "__main__":
    unittest.main()
