"""Index a customer fixture and answer one service call.

Response bodies that come from the fixture are the original JSON text.
Unknown keys use the contract's error for that service. No customer is
hard-coded.
"""
import json
import re
from pathlib import Path

from agentforge.case_spec import FENCE

CUSTOMER_KEY = "customerNo"
CARD_KEY = "cardNumber"
WEEK_KEY = "newStatementWeek"
TEMPLATE_PREFIXES = ("{{", "%7B%7B")
WEEK_SERVICES = ("statement.week.decide", "statement.week.change")
CARD_SERVICES = ("cards.balance", "statement.week.get")
UTF8 = "utf-8"


class FixtureError(ValueError):
    """The fixture or contract could not be indexed."""


def build_index(case_folder, spec):
    """Return the lookup index for a normalized spec."""
    root = Path(case_folder)
    raw = (root / spec["fixture"]["path"]).read_text(encoding=UTF8)
    contract = (root / spec["sources"]["contract"]).read_text(encoding=UTF8)
    parsed, _start, end = _parse_at(raw, 0)
    if end < 0:
        raise FixtureError("fixture JSON could not be indexed")
    by_service = {}
    for rule in spec["fixture"]["lookup"]:
        by_service[rule["service"]] = _mode(rule["by"])
    records = {}
    customers = parsed.get("customers")
    if not isinstance(customers, list):
        raise FixtureError("fixture has no customers")
    for customer in customers:
        if not isinstance(customer, dict):
            continue
        number = _identity(customer.get("customerNo"))
        services = customer.get("services")
        if not isinstance(services, dict) or not number:
            continue
        for name, node in services.items():
            if str(name).endswith(".__span"):
                continue
            bucket = records.setdefault(name, {})
            _store(bucket, name, number, node, raw, by_service.get(name, CUSTOMER_KEY))
    paths = {}
    for operation in spec["operations"]:
        paths[operation["path"]] = {
            "name": operation["name"],
            "method": operation["method"],
            "by": by_service.get(operation["name"], CUSTOMER_KEY),
        }
    return {
        "paths": paths,
        "records": records,
        "fallback": _fallbacks(spec, contract, records),
        "template_probe": bool(spec.get("template_probe")),
    }


def write_index(index, path):
    """Write the worker index. The directory is generated and not committed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(index, ensure_ascii=False, indent=1) + "\n"
    target.write_text(payload, encoding=UTF8)


def write_index(index, path):
    """Write the lookup index as JSON for the Cloudflare Worker."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(index, ensure_ascii=False, indent=1) + "\n"
    target.write_text(payload, encoding=UTF8)


def lookup(index, method, path, payload):
    """Return status, exact body text and delay seconds."""
    operation = (index.get("paths") or {}).get(path)
    if operation is None or str(method).upper() != operation["method"]:
        missing = json.dumps({"error": "not_found", "path": path}, ensure_ascii=False)
        return {"status": 404, "body": missing, "delaySeconds": 0}
    name = operation["name"]
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = {}
    if _templated(data, operation["by"]) and index.get("template_probe"):
        sample = _first_success(index["records"].get(name) or {})
        if sample is not None:
            return {"status": sample["status"], "body": sample["body"], "delaySeconds": 0}
    missing_field = _missing_field(operation["by"], data)
    if missing_field:
        return _invalid(index, missing_field)
    key = _key(operation["by"], data)
    found = (index["records"].get(name) or {}).get(key)
    if found is None:
        fallback = (index.get("fallback") or {}).get(name) or _invalid(index, "request")
        return {"status": fallback["status"], "body": fallback["body"], "delaySeconds": 0}
    return {
        "status": found["status"],
        "body": found["body"],
        "delaySeconds": int(found.get("delaySeconds") or 0),
    }


def _mode(text):
    if "newStatementWeek" in text:
        return "cardWeek"
    if "cardNumber" in text:
        return "cardNumber"
    return "customerNo"


def _unwrap(value):
    if isinstance(value, tuple) and len(value) == 3 and isinstance(value[1], int):
        return value[0]
    return value


def _identity(value):
    value = _unwrap(value)
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value).strip()


