"""Export helper for the final workflow. Importing this module does not call Freya.

Documented command, from the project root, after a final workflow id exists:

    python -c "import freya; freya.export_workflow(WORKFLOW_ID, 'submission/final.workflow.json')"

`export_invocation` returns that command. `export_final_workflow` performs the call.
Case-folder ingestion does not call either.
"""
import json
from pathlib import Path

SUBMISSION_DIR = "submission"
FINAL_WORKFLOW_NAME = "final.workflow.json"
FINAL_WORKFLOW_RELATIVE = SUBMISSION_DIR + "/" + FINAL_WORKFLOW_NAME
REJECTED_WORKFLOW_IDS = frozenset({"", "none", "null", "unavailable"})


def final_export_path(kit, destination=None):
    raw = Path(destination) if destination else Path(FINAL_WORKFLOW_RELATIVE)
    if raw.is_absolute():
        return raw
    return Path(kit) / raw


def export_invocation(workflow_id, destination=FINAL_WORKFLOW_RELATIVE):
    """Return a copy-pastable command. Does not call Freya."""
    _require_workflow_id(workflow_id)
    script = "import freya; freya.export_workflow(%r, %r)" % (str(workflow_id), str(destination))
    return "python -c " + json.dumps(script)


def export_final_workflow(workflow_id, kit, destination=None):
    """Call freya.export_workflow. Live API. Not used by case ingestion."""
    _require_workflow_id(workflow_id)
    target = final_export_path(kit, destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    import freya
    return freya.export_workflow(str(workflow_id), str(target))


def _require_workflow_id(workflow_id):
    if not isinstance(workflow_id, str) or workflow_id.strip().lower() in REJECTED_WORKFLOW_IDS:
        raise ValueError("workflow_id is required")
