"""Fail closed when a floor rule is stated but not bound to a product field.

No Freya calls. Supported backtick floors and ordinary prose must stay deployable.
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agentforge.cli import build, main
from agentforge.prose_extract import FLOOR_UNBOUND
from agentforge.tests.synthetic_eval import (
    EXPECTED_FLOORS, FIXTURES, FLOOR_LINE, SPEC, base_text,
)
from agentforge.tests.test_regression_harness import BRIEF_A, BRIEF_B, NODES_A, NODES_B

SYN03 = FIXTURES / "syn03_natural_floor.md"
SYN03_ERROR = FLOOR_UNBOUND + " (line 24: credit card, personal loan)"
AMBIGUOUS_ERROR = FLOOR_UNBOUND + " (line 24: unspecified product)"
PUBLIC_FLOORS = [
    "credit_card|minimum_payment",
    "personal_loan|instalment_amount",
    "car_loan|instalment_amount",
]


def _compile_text(text, name):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return build([path], SPEC)


class UnboundFloorTests(unittest.TestCase):
    def test_syn03_natural_floor_is_rejected(self):
        _policy, _workflow, errors = build([SYN03], SPEC)
        again = build([SYN03], SPEC)[2]
        self.assertEqual(errors, [SYN03_ERROR])
        self.assertEqual(again, errors)

    def test_syn03_deploy_is_blocked(self):
        fake = types.ModuleType("freya")

        def save_workflow(*_args, **_kwargs):
            raise AssertionError("deploy should not run")

        fake.save_workflow = save_workflow
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.cli.KIT", root):
                with patch.dict(sys.modules, {"freya": fake}):
                    with patch.dict(os.environ, {"FREYA_API_KEY": "fak_test_gate"}):
                        code = main([str(SYN03), "--openapi", str(SPEC), "--deploy"])
            trace = next((root / "traces").glob("*.txt")).read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("deploy skipped", trace)
        self.assertIn(SYN03_ERROR, trace)
        self.assertNotIn("freya workflow_id", trace)

    def test_supported_markdown_floor_stays_bound(self):
        policy, _workflow, errors = build([FIXTURES / "syn01_structured.md"], SPEC)
        self.assertEqual(errors, [])
        self.assertEqual(policy["floors"], EXPECTED_FLOORS)
        self.assertNotIn(FLOOR_UNBOUND, " ".join(errors))

    def test_supported_backtick_prose_floor_stays_bound(self):
        line = (
            "3. The floor is `minimum_payment` for a credit card and "
            "`instalment_amount` for a personal loan or a car loan."
        )
        policy, _workflow, errors = _compile_text(base_text().replace(FLOOR_LINE, line), "prose-floor.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["floors"], PUBLIC_FLOORS)

    def test_distant_minimum_payment_is_not_a_floor_rule(self):
        extra = (
            "\nPrices stay at or above the lobby poster from last spring, "
            "and the brochure later mentions the minimum payment date for visitors.\n"
        )
        policy, _workflow, errors = _compile_text(base_text() + extra, "distant.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["floors"], EXPECTED_FLOORS)

    def test_ground_floor_prose_is_not_a_payment_rule(self):
        extra = (
            "\nThe customer says the office is on the ground floor. "
            "The lobby has a minimum of chairs.\n"
        )
        policy, _workflow, errors = _compile_text(base_text() + extra, "ground.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["floors"], EXPECTED_FLOORS)

    def test_example_section_does_not_block_a_bound_floor(self):
        extra = (
            "\nExample only\n"
            "A credit card settlement must stay at or above the minimum payment.\n"
        )
        policy, _workflow, errors = _compile_text(base_text() + extra, "example-floor.md")
        self.assertEqual(errors, [])
        self.assertEqual(policy["floors"], EXPECTED_FLOORS)

    def test_unspecified_product_floor_is_rejected(self):
        line = "3. Recorded amounts must stay at or above the minimum payment."
        _policy, _workflow, errors = _compile_text(base_text().replace(FLOOR_LINE, line), "ambiguous.md")
        again = _compile_text(base_text().replace(FLOOR_LINE, line), "ambiguous.md")[2]
        self.assertEqual(errors, [AMBIGUOUS_ERROR])
        self.assertEqual(again, errors)

    def test_public_briefs_keep_their_floors(self):
        policy_a, built_a, errors_a = build([BRIEF_A], SPEC)
        policy_b, built_b, errors_b = build([BRIEF_A, BRIEF_B], SPEC)
        self.assertEqual(errors_a, [])
        self.assertEqual(errors_b, [])
        self.assertEqual(policy_a["floors"], PUBLIC_FLOORS)
        self.assertEqual(policy_b["floors"], PUBLIC_FLOORS)
        self.assertEqual(set(built_a["nodes"]), NODES_A)
        self.assertEqual(set(built_b["nodes"]), NODES_B)
        self.assertEqual(built_a["initial_node"], "boot")
        self.assertEqual(built_b["initial_node"], "boot")


if __name__ == "__main__":
    unittest.main()
