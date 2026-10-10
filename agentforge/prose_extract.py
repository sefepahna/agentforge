"""Bind a narrow set of prose policy statements into the existing brief fields.

This is not a general reader. It fills bands, outcome maps, and the bank name
only when a sentence matches the patterns below. Pipe-table rows stay with the
markdown reader. Example sections are skipped. Ordinary prohibitions are not
withdrawals and do not block deployment.
"""
import re

RANGE = re.compile(r"(?i)\b(\d+)\s+to\s+(\d+)\s+days\s+late\b")
BAND_NAME = re.compile(r"(?i)\b([a-z]+)\s+band\b")
BUSINESS_DAY = re.compile(r"(?i)\b(\d+)(?:st|nd|rd|th)\s+business\s+day\b")
ATTEMPT = re.compile(
    r"(?i)(?:(\d+)\s+persuasion\s+attempts?\b|\bpersuasion\s+attempts?\s*:\s*(\d+))"
)
USE_NONE = re.compile(r"(?i)\buse\s+outcome\s+([a-z_]+)\s+with\s+no\s+reason\b")
USE_SOME = re.compile(
    r"(?i)\buse\s+outcome\s+([a-z_]+)\s+with\s+reasons?\s+(.+?)(?:\s+when\b|\s+for\b|$)"
)
ALT_NONE = re.compile(r"(?i)\b([a-z_]+)\s+outcome\s+(?:has|uses|with)\s+no\s+reason\b")
ALT_SOME = re.compile(
    r"(?i)\b([a-z_]+)\s+outcome\s+(?:has|uses|with)\s+reasons?\s+(.+?)(?:\s+when\b|\s+for\b|$)"
)
BANK_NAME = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+Bank\b")
WITHDRAWAL = re.compile(
    r"(?i)\b(withdraw|withdraws|withdrawn|no longer applies|is revoked|do not apply)\b"
)
FLOOR_DEFINITION = re.compile(r"(?i)(?:^FLOOR\b|\bthe floor is\b)")
FLOOR_BINDING = re.compile(
    r"`?([a-z][a-z0-9_]*(?:_payment|_amount))`?\s+for\s+(?:a\s+)?"
)
EXAMPLE_SECTION = re.compile(r"(?i)^(example only|sample only|illustration|for example)\b")
POLICY_SECTION = re.compile(r"(?i)^(policy schedule|policy|schedule)\b")

FLOOR_UNBOUND = "explicit floor statement was not bound to configuration"
WITHDRAWAL_UNAPPLIED = "policy withdrawal was detected but cannot be applied"
BAND_REJECTED = "prose band statement was ambiguous or conflicting and was not applied"
OUTCOME_REJECTED = "prose outcome statement was ambiguous or conflicting and was not applied"
BANK_CONFLICT = "bank name statements conflict and were not applied"


def _sentences(line):
    parts = re.split(r"(?<=[.!?])\s+", line.strip())
    return [part.strip() for part in parts if part.strip()]


def _classify_lines(text):
    """Mark policy lines. Example headings cover following fences and indents."""
    section = "policy"
    fence = None
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            fence = section if fence is None else None
            rows.append((number, line, "marker"))
            continue
        if fence is not None:
            rows.append((number, line, fence))
            continue
        if EXAMPLE_SECTION.match(stripped):
            section = "example"
            rows.append((number, line, "marker"))
            continue
        if POLICY_SECTION.match(stripped):
            section = "policy"
            rows.append((number, line, "marker"))
            continue
        rows.append((number, line, section))
    return rows


def _policy_paragraphs(text):
    paragraphs = []
    current = []
    for number, line, kind in _classify_lines(text):
        if kind != "policy":
            if current:
                paragraphs.append(current)
                current = []
            continue
        if not line.strip() or line.lstrip().startswith("|"):
            if current:
                paragraphs.append(current)
                current = []
            continue
        for sentence in _sentences(line):
            current.append((number, sentence))
    if current:
        paragraphs.append(current)
    return paragraphs


def _attempt_value(sentence):
    found = ATTEMPT.search(sentence)
    if not found:
        return None
    return int(found.group(1) or found.group(2))


def _complete(group):
    return all(group.get(key) is not None for key in ("low", "high", "name", "day", "attempts"))


def _paragraph_bands(sentences):
    groups = []
    current = None
    for number, sentence in sentences:
        day_count = len(list(BUSINESS_DAY.finditer(sentence)))
        attempts = _attempt_value(sentence)
        found_range = RANGE.search(sentence)
        found_name = BAND_NAME.search(sentence)
        if found_range and found_name:
            if day_count > 1:
                return [], {"problem": "ambiguous_day", "line": number}
            if current and not _complete(current):
                return [], {"problem": "incomplete_band", "line": number}
            if current:
                groups.append(current)
            day = BUSINESS_DAY.search(sentence)
            current = {
                "low": int(found_range.group(1)),
                "high": int(found_range.group(2)),
                "name": found_name.group(1).lower(),
                "day": int(day.group(1)) if day else None,
                "attempts": attempts,
                "line": number,
            }
            continue
        if day_count or attempts is not None:
            if current is None or _complete(current):
                return [], {"problem": "unattached_slot", "line": number}
            if day_count > 1 or (day_count and current["day"] is not None):
                return [], {"problem": "conflicting_slot", "line": number}
            if attempts is not None and current["attempts"] is not None:
                return [], {"problem": "conflicting_slot", "line": number}
            if day_count == 1:
                current["day"] = int(BUSINESS_DAY.search(sentence).group(1))
            if attempts is not None:
                current["attempts"] = attempts
    if current and not _complete(current):
        return [], {"problem": "incomplete_band", "line": current["line"]}
    if current:
        groups.append(current)
    return groups, None


