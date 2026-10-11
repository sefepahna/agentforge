"""Plain-text trace for a final case-folder run. No secrets are written."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

UTF8 = "utf-8"
GIT_TIMEOUT_SECONDS = 5
MIN_SECRET_LENGTH = 8
REDACTED = "[redacted]"
MODEL_CALLS_NONE = "none"
API_NODE = "api_request"
SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
UNAVAILABLE = "unavailable"


class FinalBuildRecord:
    """Facts stored when a Freya build actually runs."""

    def __init__(self, workflow_id, agent_id, node_count, tool_count, validation, local_test):
        self.workflow_id = str(workflow_id)
        self.agent_id = str(agent_id)
        self.node_count = int(node_count)
        self.tool_count = int(tool_count)
        self.validation = str(validation)
        self.local_test = str(local_test)


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_builder_version(root):
    path = Path(root) / "VERSION"
    try:
        text = path.read_text(encoding=UTF8).strip()
    except OSError:
        return UNAVAILABLE
    return text or UNAVAILABLE


def read_git_commit(root):
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return UNAVAILABLE
    if proc.returncode != 0:
        return UNAVAILABLE
    commit = proc.stdout.strip()
    if len(commit) < 7:
        return UNAVAILABLE
    return commit


def configured_secrets(environ=None):
    source = os.environ if environ is None else environ
    found = []
    for name, value in source.items():
        if not value or len(value) < MIN_SECRET_LENGTH:
            continue
        upper = name.upper()
        if any(marker in upper for marker in SECRET_NAME_MARKERS):
            found.append(value)
    found.sort(key=len, reverse=True)
    return found


def redact_secrets(text, secrets=None):
    values = configured_secrets() if secrets is None else sorted(secrets, key=len, reverse=True)
    redacted = text
    for value in values:
        if value:
            redacted = redacted.replace(value, REDACTED)
    return redacted


def summarize_workflow(workflow):
    """Return (node count, api_request tool count) for a workflow dict."""
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    if not isinstance(nodes, dict):
        return 0, 0
    tools = 0
    for node in nodes.values():
        if isinstance(node, dict) and node.get("node_type") == API_NODE:
            tools += 1
    return len(nodes), tools


def render_final_trace(
    started,
    finished,
    version,
    commit,
    case_folder,
    mock_url,
    files,
    evidence_file,
    build=None,
    model_calls=MODEL_CALLS_NONE,
):
    """Return the trace body. Caller redacts secrets before writing or printing."""
    lines = [
        _field("run_start_utc", started),
        _field("run_end_utc", finished),
        _field("builder_version", version),
        _field("git_commit", commit),
        _field("case_folder", case_folder),
        _field("mock_url", mock_url),
        _field("evidence_file", evidence_file),
        _field("builder_model_calls", model_calls),
        _field("evidence_count", len(files)),
        "evidence_inventory:",
    ]
    for item in files:
        lines.append(
            "evidence "
            + _pair("path", item["path"])
            + " "
            + _pair("type", item["type"])
            + " "
            + _pair("status", item["status"])
            + " warnings="
            + str(len(item["warnings"]))
        )
        for warning in item["warnings"]:
            lines.append("evidence_warning " + _pair("path", item["path"]) + " " + _one_line(warning))
    if build is None:
        lines.extend([
            _field("workflow_id", "none"),
            _field("agent_id", "none"),
            _field("workflow_node_count", "none"),
            _field("tool_count", "none"),
            _field("validation", "not_run"),
            _field("local_test", "none"),
        ])
    else:
        lines.extend([
            _field("workflow_id", build.workflow_id),
            _field("agent_id", build.agent_id),
            _field("workflow_node_count", build.node_count),
            _field("tool_count", build.tool_count),
            _field("validation", build.validation),
            _field("local_test", build.local_test),
        ])
    return "\n".join(lines) + "\n"


def _field(label, value):
    return label + ": " + _one_line(value)


def _pair(key, value):
    return key + "=" + json.dumps(_one_line(value), ensure_ascii=False)


def _one_line(value):
    return str(value).replace("\r", " ").replace("\n", " ")
