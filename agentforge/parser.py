"""Read one or more briefs into a flat policy. Values come from the text, not from constants."""
import re
from pathlib import Path

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def load_openapi(path):
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _enums(spec):
    found = {}
    for path, item in spec.get("paths", {}).items():
        schema = item.get("post", {}).get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        props = schema.get("properties") or {}
        found[path.strip("/")] = {name: (field.get("enum") or []) for name, field in props.items()}
    return found


def _product_types(phrase):
    types = []
    for part in re.split(r"\bor\b|,", phrase.lower()):
        text = part.strip()
        if "credit card" in text:
            types.append("credit_card")
        elif "personal loan" in text:
            types.append("personal_loan")
        elif "car loan" in text:
            types.append("car_loan")
        else:
            slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
            if slug and slug not in ("a", "the"):
                types.append(slug)
    return types


def _kind(text):
    low = text.lower()
    if any(word in low for word in ("business day", "holiday", "deadline", "floor", "amount", "wrong answer", "date of birth")):
        return "code"
    if any(word in low for word in ("close as", "do not say", "verify", "outcome", "before identity", "transfer", "callback")):
        return "transition"
    return "prompt"


def _parse_one(text, spec):
    enums = _enums(spec)
    holidays = []
    for line in text.splitlines():
        if re.search(r"holiday", line, re.I):
            holidays.extend(re.findall(r"\d{4}-\d{2}-\d{2}", line))
    bands = []
    for low, high, name, deadline, attempts in re.findall(
        r"\|\s*(\d+)\s+to\s+(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|",
        text,
        re.I,
    ):
        count = re.search(r"(\d+)(?:st|nd|rd|th)\s+business day", deadline, re.I)
        if not count:
            continue
        bands.append("%s|%s|%s|%s|%s" % (low, high, name.strip().strip("`"), count.group(1), attempts))
    outcomes = {}
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or re.fullmatch(r"[:\- ]+", cells[0]):
            continue
        if re.search(r"outcome", cells[0], re.I) and "`" not in cells[0]:
            in_table = True
            continue
        if not in_table:
            continue
        if not any("`" in cell for cell in cells):
            in_table = False
            continue
        names = re.findall(r"`([^`]+)`", cells[0])
        if not names:
            continue
        reason_cell = cells[1] if len(cells) > 1 else ""
        if reason_cell.lower() in ("none", "`none`"):
            reasons = []
        else:
            reasons = re.findall(r"`([^`]+)`", reason_cell)
        outcomes[names[0]] = reasons
    floors = []
    for field, phrase in re.findall(
        r"`?([a-z][a-z0-9_]*(?:_payment|_amount))`?\s+for\s+(?:a\s+)?(.+?)(?:\s+and\s+`|\.|;|\n)",
        text,
    ):
        for product in _product_types(phrase):
            floors.append(product + "|" + field)
    notes = None
    if re.search(r"never uses\s+`?add_note`?", text, re.I):
        notes = False
    if re.search(r"(call|use)\s+`?add_note`?", text, re.I):
        notes = True
    multi = None
    max_products = None
    match = re.search(r"up to\s+(\w+)\s+products|one to\s+(\w+)\s+products", text, re.I)
    if match:
        word = (match.group(1) or match.group(2)).lower()
        max_products = int(word) if word.isdigit() else WORD_NUMBERS.get(word, 0)
        multi = max_products > 1
    if re.search(r"\bone product\b", text, re.I) and max_products is None:
        max_products = 1
        multi = False
    window = re.search(r"from\s+(\d{1,2}:\d{2})\s+to\s+(\d{1,2}:\d{2})", text)
    wrong = re.search(r"(\d+|one|two|three|four|five)\s+wrong answers", text, re.I)
    id_fields = []
    for match in re.finditer(r"date of birth|last four digits|phone_last4|date_of_birth|postcode|birth year|company number", text, re.I):
        token = match.group(0).lower()
        if "birth" in token and "year" not in token:
            field = "date_of_birth"
        elif "four" in token or "phone" in token:
            field = "phone_last4"
        elif "postcode" in token:
            field = "postcode"
        elif "birth year" in token:
            field = "birth_year"
        else:
            field = "company_number"
        allowed = (enums.get("verify_identity") or {}).get("field") or []
        if field not in id_fields and (not allowed or field in allowed):
            id_fields.append(field)
    forbidden = []
    ban = re.search(r"Do not say ([^.]+)\.", text)
    if ban:
        forbidden = re.findall(r'"([^"]+)"', ban.group(1))
    sentence = ""
    match = re.search(r'say this sentence:\s*"([^"]+)"', text, re.I)
    if match:
        sentence = match.group(1)
    sorry = ""
    match = re.search(r'say "([^"]*sorry[^"]*)"', text, re.I)
    if match:
        sorry = match.group(1)
    rules = []
    for match in re.finditer(r"(?m)^(\d+)\.\s+(.+)$", text):
        rules.append({"id": match.group(1), "text": match.group(2).strip(), "implement_with": _kind(match.group(2))})
    heading = re.search(r"(?m)^#\s+[^:\n]*:\s*([^,\n]+)", text)
    bank = heading.group(1).strip() if heading else ""
    example_now = ""
    match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text)
    if match:
        example_now = match.group(0)
    return {
        "holidays": holidays,
        "bands": bands,
        "outcomes": outcomes,
        "floors": floors,
        "notes": notes,
        "multi": multi,
        "max_products": max_products,
        "callback_start": window.group(1) if window else "",
        "callback_end": window.group(2) if window else "",
        "max_wrong": (int(wrong.group(1)) if wrong and wrong.group(1).isdigit() else WORD_NUMBERS.get((wrong.group(1) if wrong else "").lower(), 0)) if wrong else 0,
        "id_fields": id_fields,
        "forbidden": forbidden,
        "sentence": sentence,
        "sorry": sorry,
        "rules": rules,
        "bank": bank,
        "example_now": example_now,
        "paid_line": "Payments can take one business day to appear." if re.search(r"one business day to appear", text, re.I) else "",
        "app_line": "Please use the mobile app or a branch." if re.search(r"mobile app or a branch", text, re.I) else "",
        "queues": (enums.get("transfer_to_agent") or {}).get("queue") or [],
    }


