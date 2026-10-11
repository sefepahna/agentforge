"""Case-folder ingestion, final trace, and export readiness. No Freya calls."""
import io
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from agentforge.case_ingest import ingest_case_folder
from agentforge.cli import main
from agentforge.final_export import export_final_workflow, export_invocation
from agentforge.final_trace import FinalBuildRecord, read_git_commit, render_final_trace, summarize_workflow

KIT = Path(__file__).resolve().parents[2]
SPEC = KIT / "tools" / "openapi.json"
BRIEF_A = KIT / "briefs" / "brief-a.md"
BRIEF_B = KIT / "briefs" / "brief-b.md"
PUBLIC_A = KIT / "out" / "brief-a.workflow.json"
PUBLIC_B = KIT / "out" / "brief-b.workflow.json"
HASH_A = "6dc58d0d3778d5bd09e7c7d35648a2df144628ad38042d2c1b3a8e7bf5b1d1da"
HASH_B = "56a8b0b58ca082d7e288628697b40cd902b335ca1ed8f9b01169e74257a47caf"
NODE_COUNT_A = 22
NODE_COUNT_B = 24
DISCLOSURE = "We are recording this call."
MOCK_URL = "https://example.test/mock"
SECRET_A = "fak-super-secret-value"
SECRET_B = "team-key-should-stay-hidden"
UTC_STAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"


def _write(root, relative, content):
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
        return path
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _only(evidence, relative):
    found = [item for item in evidence["files"] if item["path"] == relative]
    if len(found) != 1:
        raise AssertionError(relative)
    return found[0]


def _pdf(text):
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 24 Tf 72 120 Td (" + safe + ") Tj ET\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(("%d 0 obj\n" % index).encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref_at = len(body)
    size = len(objects) + 1
    body.extend(("xref\n0 %d\n" % size).encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(("%010d 00000 n \n" % offset).encode("ascii"))
    trailer = "trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_at)
    body.extend(trailer.encode("ascii"))
    return bytes(body)


def _docx(body_text, header_text=None):
    def document(text):
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body></w:document>"
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", document(body_text))
        if header_text is not None:
            archive.writestr("word/header1.xml", document(header_text))
    return buf.getvalue()


def _xlsx(sheets):
    shared = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><t>alpha</t></si></sst>"
    )
    rels = []
    workbook_sheets = []
    members = []
    total = len(sheets)
    for index, (name, worksheet) in enumerate(sheets, start=1):
        file_index = total - index + 1
        filename = "xl/worksheets/sheet%d.xml" % file_index
        members.append((filename, worksheet))
        rels.append(
            '<Relationship Id="rId%d" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet%d.xml"/>' % (index, file_index)
        )
        workbook_sheets.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (name, index, index))
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>%s</sheets></workbook>" % "".join(workbook_sheets)
    )
    rel_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels) + "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/_rels/workbook.xml.rels", rel_xml)
        for filename, worksheet in reversed(members):
            archive.writestr(filename, worksheet)
        archive.writestr("xl/workbook.xml", workbook)
    return buf.getvalue()


LATER_SHEET = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="C1" t="inlineStr"><is><t>tail</t></is></c>
    </row>
  </sheetData>
</worksheet>
"""

EARLIER_SHEET = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>beta</t></is></c>
      <c r="B1"><v>12</v></c>
    </row>
  </sheetData>
</worksheet>
"""

FORMULA_SHEET = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row>
  </sheetData>