def _store(bucket, name, number, node, raw, mode):
    leaf = _leaf(node, raw)
    if leaf is not None and mode == "customerNo":
        bucket[number] = leaf
        return
    if not isinstance(node, dict):
        return
    for card, entry in node.items():
        if str(card).endswith(".__span") or card in ("http", "response", "delaySeconds"):
            continue
        card_leaf = _leaf(entry, raw)
        if card_leaf is not None:
            bucket[str(card)] = card_leaf
            continue
        if not isinstance(entry, dict):
            continue
        for week, week_entry in entry.items():
            if str(week).endswith(".__span"):
                continue
            week_leaf = _leaf(week_entry, raw)
            if week_leaf is None:
                continue
            bucket[str(card) + "|" + _identity(week)] = week_leaf


def _leaf(node, raw):
    if not isinstance(node, dict) or "http" not in node or "response.__span" not in node:
        return None
    http = node["http"]
    span = node["response.__span"]
    if not isinstance(http, tuple) or not isinstance(span, tuple):
        return None
    delay = node.get("delaySeconds")
    delay_value = delay[0] if isinstance(delay, tuple) else 0
    return {
        "status": int(http[0]),
        "body": raw[span[0]:span[1]],
        "delaySeconds": int(delay_value or 0),
    }


def _key(mode, data):
    if mode == "cardWeek":
        return _identity(data.get(CARD_KEY)) + "|" + _identity(data.get(WEEK_KEY))
    if mode == "cardNumber":
        return _identity(data.get(CARD_KEY))
    return _identity(data.get(CUSTOMER_KEY))


def _missing_field(mode, data):
    if mode == "cardWeek":
        if not _identity(data.get(CARD_KEY)):
            return CARD_KEY
        if not _identity(data.get(WEEK_KEY)):
            return WEEK_KEY
        return ""
    if mode == "cardNumber":
        return "" if _identity(data.get(CARD_KEY)) else CARD_KEY
    return "" if _identity(data.get(CUSTOMER_KEY)) else CUSTOMER_KEY


def _templated(data, mode):
    fields = [CUSTOMER_KEY]
    if mode == "cardNumber":
        fields = [CARD_KEY]
    if mode == "cardWeek":
        fields = [CARD_KEY, WEEK_KEY]
    for field in fields:
        value = data.get(field)
        if isinstance(value, str) and value.startswith(TEMPLATE_PREFIXES):
            return True
    return False


def _first_success(bucket):
    for entry in bucket.values():
        if int(entry.get("status") or 0) == 200:
            return entry
    return None


def _invalid(index, field):
    fallback = (index.get("fallback") or {}).get("INVALID_ARGUMENTS_ERROR")
    if not fallback:
        body = json.dumps({"result": {"code": "INVALID_ARGUMENTS_ERROR"}}, ensure_ascii=False)
        return {"status": 400, "body": body, "delaySeconds": 0}
    return {"status": fallback["status"], "body": fallback["body"], "delaySeconds": 0}


def _fallbacks(spec, contract, records):
    found = {}
    for row in spec["errors"]:
        code = row["code"]
        example = _example_with(contract, code)
        body = example or _envelope(code, row["type"], _message(row))
        for name in _service_names(row["services"], spec):
            if row["http"] == 404 or (row["http"] == 400 and name not in found):
                found[name] = {"status": row["http"], "body": body}
            if row["http"] == 500 and name not in found:
                continue
        if code == "INVALID_ARGUMENTS_ERROR":
            found[code] = {"status": 400, "body": body}
        if code == "FBE00099":
            found[code] = {"status": 500, "body": body}
    for operation in spec["operations"]:
        name = operation["name"]
        if name in found:
            continue
        invalid = found.get("INVALID_ARGUMENTS_ERROR")
        if invalid:
            found[name] = invalid
    for name, bucket in records.items():
        if name in found:
            continue
        for entry in bucket.values():
            if int(entry["status"]) >= 400:
                found[name] = {"status": entry["status"], "body": entry["body"]}
                break
    return found


def _service_names(cell, spec):
    names = []
    if cell.strip("`") == "all":
        return [item["name"] for item in spec["operations"]]
    for match in re.finditer(r"`([^`]+)`", cell):
        names.append(match.group(1))
    return names