def _pick(reasons, *names):
    for name in names:
        if name in reasons:
            return name
    return ""


def _merge(base, extra):
    if extra.get("holidays"):
        for day in extra["holidays"]:
            if day not in base["holidays"]:
                base["holidays"].append(day)
    if extra.get("bands"):
        base["bands"] = extra["bands"]
    if extra.get("outcomes"):
        base["outcomes"] = extra["outcomes"]
    if extra.get("floors"):
        base["floors"] = extra["floors"]
    for key in ("notes", "multi", "max_products"):
        if extra.get(key) is not None:
            base[key] = extra[key]
    for key in ("callback_start", "callback_end", "sentence", "sorry", "bank", "example_now", "paid_line", "app_line"):
        if extra.get(key):
            base[key] = extra[key]
    if extra.get("max_wrong"):
        base["max_wrong"] = extra["max_wrong"]
    if extra.get("id_fields"):
        base["id_fields"] = extra["id_fields"]
    if extra.get("forbidden"):
        base["forbidden"] = extra["forbidden"]
    if extra.get("queues"):
        base["queues"] = extra["queues"]
    base["rules"].extend(extra.get("rules") or [])
    return base


EXACT_OUTCOMES = {
    "promise": "role_promise",
    "paid": "role_paid",
    "transferred": "role_transferred",
    "no_promise": "role_no_promise",
    "not_verified": "role_not_verified",
    "not_reached": "role_not_reached",
}


def _norm_outcome(name):
    return str(name).strip().lower()