def _extract_bands(text):
    found = []
    seen = {}
    problem = None
    for paragraph in _policy_paragraphs(text):
        groups, paragraph_problem = _paragraph_bands(paragraph)
        if paragraph_problem:
            problem = paragraph_problem
            continue
        for group in groups:
            key = (group["low"], group["high"], group["name"])
            packed = "%s|%s|%s|%s|%s" % (
                group["low"], group["high"], group["name"], group["day"], group["attempts"],
            )
            prior = seen.get(key)
            if prior and prior != packed:
                problem = {"problem": "conflicting_band", "line": group["line"]}
                continue
            seen[key] = packed
            if packed not in found:
                found.append(packed)
    if problem:
        return [], problem
    return found, None


def _reason_list(tail):
    parts = re.split(r"(?i)\s*,\s*|\s+\band\b\s+|\s+\bor\b\s+", tail.strip(" ."))
    tokens = []
    for part in parts:
        token = re.sub(r"(?i)^(and|or)\s+", "", part.strip(" ."))
        if not token:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]*", token):
            return None
        tokens.append(token)
    return tokens


def _outcome_from_sentence(sentence):
    if USE_NONE.search(sentence):
        return USE_NONE.search(sentence).group(1).lower(), []
    match = USE_SOME.search(sentence)
    if match:
        return match.group(1).lower(), _reason_list(match.group(2))
    if ALT_NONE.search(sentence):
        return ALT_NONE.search(sentence).group(1).lower(), []
    match = ALT_SOME.search(sentence)
    if match:
        return match.group(1).lower(), _reason_list(match.group(2))
    return None, None


def _extract_outcomes(text):
    found = {}
    problem = None
    for paragraph in _policy_paragraphs(text):
        for number, sentence in paragraph:
            name, reasons = _outcome_from_sentence(sentence)
            if name is None:
                continue
            if reasons is None:
                problem = {"problem": "ambiguous_reasons", "line": number}
                continue
            prior = found.get(name)
            if prior is not None and prior != reasons:
                problem = {"problem": "conflicting_outcome", "line": number}
                continue
            found[name] = reasons
    if problem:
        return {}, problem
    return found, None


def _extract_bank(text):
    names = []
    for paragraph in _policy_paragraphs(text):
        for _number, sentence in paragraph:
            if WITHDRAWAL.search(sentence):
                continue
            for match in BANK_NAME.finditer(sentence):
                name = match.group(0).strip()
                if name not in names:
                    names.append(name)
    return names


def _withdrawals(text):
    found = []
    for paragraph in _policy_paragraphs(text):
        for number, sentence in paragraph:
            if WITHDRAWAL.search(sentence):
                found.append(number)
    return found


def _unbound_floor_lines(text):
    rows = []
    for number, line, kind in _classify_lines(text):
        if kind != "policy":
            continue
        stripped = line.strip()
        if FLOOR_DEFINITION.search(stripped) and not FLOOR_BINDING.search(stripped):
            rows.append(number)
    return rows


def _detail(prefix, problem):
    return prefix + " (" + problem["problem"] + ", line " + str(problem["line"]) + ")"


def apply_prose(parsed, text):
    """Copy parsed fields and fill only empty band, outcome, and bank values.

    Markdown values win. A conflict or a withdrawal does not delete them.
    Diagnostics are deploy blockers; they are not a trace of every missed field.
    """
    updated = dict(parsed)
    diagnostics = []
    bands, band_problem = _extract_bands(text)
    outcomes, outcome_problem = _extract_outcomes(text)
    bank_names = _extract_bank(text)
    if _withdrawals(text):
        diagnostics.append(
            WITHDRAWAL_UNAPPLIED + " (line " + str(_withdrawals(text)[0]) + ")"
        )
        bands = []
        band_problem = None
    if band_problem:
        diagnostics.append(_detail(BAND_REJECTED, band_problem))
        bands = []
    if parsed.get("bands"):
        if bands and bands != parsed["bands"]:
            diagnostics.append(BAND_REJECTED + " (conflict_with_markdown)")
        bands = parsed["bands"]
    updated["bands"] = bands
    if outcome_problem:
        diagnostics.append(_detail(OUTCOME_REJECTED, outcome_problem))
        outcomes = {}
    if parsed.get("outcomes"):
        if outcomes and outcomes != parsed["outcomes"]:
            diagnostics.append(OUTCOME_REJECTED + " (conflict_with_markdown)")
        outcomes = parsed["outcomes"]
    updated["outcomes"] = outcomes
    bank = ""
    if len(bank_names) > 1:
        diagnostics.append(BANK_CONFLICT + " (" + ", ".join(bank_names) + ")")
    elif len(bank_names) == 1:
        bank = bank_names[0]
    if parsed.get("bank"):
        if bank and bank != parsed["bank"]:
            diagnostics.append(BANK_CONFLICT + " (conflict_with_heading)")
        bank = parsed["bank"]
    updated["bank"] = bank or parsed.get("bank") or ""
    floor_lines = _unbound_floor_lines(text)
    if floor_lines:
        shown = ", ".join("line " + str(number) for number in floor_lines[:4])
        diagnostics.append(FLOOR_UNBOUND + " (" + shown + ")")
    return updated, diagnostics
