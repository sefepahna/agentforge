"""Single-command builder: brief path in, workflow file out."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from agentforge.case_run import USAGE_EXIT, run_case_folder
from agentforge.parser import load_openapi, parse_briefs, unresolved_configuration
from agentforge.validate import validate_workflow
from agentforge.workflow_builder import build_workflow

KIT = Path(__file__).resolve().parents[1]


def _letter(path, explicit):
    if explicit:
        return explicit.upper()
    name = Path(path).stem.lower()
    if name.endswith("b") or name.endswith("-b"):
        return "B"
    if name.endswith("a") or name.endswith("-a"):
        return "A"
    return ""


def build(brief_paths, openapi_path):
    spec = load_openapi(openapi_path)
    policy = parse_briefs(brief_paths, spec)
    workflow = build_workflow(policy, spec)
    errors = validate_workflow(workflow, policy.get("server") or "")
    unsupported = policy.get("unsupported_outcomes") or []
    if unsupported:
        errors.append("unsupported outcomes are not implemented: " + ", ".join(unsupported))
    errors.extend(unresolved_configuration(policy))
    errors.extend(policy.get("deploy_diagnostics") or [])
    return policy, workflow, errors


def _case_folder_main(args):
    if len(args.briefs) != 2:
        print(
            "case folder invocation is: python -m agentforge <case_folder> <mock_url>",
            file=sys.stderr,
        )
        return USAGE_EXIT
    return run_case_folder(
        args.briefs[0],
        args.briefs[1],
        KIT,
        deploy_requested=bool(args.deploy),
        test_requested=bool(args.test),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a Freya phone agent from a brief.")
    parser.add_argument(
        "briefs",
        nargs="+",
        help="Brief files, in order. Or a case folder and an http(s) mock URL.",
    )
    parser.add_argument("--openapi", default=str(KIT / "tools" / "openapi.json"))
    parser.add_argument("--out", default="")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--brief", default="", help="Practice brief letter for run_cases.py, A or B.")
    args = parser.parse_args(argv)
    if Path(args.briefs[0]).is_dir():
        return _case_folder_main(args)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    slot = Path(args.briefs[-1]).stem
    out_dir = KIT / "out"
    out_dir.mkdir(exist_ok=True)
    workflow_path = Path(args.out) if args.out else out_dir / (slot + ".workflow.json")
    checklist_path = out_dir / (slot + ".checklist.json")
    trace_dir = KIT / "traces"
    trace_dir.mkdir(exist_ok=True)
    trace_path = trace_dir / ("agentforge-" + time.strftime("%Y%m%d-%H%M%S") + "-" + slot + ".txt")
    policy, workflow, errors = build(args.briefs, args.openapi)
    checklist = {
        "sources": policy["sources"],
        "bank": policy["bank"],
        "holidays": policy["holidays"],
        "bands": policy["bands"],
        "notes": policy["blob"]["notes"],
        "multi": policy["blob"]["multi"],
        "identity_fields": policy["blob"]["id_fields"],
        "outcomes": policy["outcomes"],
        "unsupported_outcomes": policy.get("unsupported_outcomes") or [],
        "rules": policy["rules"],
    }
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(json.dumps(workflow, indent=1), encoding="utf-8")
    checklist_path.write_text(json.dumps(checklist, indent=1), encoding="utf-8")
    lines = [
        "start " + started,
        "model none",
        "purpose compile brief into a Freya workflow with deterministic policy code",
        "briefs " + " ".join(args.briefs),
        "checklist " + str(checklist_path),
        "workflow " + str(workflow_path),
        "validation " + ("ok" if not errors else "failed"),
    ]
    for error in errors:
        lines.append("error " + error)
    deployed = ""
    if errors:
        lines.append("deploy skipped")
    elif args.deploy:
        if not os.environ.get("FREYA_API_KEY"):
            lines.append("deploy blocked: FREYA_API_KEY is not set")
        else:
            sys.path.insert(0, str(KIT))
            import freya
            saved = freya.save_workflow(slot, workflow)
            deployed = saved.get("agent_id") or ""
            lines.append("freya workflow_id " + str(saved.get("workflow_id") or ""))
            lines.append("freya agent_id " + deployed)
            lines.append("purpose save_workflow update-or-create and publish")
    if args.test:
        if not deployed:
            lines.append("test blocked: deploy a workflow first, or pass an agent that was just saved")
        elif not os.environ.get("FREYA_BANK_TEAM_KEY"):
            lines.append("test blocked: FREYA_BANK_TEAM_KEY is not set")
        else:
            letter = _letter(args.briefs[-1], args.brief)
            command = [sys.executable, str(KIT / "tools" / "run_cases.py"), deployed]
            if letter:
                command.extend(["--brief", letter])
            lines.append("purpose run official practice cases")
            lines.append("command " + " ".join(command))
            proc = subprocess.run(command, cwd=str(KIT))
            lines.append("test_exit " + str(proc.returncode))
    lines.append("end " + time.strftime("%Y-%m-%dT%H:%M:%S"))
    trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("workflow " + str(workflow_path))
    print("checklist " + str(checklist_path))
    print("trace " + str(trace_path))
    print("validation " + ("ok" if not errors else "failed: " + "; ".join(errors)))
    if not args.deploy:
        print("Freya was not called. Set FREYA_API_KEY and FREYA_BANK_TEAM_KEY, then re-run with --deploy --test.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
