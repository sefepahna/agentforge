"""Case-folder command. Stops after evidence ingestion. Does not call Freya."""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from agentforge.case_ingest import ingest_case_folder
from agentforge.final_export import SUBMISSION_DIR
from agentforge.final_trace import (
    MODEL_CALLS_NONE,
    read_builder_version,
    read_git_commit,
    redact_secrets,
    render_final_trace,
    utc_stamp,
)

TRACE_DIR = "traces"
EVIDENCE_SUFFIX = ".evidence.json"
HTTP_SCHEMES = frozenset({"http", "https"})
EXIT_OK = 0
EXIT_ERROR = 1
USAGE_EXIT = 2
UTF8 = "utf-8"


def is_mock_url(value):
    parsed = urlparse(value)
    return parsed.scheme in HTTP_SCHEMES and bool(parsed.netloc)


def run_case_folder(folder, mock_url, kit, deploy_requested=False, test_requested=False):
    """Ingest a case folder and write a plain-text trace. Returns a process exit code."""
    if not is_mock_url(mock_url):
        _write_stderr("mock URL must be an http or https URL\n")
        return USAGE_EXIT
    root = Path(folder)
    if not root.is_dir():
        _write_stderr("case folder is not a directory\n")
        return USAGE_EXIT
    started = utc_stamp()
    try:
        evidence = ingest_case_folder(root)
    except OSError as exc:
        _write_stderr(redact_secrets("case folder read failed: " + str(exc) + "\n"))
        return EXIT_ERROR
    kit_path = Path(kit)
    trace_dir = kit_path / TRACE_DIR
    trace_dir.mkdir(parents=True, exist_ok=True)
    (kit_path / SUBMISSION_DIR).mkdir(parents=True, exist_ok=True)
    trace_path = _unique(trace_dir / (_stem(root.name, started) + ".txt"))
    evidence_path = trace_path.with_suffix(EVIDENCE_SUFFIX)
    finished = utc_stamp()
    lines = render_final_trace(
        started,
        finished,
        read_builder_version(kit_path),
        read_git_commit(kit_path),
        str(root.resolve()),
        mock_url,
        evidence["files"],
        str(evidence_path),
        build=None,
        model_calls=MODEL_CALLS_NONE,
    )
    if deploy_requested or test_requested:
        lines = lines.rstrip("\n") + "\ndeploy skipped: final case semantics are not available\n"
    if test_requested:
        lines = lines.rstrip("\n") + "\ntest skipped: final case semantics are not available\n"
    body = redact_secrets(lines)
    trace_path.write_text(body, encoding=UTF8)
    payload = json.dumps(evidence, indent=1, ensure_ascii=False) + "\n"
    evidence_path.write_text(payload, encoding=UTF8)
    _write_stdout(body)
    return EXIT_OK


def _stem(name, started):
    stamp = started.replace("-", "").replace(":", "")
    cleaned = []
    for char in name:
        if char.isalnum() or char in ("-", "_"):
            cleaned.append(char)
        else:
            cleaned.append("-")
    label = "".join(cleaned).strip("-") or "case"
    return "final-" + stamp + "-" + redact_secrets(label)


def _unique(path):
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(path.stem + "-" + str(index) + path.suffix)
        if not candidate.exists():
            return candidate
        index += 1


def _write_stdout(text):
    _write_stream(sys.stdout, text)


def _write_stderr(text):
    _write_stream(sys.stderr, text)


def _write_stream(stream, text):
    data = text.encode(UTF8)
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
        return
    stream.write(text)
    stream.flush()