</worksheet>
"""


class CaseFolderTests(unittest.TestCase):
    def test_inventory_is_recursive_and_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "z.txt", "z")
            _write(root, "nested/deep/note.md", "deep")
            _write(root, "b/c.txt", "c")
            _write(root, "a.txt", "a")
            _write(root, ".note.txt", "hidden")
            first = ingest_case_folder(root)
            second = ingest_case_folder(root)
        paths = [item["path"] for item in first["files"]]
        self.assertEqual(paths, [".note.txt", "a.txt", "b/c.txt", "nested/deep/note.md", "z.txt"])
        self.assertEqual(first, second)
        self.assertIn("nested/deep/note.md", paths)

    def test_evidence_order_ignores_creation_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("m.txt", "a/z.txt", "a/a.txt"):
                _write(root, name, name)
            evidence = ingest_case_folder(root)
        paths = [item["path"] for item in evidence["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(paths, ["a/a.txt", "a/z.txt", "m.txt"])

    def test_markdown_and_text_are_extracted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "note.md", "# Title\n\nalpha\n")
            _write(root, "plain.txt", "beta\n")
            evidence = ingest_case_folder(root)
        markdown = _only(evidence, "note.md")
        plain = _only(evidence, "plain.txt")
        self.assertEqual(markdown["type"], "md")
        self.assertEqual(markdown["status"], "extracted")
        self.assertEqual(markdown["text"], "# Title\n\nalpha\n")
        self.assertIsNone(markdown["structured"])
        self.assertEqual(markdown["warnings"], [])
        self.assertEqual(plain["type"], "txt")
        self.assertEqual(plain["text"], "beta\n")
        self.assertEqual(plain["warnings"], [])

    def test_json_is_extracted_without_interpretation(self):
        raw = '{"alpha": 1, "beta": [true, "x"]}\n'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "payload.json", raw)
            evidence = ingest_case_folder(root)
        item = _only(evidence, "payload.json")
        self.assertEqual(item["status"], "extracted")
        self.assertEqual(item["text"], raw)
        self.assertEqual(item["structured"], {"alpha": 1, "beta": [True, "x"]})
        self.assertEqual(item["warnings"], [])

    def test_csv_rows_are_extracted(self):
        raw = 'name,note\nada,"hello, world"\n'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "rows.csv", raw)
            evidence = ingest_case_folder(root)
        item = _only(evidence, "rows.csv")
        self.assertEqual(item["status"], "extracted")
        self.assertEqual(item["text"], raw)
        self.assertEqual(item["structured"], [["name", "note"], ["ada", "hello, world"]])
        self.assertEqual(item["warnings"], [])

    def test_pdf_text_is_extracted(self):
        import pypdf
        self.assertTrue(pypdf.__version__)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "note.pdf", _pdf("CaseFolder"))
            evidence = ingest_case_folder(root)
        item = _only(evidence, "note.pdf")
        self.assertEqual(item["status"], "extracted")
        self.assertEqual(item["text"], "CaseFolder")
        self.assertEqual(item["warnings"], [])

    def test_docx_text_is_extracted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "plain.docx", _docx("BodyLine"))
            _write(root, "headed.docx", _docx("BodyLine", "HeaderLine"))
            evidence = ingest_case_folder(root)
        plain = _only(evidence, "plain.docx")
        headed = _only(evidence, "headed.docx")
        self.assertEqual(plain["status"], "extracted")
        self.assertEqual(plain["text"], "BodyLine")
        self.assertEqual(plain["warnings"], [])
        self.assertIn("BodyLine", headed["text"])
        self.assertIn("HeaderLine", headed["text"])
        self.assertEqual(headed["status"], "partial")
        self.assertTrue(any("header1.xml" in warning for warning in headed["warnings"]))

    def test_xlsx_cells_are_extracted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "book.xlsx", _xlsx([("Later", LATER_SHEET), ("Earlier", EARLIER_SHEET)]))
            _write(root, "formula.xlsx", _xlsx([("Calc", FORMULA_SHEET)]))
            evidence = ingest_case_folder(root)
        book = _only(evidence, "book.xlsx")
        formula = _only(evidence, "formula.xlsx")
        self.assertEqual(book["status"], "extracted")
        self.assertEqual(book["warnings"], [])
        self.assertEqual(book["structured"]["sheets"], [
            {"name": "Later", "rows": [{"row": 1, "cells": ["alpha", "", "tail"]}]},
            {"name": "Earlier", "rows": [{"row": 1, "cells": ["beta", "12"]}]},
        ])
        self.assertIn("alpha", book["text"])
        self.assertIn("tail", book["text"])
        self.assertIn("beta", book["text"])
        self.assertEqual(formula["status"], "partial")
        self.assertEqual(formula["structured"]["sheets"][0]["rows"][0]["cells"], ["2"])
        self.assertTrue(any("formula" in warning for warning in formula["warnings"]))

    def test_unsupported_and_broken_files_stay_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, "blob.bin", b"\x00\x01")
            _write(root, "broken.json", b"{")
            _write(root, "broken.docx", b"not a docx")
            _write(root, "broken.pdf", b"not a pdf")
            _write(root, "broken.xlsx", b"not a workbook")
            _write(root, "bad.txt", b"\xff")
            _write(root, "README", b"no suffix")
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                evidence = ingest_case_folder(root)
        self.assertEqual(stderr.getvalue(), "")
        paths = [item["path"] for item in evidence["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(len(paths), 7)
        blob = _only(evidence, "blob.bin")
        broken_json = _only(evidence, "broken.json")
        self.assertEqual(blob["status"], "failed")
        self.assertIsNone(blob["text"])
        self.assertIn("unsupported format: .bin", blob["warnings"])
        self.assertEqual(broken_json["status"], "partial")
        self.assertEqual(broken_json["text"], "{")
        self.assertTrue(any("json parse failed" in warning for warning in broken_json["warnings"]))
        for name in ("broken.docx", "broken.pdf", "broken.xlsx"):
            item = _only(evidence, name)
            self.assertEqual(item["status"], "failed", name)
            self.assertTrue(item["warnings"], name)
        self.assertEqual(_only(evidence, "bad.txt")["status"], "partial")
        self.assertTrue(_only(evidence, "bad.txt")["warnings"])
        self.assertIn("unsupported format: no extension", _only(evidence, "README")["warnings"])

    def test_unreadable_directory_is_visible(self):
        def walk(root, topdown=True, onerror=None, followlinks=False):
            if onerror is not None:
                onerror(OSError(13, "denied", str(root)))
            return iter(())

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.case_ingest.os.walk", walk):
                evidence = ingest_case_folder(root)
        self.assertEqual(len(evidence["files"]), 1)
        self.assertEqual(evidence["files"][0]["status"], "failed")
        self.assertIn("directory read failed", evidence["files"][0]["warnings"][0])

    def test_existing_brief_invocation_remains_compatible(self):
        import hashlib
        before_a = PUBLIC_A.read_bytes()
        before_b = PUBLIC_B.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("agentforge.cli.KIT", root), patch("sys.stdout", io.StringIO()):
                code_a = main([str(BRIEF_A), "--openapi", str(SPEC), "--out", str(root / "a.json")])
                code_b = main(
                    [str(BRIEF_A), str(BRIEF_B), "--openapi", str(SPEC), "--out", str(root / "b.json")],
                )
            trace = next((root / "traces").glob("*brief-a*")).read_text(encoding="utf-8")
            built_a = json.loads((root / "a.json").read_text(encoding="utf-8"))
            built_b = json.loads((root / "b.json").read_text(encoding="utf-8"))
        self.assertEqual(code_a, 0)
        self.assertEqual(code_b, 0)
        self.assertIn("model none", trace)
        self.assertIn("validation ok", trace)
        self.assertEqual(len(built_a["nodes"]), NODE_COUNT_A)
        self.assertEqual(len(built_b["nodes"]), NODE_COUNT_B)
        self.assertEqual(built_a["initial_node"], "boot")
        self.assertEqual(built_b["initial_node"], "boot")
        self.assertIn(DISCLOSURE, json.dumps(built_a))
        self.assertIn(DISCLOSURE, json.dumps(built_b))
        self.assertEqual(built_a, json.loads(before_a.decode("utf-8")))
        self.assertEqual(built_b, json.loads(before_b.decode("utf-8")))
        self.assertEqual(hashlib.sha256(PUBLIC_A.read_bytes()).hexdigest(), HASH_A)
        self.assertEqual(hashlib.sha256(PUBLIC_B.read_bytes()).hexdigest(), HASH_B)
        self.assertEqual(PUBLIC_A.read_bytes(), before_a)
        self.assertEqual(PUBLIC_B.read_bytes(), before_b)

    def test_trace_contains_required_fields(self):
        before_a = PUBLIC_A.read_bytes()
        before_b = PUBLIC_B.read_bytes()
        trace_path = None
        evidence_path = None
        try:
            with tempfile.TemporaryDirectory() as folder:
                case = Path(folder) / "packet"
                case.mkdir()
                _write(case, "readme.md", "hello\n")
                stdout = io.StringIO()
                with patch("sys.stdout", stdout):
                    code = main([str(case), MOCK_URL])
                self.assertEqual(code, 0)
                traces = list((KIT / "traces").glob("final-*packet*.txt"))
                self.assertTrue(traces)
                trace_path = max(traces, key=lambda item: item.stat().st_mtime)
                evidence_path = trace_path.with_suffix(".evidence.json")
                trace = trace_path.read_text(encoding="utf-8")
            self.assertEqual(stdout.getvalue(), trace)
            commit = read_git_commit(KIT)
            self.assertRegex(commit, r"[0-9a-f]{40}")
            for label in (
                "run_start_utc: ",
                "run_end_utc: ",
                "builder_version: 3",
                "git_commit: " + commit,
                "case_folder: ",
                "mock_url: " + MOCK_URL,
                "builder_model_calls: none",
                "evidence_inventory:",
                "workflow_id: none",
                "agent_id: none",
                "workflow_node_count: none",
                "tool_count: none",
                "validation: not_run",
                "local_test: none",
            ):
                self.assertIn(label, trace)
            self.assertRegex(trace, "run_start_utc: " + UTC_STAMP)
            self.assertRegex(trace, "run_end_utc: " + UTC_STAMP)
            self.assertIn("readme.md", trace)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["files"][0]["path"], "readme.md")
            self.assertEqual(evidence["files"][0]["text"], "hello\n")
        finally:
            if trace_path is not None:
                trace_path.unlink(missing_ok=True)
            if evidence_path is not None:
                evidence_path.unlink(missing_ok=True)
        self.assertEqual(PUBLIC_A.read_bytes(), before_a)
        self.assertEqual(PUBLIC_B.read_bytes(), before_b)
        self.assertFalse((KIT / "submission" / "final.workflow.json").exists())

    def test_trace_omits_configured_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / SECRET_A
            case.mkdir()
            _write(case, SECRET_B + ".txt", "body " + SECRET_A + " " + SECRET_B + "\n")
            stdout = io.StringIO()
            env = {"FREYA_API_KEY": SECRET_A, "FREYA_BANK_TEAM_KEY": SECRET_B}
            with patch("agentforge.cli.KIT", root), patch.dict(os.environ, env), patch("sys.stdout", stdout):
                code = main([str(case), MOCK_URL + "?x=" + SECRET_A])
            self.assertEqual(code, 0)
            trace_path = next((root / "traces").glob("final-*.txt"))
            trace = trace_path.read_text(encoding="utf-8")
            evidence = json.loads(trace_path.with_suffix(".evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(stdout.getvalue(), trace)
        self.assertNotIn(SECRET_A, trace)
        self.assertNotIn(SECRET_B, trace)
        self.assertNotIn(SECRET_A, trace_path.name)
        self.assertNotIn(SECRET_B, trace_path.name)
        self.assertIn("[redacted]", trace)
        self.assertIn(SECRET_A, evidence["files"][0]["text"])
        self.assertIn("builder_model_calls: none", trace)

    def test_case_folder_does_not_parse_briefs_or_overwrite_workflows(self):
        before_a = PUBLIC_A.read_bytes()
        before_b = PUBLIC_B.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / "packet"
            case.mkdir()
            _write(case, "note.md", "not a brief table\n")
            stdout = io.StringIO()
            with patch("agentforge.cli.KIT", root), \
                    patch("agentforge.cli.parse_briefs", side_effect=AssertionError("parsed")), \
                    patch("freya.save_workflow", side_effect=AssertionError("saved")), \
                    patch("freya.export_workflow", side_effect=AssertionError("exported")), \
                    patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
                    patch("sys.stdout", stdout):
                code = main([
                    str(case), MOCK_URL, "--deploy", "--test", "--out", str(PUBLIC_A),
                ])
            trace = stdout.getvalue()
            self.assertFalse((root / "submission" / "final.workflow.json").exists())
        self.assertEqual(code, 0)
        self.assertIn("deploy skipped: final case semantics are not available", trace)
        self.assertIn("test skipped: final case semantics are not available", trace)
        self.assertIn("builder_model_calls: none", trace)
        self.assertIn("validation: not_run", trace)
        self.assertEqual(PUBLIC_A.read_bytes(), before_a)
        self.assertEqual(PUBLIC_B.read_bytes(), before_b)

    def test_case_folder_rejects_a_missing_mock_url(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / "packet"
            case.mkdir()
            stderr = io.StringIO()
            with patch("agentforge.cli.KIT", root), patch("sys.stderr", stderr):
                missing = main([str(case)])
            self.assertEqual(missing, 2)
            self.assertIn("mock_url", stderr.getvalue())
            stderr = io.StringIO()
            with patch("agentforge.cli.KIT", root), patch("sys.stderr", stderr):
                rejected = main([str(case), "not-a-url"])
            self.assertEqual(rejected, 2)
            self.assertIn("http", stderr.getvalue())
            stderr = io.StringIO()
            with patch("agentforge.cli.KIT", root), patch("sys.stderr", stderr):
                extra = main([str(case), MOCK_URL, "extra.md"])
            self.assertEqual(extra, 2)
            self.assertFalse((root / "traces").exists())

    def test_supplied_build_is_recorded_without_a_model_call(self):
        record = FinalBuildRecord("wf_example", "agent_example", 4, 2, "ok", "local check passed")
        text = render_final_trace(
            "2026-10-11T12:00:00Z",
            "2026-10-11T12:00:01Z",
            "3",
            "abc",
            "C:/case",
            MOCK_URL,
            [],
            "C:/traces/final.evidence.json",
            build=record,
        )
        self.assertIn("builder_model_calls: none", text)
        self.assertIn("workflow_id: wf_example", text)
        self.assertIn("agent_id: agent_example", text)
        self.assertIn("workflow_node_count: 4", text)
        self.assertIn("tool_count: 2", text)
        self.assertIn("validation: ok", text)
        self.assertIn("local_test: local check passed", text)
        nodes, tools = summarize_workflow({
            "nodes": {
                "boot": {"node_type": "code"},
                "api_account": {"node_type": "api_request"},
                "talk": {"node_type": "conversation"},
            },
        })
        self.assertEqual(nodes, 3)
        self.assertEqual(tools, 1)

    def test_export_command_targets_the_final_path(self):
        command = export_invocation("wf_example")
        self.assertIn("export_workflow", command)
        self.assertIn("submission/final.workflow.json", command)
        self.assertIn("wf_example", command)
        self.assertNotIn(SECRET_A, command)
        with self.assertRaises(ValueError):
            export_invocation("none")
        template = json.loads((KIT / "submission" / "submission.template.json").read_text(encoding="utf-8"))
        self.assertIsNone(template["workflow_id"])
        self.assertIsNone(template["agent_id"])
        self.assertEqual(template["workflow_export"], "submission/final.workflow.json")
        with tempfile.TemporaryDirectory() as folder:
            with patch("freya.export_workflow", return_value="ok") as mocked:
                result = export_final_workflow("wf_example", folder)
            target = mocked.call_args.args[1].replace("\\", "/")
            self.assertTrue(target.endswith("submission/final.workflow.json"))
            self.assertEqual(result, "ok")
            mocked.assert_called_once()
            with patch("freya.export_workflow", side_effect=AssertionError("called")):
                with self.assertRaises(ValueError):
                    export_final_workflow("", folder)

    def test_final_artifacts_are_not_gitignored(self):
        def ignored(relative):
            proc = subprocess.run(
                ["git", "check-ignore", "-q", "--", relative],
                cwd=str(KIT),
                capture_output=True,
                check=False,
            )
            return proc.returncode == 0

        self.assertFalse(ignored("traces/final.log"))
        self.assertFalse(ignored("submission/final.workflow.json"))
        self.assertFalse(ignored("submission/submission.json"))
        self.assertTrue(ignored("traces/agentforge-scratch.txt"))
        self.assertTrue(ignored("traces/debug.log"))
        self.assertTrue(ignored(".env"))


if __name__ == "__main__":
    unittest.main()
