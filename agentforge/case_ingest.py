"""Neutral inventory of a case folder. No business interpretation."""
import csv
import io
import json
import logging
import os
import posixpath
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

STATUS_EXTRACTED = "extracted"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
TYPE_UNKNOWN = "unknown"

TEXT_TYPES = frozenset({"md", "txt"})
JSON_TYPE = "json"
CSV_TYPE = "csv"
PDF_TYPE = "pdf"
DOCX_TYPE = "docx"
XLSX_TYPE = "xlsx"

UTF8 = "utf-8"
WARNING_LIMIT = 180
COLUMN_BASE = 26
WARNING_UNSUPPORTED = "unsupported format"
WARNING_UTF8 = "text is not valid utf-8"

XL_DIR = "xl"
WORKBOOK = "xl/workbook.xml"
WORKBOOK_RELS = "xl/_rels/workbook.xml.rels"
SHARED_STRINGS = "xl/sharedStrings.xml"
DOCUMENT_XML = "word/document.xml"


def ingest_case_folder(folder):
    """Return a deterministic evidence inventory for every file under `folder`."""
    root = Path(folder)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    paths, problems = _files(root)
    items = [_read_file(path, path.relative_to(root).as_posix()) for path in paths]
    items.extend(_problem_item(root, error) for error in problems)
    items.sort(key=lambda item: item["path"])
    return {"case_folder": str(root.resolve()), "files": items}


def _files(root):
    found = []
    problems = []

    def onerror(error):
        problems.append(error)

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror, followlinks=False):
        dirnames.sort()
        for name in filenames:
            found.append(Path(dirpath) / name)
    found.sort(key=lambda item: item.relative_to(root).as_posix())
    return found, problems


def _problem_item(root, error):
    raw = getattr(error, "filename", None) or str(root)
    try:
        relative = Path(raw).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        relative = str(raw).replace("\\", "/")
    warning = "directory read failed: " + _short(error)
    return _item(relative or ".", TYPE_UNKNOWN, STATUS_FAILED, None, None, [warning])


