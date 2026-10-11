"""Fail closed when one brief states two different calling-hour ranges.

No Freya calls. One range, an exact repeat, and a later file stay deployable.
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agentforge.cli import build, main
from agentforge.parser import CALLING_HOURS_AMBIGUOUS
from agentforge.tests.synthetic_eval import (
    CALLBACK_LINE, CONFLICTING_CALLBACK, FIXTURES, SPEC, base_text,
)
from agentforge.tests.test_regression_harness import BRIEF_A, BRIEF_B, NODES_A, NODES_B

SYN08 = FIXTURES / "syn08_window_conflict.md"
WINDOW_ERROR = CALLING_HOURS_AMBIGUOUS + ": 09:15-16:45, 08:00-12:00"


def _compile_text(text, name="hours.md"):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return build([str(path)], str(SPEC))


def _compile_files(paths):
    return build([str(path) for path in paths], str(SPEC))


class CallingHoursGateTests(unittest.TestCase):
    def test_syn08a_distinct_ranges_are_rejected(self):
        _policy, _workflow, errors = _compile_files([SYN08])
        again = _compile_files([SYN08])[2]
        self.assertEqual(errors, [WINDOW_ERROR])
        self.assertEqual(again, errors)
        self.assertIn("08:00 to 12:00", SYN08.read_text(encoding="utf-8"))

    def test_syn08a_keeps_the_first_window_and_blocks_deploy(self):
        policy, _workflow, errors = _compile_files([SYN08])
        self.assertEqual(policy["blob"]["callback_start"], "09:15")
        self.assertEqual(policy["blob"]["callback_end"], "16:45")
        self.assertIn(WINDOW_ERROR, policy["deploy_diagnostics"])
        fake = types.ModuleType("freya")

        def save_workflow(*_args, **_kwargs):
            raise AssertionError("deploy should not run")

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.cli.KIT", root):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([str(SYN08), "--openapi", str(SPEC), "--deploy"])
            trace = next((root / "traces").glob("*.txt")).read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertEqual(errors, [WINDOW_ERROR])
        self.assertIn("deploy skipped", trace)
        self.assertIn(WINDOW_ERROR, trace)
        self.assertNotIn("freya workflow_id", trace)

    def test_single_supported_range_stays_deployable(self):
        policy, _workflow, errors = _compile_files([FIXTURES / "syn01_structured.md"])
        self.assertEqual(errors, [])
        self.assertEqual(policy["blob"]["callback_start"], "09:15")
        self.assertEqual(policy["blob"]["callback_end"], "16:45")
        self.assertEqual(policy["deploy_diagnostics"], [])

    def test_missing_range_keeps_the_default_window(self):
        text = base_text().replace(CALLBACK_LINE, "4. A callback is for today or the next business day.")
        policy, _workflow, errors = _compile_text(text, "no-window.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["blob"]["callback_start"], "10:00")
        self.assertEqual(policy["blob"]["callback_end"], "19:00")

    def test_identical_duplicate_range_stays_deployable(self):
        extra = "\nThe same callback window runs from 09:15 to 16:45.\n"
        policy, _workflow, errors = _compile_text(base_text() + extra, "duplicate.md")
        again = _compile_text(base_text() + extra, "duplicate.md")[2]
        self.assertEqual(errors, [])
        self.assertEqual(again, errors)
        self.assertEqual(policy["blob"]["callback_start"], "09:15")
        self.assertEqual(policy["blob"]["callback_end"], "16:45")

    def test_cross_file_override_is_not_same_file_ambiguity(self):
        later = "The callback window runs from 08:00 to 12:00.\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "later-window.md"
            path.write_text(later, encoding="utf-8")
            forward, _forward_workflow, forward_errors = _compile_files([
                FIXTURES / "syn01_structured.md", path,
            ])
            reverse, _reverse_workflow, reverse_errors = _compile_files([
                path, FIXTURES / "syn01_structured.md",
            ])
        self.assertEqual(forward_errors, [])
        self.assertEqual(reverse_errors, [])
        self.assertEqual(forward["deploy_diagnostics"], [])
        self.assertEqual(reverse["deploy_diagnostics"], [])
        self.assertEqual(forward["blob"]["callback_start"], "08:00")
        self.assertEqual(forward["blob"]["callback_end"], "12:00")
        self.assertEqual(reverse["blob"]["callback_start"], "09:15")
        self.assertEqual(reverse["blob"]["callback_end"], "16:45")

    def test_unrelated_times_are_not_a_second_window(self):
        extra = (
            "\nThe customer may ask for an appointment at 15:30. "
            "The branch is open between 10:00 and 19:00. "
            "Visitors walk from the lobby to the desk. "
            "Office hours are 09:00-17:00.\n"
        )
        policy, _workflow, errors = _compile_text(base_text() + extra, "prose-times.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["blob"]["callback_start"], "09:15")
        self.assertEqual(policy["blob"]["callback_end"], "16:45")

    def test_example_and_fenced_range_does_not_count(self):
        example = (
            "\nExample only\n"
            "A sample note sets the window from 08:00 to 12:00.\n"
            "```\n"
            "from 07:00 to 11:00\n"
            "```\n"
        )
        policy, _workflow, errors = _compile_text(base_text() + example, "example-hours.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["blob"]["callback_start"], "09:15")
        self.assertEqual(policy["blob"]["callback_end"], "16:45")

    def test_policy_fence_with_a_second_range_is_rejected(self):
        fenced = "\n```\nfrom 08:00 to 12:00\n```\n"
        _policy, _workflow, errors = _compile_text(base_text() + fenced, "fenced-hours.md")
        self.assertEqual(errors, [WINDOW_ERROR])

    def test_unpadded_clock_is_a_distinct_range(self):
        text = base_text().replace(
            CALLBACK_LINE,
            CALLBACK_LINE + " A note also says from 9:15 to 16:45.",
        )
        _policy, _workflow, errors = _compile_text(text, "unpadded.md")
        self.assertEqual(errors, [CALLING_HOURS_AMBIGUOUS + ": 09:15-16:45, 9:15-16:45"])

    def test_public_briefs_keep_their_calling_hours(self):
        policy_a, built_a, errors_a = build([str(BRIEF_A)], str(SPEC))
        policy_b, built_b, errors_b = build([str(BRIEF_A), str(BRIEF_B)], str(SPEC))
        self.assertEqual(errors_a, [])
        self.assertEqual(errors_b, [])
        self.assertEqual(policy_a["blob"]["callback_start"], "10:00")
        self.assertEqual(policy_a["blob"]["callback_end"], "19:00")
        self.assertEqual(policy_b["blob"]["callback_start"], "10:00")
        self.assertEqual(policy_b["blob"]["callback_end"], "19:00")
        self.assertEqual(set(built_a["nodes"]), NODES_A)
        self.assertEqual(set(built_b["nodes"]), NODES_B)
        self.assertEqual(built_a["initial_node"], "boot")
        self.assertEqual(built_b["initial_node"], "boot")
        self.assertIn("09:15 to 16:45", CALLBACK_LINE)
        self.assertIn("08:00 to 12:00", CONFLICTING_CALLBACK)


if __name__ == "__main__":
    unittest.main()