def _message(row):
    match = re.search("“([^”]+)”|\"([^\"]+)\"", row["when"])
    if match:
        return match.group(1) or match.group(2)
    return row["code"]


def _example_with(contract, code):
    for fence in FENCE.findall(contract):
        if code not in fence:
            continue
        start = fence.find("{")
        if start < 0:
            continue
        try:
            _value, begin, end = _parse_at(fence, start)
        except (IndexError, ValueError):
            continue
        if begin >= 0:
            return fence[begin:end].strip()
    return ""


def _envelope(code, kind, message):
    result = {}
    result["returnCode"] = code
    result["messageText"] = message
    result["code"] = code
    result["message"] = message
    result["type"] = kind or "ERROR"
    details = {}
    details["rootCause"] = None
    details["errorOrigin"] = None
    result["details"] = details
    body = {}
    body["result"] = result
    return json.dumps(body, ensure_ascii=False)


def _parse_at(text, index):
    index = _skip(text, index)
    if index >= len(text):
        raise ValueError("truncated JSON")
    start = index
    char = text[index]
    if char == "{":
        return _parse_object(text, index)
    if char == "[":
        return _parse_array(text, index)
    if char == '"':
        value, end = _parse_string(text, index)
        return value, start, end
    if char == "t" and text.startswith("true", index):
        return True, start, index + 4
    if char == "f" and text.startswith("false", index):
        return False, start, index + 5
    if char == "n" and text.startswith("null", index):
        return None, start, index + 4
    if char == "-" or char.isdigit():
        return _parse_number(text, index)
    raise ValueError("unexpected JSON at " + str(index))


def _parse_object(text, index):
    start = index
    index += 1
    value = {}
    index = _skip(text, index)
    if text[index] == "}":
        return value, start, index + 1
    while True:
        index = _skip(text, index)
        key, index = _parse_string(text, index)
        index = _skip(text, index)
        if text[index] != ":":
            raise ValueError("expected colon")
        index += 1
        child, child_start, index = _parse_at(text, index)
        if isinstance(child, (dict, list)):
            value[key] = child
        else:
            value[key] = (child, child_start, index)
        if isinstance(child, (dict, list)):
            value[key + ".__span"] = (child_start, index)
        index = _skip(text, index)
        if text[index] == ",":
            index += 1
            continue
        if text[index] == "}":
            return value, start, index + 1
        raise ValueError("expected object end")


def _parse_array(text, index):
    start = index
    index += 1
    value = []
    index = _skip(text, index)
    if text[index] == "]":
        return value, start, index + 1
    while True:
        child, _child_start, index = _parse_at(text, index)
        value.append(child)
        index = _skip(text, index)
        if text[index] == ",":
            index += 1
            continue
        if text[index] == "]":
            return value, start, index + 1
        raise ValueError("expected array end")


def _parse_string(text, index):
    if text[index] != '"':
        raise ValueError("expected string")
    index += 1
    chars = []
    while index < len(text):
        char = text[index]
        if char == '"':
            return "".join(chars), index + 1
        if char == "\\":
            index += 1
            escaped = text[index]
            mapping = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/"}
            if escaped == "u":
                chars.append(chr(int(text[index + 1:index + 5], 16)))
                index += 5
                continue
            chars.append(mapping.get(escaped, escaped))
            index += 1
            continue
        chars.append(char)
        index += 1
    raise ValueError("unterminated string")


def _parse_number(text, index):
    start = index
    if text[index] == "-":
        index += 1
    while index < len(text) and text[index].isdigit():
        index += 1
    float_value = False
    if index < len(text) and text[index] == ".":
        float_value = True
        index += 1
        while index < len(text) and text[index].isdigit():
            index += 1
    if index < len(text) and text[index] in ("e", "E"):
        float_value = True
        index += 1
        if index < len(text) and text[index] in ("+", "-"):
            index += 1
        while index < len(text) and text[index].isdigit():
            index += 1
    token = text[start:index]
    if float_value:
        return float(token), start, index
    return int(token), start, index


def _skip(text, index):
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index