def _read_file(path, relative):
    kind = _kind(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        warning = "read failed: " + _short(exc)
        return _item(relative, kind, STATUS_FAILED, None, None, [warning])
    try:
        text, structured, warnings = _extract(kind, data)
    except Exception as exc:
        warning = "extraction failed: " + _short(exc)
        return _item(relative, kind, STATUS_FAILED, None, None, [warning])
    return _item(relative, kind, _status(text, structured, warnings), text, structured, warnings)


def _kind(path):
    suffix = path.suffix.lower().lstrip(".")
    return suffix or TYPE_UNKNOWN


def _extract(kind, data):
    if kind in TEXT_TYPES:
        text, warnings = _decode(data)
        return text, None, warnings
    if kind == JSON_TYPE:
        return _extract_json(data)
    if kind == CSV_TYPE:
        return _extract_csv(data)
    if kind == PDF_TYPE:
        return _extract_pdf(data)
    if kind == DOCX_TYPE:
        return _extract_docx(data)
    if kind == XLSX_TYPE:
        return _extract_xlsx(data)
    if kind == TYPE_UNKNOWN:
        return None, None, [WARNING_UNSUPPORTED + ": no extension"]
    return None, None, [WARNING_UNSUPPORTED + ": ." + kind]


def _extract_json(data):
    text, warnings = _decode(data)
    if text is None:
        return None, None, warnings
    try:
        structured = json.loads(text)
    except json.JSONDecodeError as exc:
        warnings.append("json parse failed: " + _short(exc))
        return text, None, warnings
    return text, structured, warnings


def _extract_csv(data):
    text, warnings = _decode(data)
    if text is None:
        return None, None, warnings
    try:
        rows = [list(row) for row in csv.reader(io.StringIO(text, newline=""))]
    except csv.Error as exc:
        warnings.append("csv parse failed: " + _short(exc))
        return text, None, warnings
    return text, rows, warnings


def _extract_pdf(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, None, ["pdf extraction unavailable: pypdf is not installed"]
    logger = logging.getLogger("pypdf")
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = []
            warnings = []
            for index, page in enumerate(reader.pages, start=1):
                try:
                    pages.append(page.extract_text() or "")
                except Exception as exc:
                    message = "pdf page " + str(index) + " extraction failed: " + _short(exc)
                    warnings.append(message)
        except Exception as exc:
            return None, None, ["pdf extraction failed: " + _short(exc)]
    finally:
        logger.setLevel(previous)
    text = "\n".join(pages).strip()
    if text:
        return text, None, warnings
    if not warnings:
        warnings.append("pdf contained no extractable text")
    return None, None, warnings


def _extract_docx(data):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        return None, None, ["docx extraction failed: " + _short(exc)]
    with archive:
        names = archive.namelist()
        if DOCUMENT_XML not in names:
            return None, None, ["docx extraction failed: word/document.xml is missing"]
        try:
            parts = [_docx_text(archive.read(DOCUMENT_XML))]
        except ET.ParseError as exc:
            return None, None, ["docx extraction failed: " + _short(exc)]
        warnings = []
        extras = sorted(
            name for name in names
            if name.startswith("word/header") or name.startswith("word/footer")
        )
        for name in extras:
            if not name.endswith(".xml"):
                continue
            try:
                parts.append(_docx_text(archive.read(name)))
            except (KeyError, ET.ParseError) as exc:
                warnings.append("docx part failed: " + name + " " + _short(exc))
                continue
            warnings.append("included part " + name)
        text = "\n".join(part for part in parts if part)
        return text, None, warnings


def _docx_text(payload):
    root = ET.fromstring(payload)
    paragraphs = []
    for node in root.iter():
        if _local(node.tag) != "p":
            continue
        paragraphs.append(_paragraph_text(node))
    return "\n".join(paragraphs)


def _paragraph_text(paragraph):
    chunks = []
    for child in paragraph.iter():
        local = _local(child.tag)
        if local == "t" and child.text:
            chunks.append(child.text)
        elif local == "tab":
            chunks.append("\t")
        elif local == "br":
            chunks.append("\n")
    return "".join(chunks)


def _extract_xlsx(data):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        return None, None, ["xlsx extraction failed: " + _short(exc)]
    with archive:
        names = set(archive.namelist())
        if WORKBOOK not in names:
            return None, None, ["xlsx extraction failed: xl/workbook.xml is missing"]
        warnings = []
        try:
            shared = _shared_strings(archive, names, warnings)
            sheets = _sheet_targets(archive, warnings)
        except (KeyError, ET.ParseError) as exc:
            return None, None, ["xlsx extraction failed: " + _short(exc)]
        structured = []
        rendered = []
        for name, target in sheets:
            rows, sheet_warnings = _sheet_rows(archive, target, shared)
            warnings.extend(sheet_warnings)
            structured.append({"name": name, "rows": rows})
            lines = ["# " + name]
            for row in rows:
                lines.append("\t".join(row["cells"]))
            rendered.append("\n".join(lines))
        return "\n".join(rendered), {"sheets": structured}, warnings


def _shared_strings(archive, names, warnings):
    if SHARED_STRINGS not in names:
        return []
    root = ET.fromstring(archive.read(SHARED_STRINGS))
    values = []
    for node in list(root):
        if _local(node.tag) != "si":
            continue
        values.append("".join(_collect_text(node, frozenset({"rPh", "phoneticPr"}))))
    if not values and root is not None:
        warnings.append("xlsx shared strings were empty")
    return values


def _sheet_targets(archive, warnings):
    root = ET.fromstring(archive.read(WORKBOOK))
    rels = {}
    if WORKBOOK_RELS in set(archive.namelist()):
        rel_root = ET.fromstring(archive.read(WORKBOOK_RELS))
        for rel in list(rel_root):
            if _local(rel.tag) != "Relationship":
                continue
            rel_id = rel.attrib.get("Id")
            target = rel.attrib.get("Target")
            if rel_id and target:
                rels[rel_id] = _join_xl(target)
    sheets = []
    for node in root.iter():
        if _local(node.tag) != "sheet":
            continue
        name = node.attrib.get("name") or ""
        rel_id = _namespaced_id(node.attrib)
        target = rels.get(rel_id)
        if not target:
            warnings.append("xlsx sheet target missing: " + (name or "(unnamed)"))
            continue
        sheets.append((name, target))
    return sheets


def _sheet_rows(archive, target, shared):
    warnings = []
    try:
        root = ET.fromstring(archive.read(target))
    except KeyError as exc:
        return [], ["xlsx sheet failed: " + target + " " + _short(exc)]
    except ET.ParseError as exc:
        return [], ["xlsx sheet failed: " + target + " " + _short(exc)]
    by_row = {}
    for cell in root.iter():
        if _local(cell.tag) != "c":
            continue
        column, row = _split_ref(cell.attrib.get("r") or "")
        if row is None:
            warnings.append("xlsx cell reference missing")
            continue
        columns = by_row.setdefault(row, {})
        if column in columns:
            warnings.append("xlsx duplicate cell reference")
        value, cell_warnings = _cell_value(cell, shared)
        warnings.extend(cell_warnings)
        columns[column] = value
    rows = []
    for row_number in sorted(by_row):
        columns = by_row[row_number]
        width = max(columns) + 1 if columns else 0
        cells = [columns.get(index, "") for index in range(width)]
        rows.append({"row": row_number, "cells": cells})
    return rows, warnings


def _cell_value(cell, shared):
    kind = cell.attrib.get("t") or "n"
    warnings = []
    if _has_child(cell, "f"):
        warnings.append("xlsx formula cell uses cached value")
    if kind == "s":
        raw = _child_text(cell, "v")
        try:
            return shared[int(raw)], warnings
        except (TypeError, ValueError, IndexError):
            warnings.append("xlsx shared string missing")
            return "", warnings
    if kind == "inlineStr":
        return "".join(_collect_text(cell, frozenset())), warnings
    if kind == "b":
        raw = _child_text(cell, "v")
        if raw == "1":
            return "true", warnings
        if raw == "0":
            return "false", warnings
        return raw, warnings
    if kind == "e":
        warnings.append("xlsx cell error")
        return "", warnings
    return _child_text(cell, "v"), warnings


def _collect_text(node, skip_tags):
    chunks = []

    def walk(current):
        if _local(current.tag) in skip_tags:
            return
        if _local(current.tag) == "t" and current.text:
            chunks.append(current.text)
        for child in list(current):
            walk(child)

    walk(node)
    return chunks


def _join_xl(target):
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(XL_DIR, target))


def _namespaced_id(attrib):
    for key, value in attrib.items():
        if _local(key) == "id" and key != "sheetId":
            return value
    return ""


def _split_ref(ref):
    letters = []
    digits = []
    for char in ref:
        if char.isalpha():
            if digits:
                return None, None
            letters.append(char)
        elif char.isdigit():
            digits.append(char)
        else:
            return None, None
    if not letters or not digits:
        return None, None
    return _column_index("".join(letters)), int("".join(digits))


def _column_index(letters):
    value = 0
    for char in letters.upper():
        value = value * COLUMN_BASE + (ord(char) - ord("A") + 1)
    return value - 1


def _has_child(node, name):
    return any(_local(child.tag) == name for child in list(node))


def _child_text(node, name):
    for child in list(node):
        if _local(child.tag) == name:
            return child.text or ""
    return ""


def _decode(data):
    try:
        return data.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        return data.decode(UTF8, errors="replace"), [WARNING_UTF8]


def _status(text, structured, warnings):
    if not warnings:
        return STATUS_EXTRACTED
    if text is not None or structured is not None:
        return STATUS_PARTIAL
    return STATUS_FAILED


def _item(path, kind, status, text, structured, warnings):
    return {
        "path": path,
        "type": kind,
        "status": status,
        "text": text,
        "structured": structured,
        "warnings": _unique(warnings),
    }


def _unique(warnings):
    found = []
    for warning in warnings:
        if warning not in found:
            found.append(warning)
    return found


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _short(exc):
    text = type(exc).__name__ + ": " + str(exc)
    text = " ".join(text.split())
    if len(text) > WARNING_LIMIT:
        return text[:WARNING_LIMIT]
    return text