def _roles(outcomes, queues):
    chosen = {}
    unsupported = []
    for name in outcomes:
        role = EXACT_OUTCOMES.get(_norm_outcome(name))
        if role is None:
            unsupported.append(str(name))
            continue
        if role not in chosen:
            chosen[role] = name
    roles = {}
    for role in EXACT_OUTCOMES.values():
        roles[role] = chosen.get(role, "")
    roles["unsupported_outcomes"] = unsupported
    def reasons(role):
        return outcomes.get(roles[role]) or []
    mapped = {
        "reason_blank": "",
        "reason_callback": _pick(reasons("role_not_reached"), "callback"),
        "reason_no_callback": _pick(reasons("role_not_reached"), "no_callback"),
        "reason_wrong_number": _pick(reasons("role_not_reached"), "wrong_number"),
        "reason_deceased": _pick(reasons("role_not_reached"), "deceased"),
        "reason_unclear": _pick(reasons("role_not_reached"), "unclear"),
        "reason_failed": _pick(reasons("role_not_verified"), "failed"),
        "reason_declined": _pick(reasons("role_not_verified"), "declined"),
        "reason_refused": _pick(reasons("role_no_promise"), "refused"),
        "reason_hardship": _pick(reasons("role_no_promise"), "hardship"),
        "reason_dispute": _pick(reasons("role_no_promise"), "dispute"),
        "reason_service_error": _pick(reasons("role_no_promise"), "service_error"),
        "reason_paid": _pick(reasons("role_no_promise") + (outcomes.get(roles["role_paid"]) or []), "paid") or "paid",
        "reason_support": _pick(reasons("role_transferred"), "support"),
        "reason_human": _pick(reasons("role_transferred"), "human"),
        "reason_restructuring": _pick(reasons("role_transferred"), "restructuring"),
    }
    queue_support = "support" if "support" in queues else ""
    queue_general = "general" if "general" in queues else ""
    queue_restructuring = "restructuring" if "restructuring" in queues else ""
    mapped["queue_support"] = queue_support
    mapped["queue_general"] = queue_general
    mapped["queue_restructuring"] = queue_restructuring
    mapped.update(roles)
    return mapped


def parse_briefs(paths, spec):
    """Merge brief files in order. A later file overrides tables and flags it states."""
    merged = {
        "holidays": [], "bands": [], "outcomes": {}, "floors": [], "notes": False, "multi": False,
        "max_products": 1, "callback_start": "10:00", "callback_end": "19:00", "max_wrong": 3,
        "id_fields": [], "forbidden": [], "sentence": "", "sorry": "", "rules": [], "bank": "the bank",
        "example_now": "", "paid_line": "", "app_line": "", "queues": [],
    }
    sources = []
    for path in paths:
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")
        sources.append(str(file_path))
        merged = _merge(merged, _parse_one(text, spec))
    blob = {
        "holidays": merged["holidays"],
        "bands": merged["bands"],
        "floors": merged["floors"],
        "bank": merged["bank"],
        "notes": "yes" if merged["notes"] else "no",
        "multi": "yes" if merged["multi"] else "no",
        "sentence": merged["sentence"],
        "sorry": merged["sorry"],
        "app_line": merged["app_line"],
        "paid_line": merged["paid_line"],
        "assistant_line": "I am " + merged["bank"] + "'s digital assistant.",
        "forbidden": merged["forbidden"],
        "callback_start": merged["callback_start"],
        "callback_end": merged["callback_end"],
        "id_fields": merged["id_fields"] or ["date_of_birth", "phone_last4"],
    }
    roles = _roles(merged["outcomes"], merged["queues"])
    merged["unsupported_outcomes"] = roles.pop("unsupported_outcomes")
    blob.update(roles)
    merged["blob"] = blob
    merged["sources"] = sources
    merged["server"] = (spec.get("servers") or [{}])[0].get("url") or ""
    merged["enums"] = _enums(spec)
    return merged
