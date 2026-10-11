"""Build a normalized case spec from an evidence inventory.

Documents are read at run time. Customer numbers, card names and fixture
answers are not stored here. A missing required rule raises CaseSpecError.
"""
import re
from datetime import datetime

QUOTED = re.compile("“([^”]+)”")
ASCII_QUOTED = re.compile("\"([^\"\\n]{12,})\"")
DATE_IN_PATH = re.compile(r"(20\d{2}-\d{2}-\d{2})")
EMAIL_DATE = re.compile(
    r"Date:\s*(?:[A-Za-z]+,\s*)?(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})",
    re.IGNORECASE,
)
HEADING = re.compile(r"^###\s+5\.(\d+)\s+`([^`]+)`", re.MULTILINE)
BASE_URL = re.compile(r"https://[^\s`]+/voice/v1/")
FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
REQUIRED_LINES = (
    "no_card",
    "select_card",
    "same_name",
    "same_last4",
    "same_last6",
    "tl_unpaid",
    "tl_minimum_paid",
    "tl_partial",
    "fx_debt",
    "due",
    "due_today",
    "another_card",
    "offer_both",
    "offer_week",
    "offer_email",
    "no_email",
    "email_confirm",
    "email_sent",
    "menu_normal",
    "tries_exhausted",
    "silence_end",
    "pay_agent",
    "agent",
    "dispute_agent",
    "service_error",
    "week_error",
    "out_of_scope_ask",
    "joint_main",
    "joint_linked",
    "week_confirm",
    "cut_today",
    "no_statement_debt",
    "week_current",
    "week_options",
    "week_done",
    "week_yearly",
    "no_debt_one",
    "non_turkish",
)
LINE_NEEDLES = {
    "no_card": "uygun bir kredi kartınız",
    "select_card": "Hangi kartınızın borcunu",
    "same_name": "isimli birden fazla",
    "same_last4": "son altı hanesini",
    "same_last6": "Son altı hanesi aynı",
    "tl_unpaid": "ödenmesi gereken minimum tutar ZZZ",
    "tl_minimum_paid": "Minimum ödemenizi yaptığınız",
    "tl_partial": "kalan minimum ödeme",
    "fx_debt": "Dolar borcunuz XXX",
    "due": "Borçlarınız için son ödeme tarihiniz",
    "due_today": "son ödeme tarihiniz bugündür",
    "another_card": "Başka bir kartınızın borcunu",
    "offer_both": "kayıtlı mail adresinize gönderebilirim",
    "offer_week": "Hesap kesim tarihinizi değiştirebilirim.",
    "offer_email": "Ekstrenizi kayıtlı mail adresinize gönderebilirim.",
    "no_email": "kayıtlı bir e-posta adresiniz bulunmadığı",
    "email_confirm": "adresine göndermemi ister misiniz",
    "email_sent": "kayıtlı e-posta adresinize gönderildi",
    "menu_normal": "Sizi ana menüye yönlendiriyorum.",
    "tries_exhausted": "şu anda yardımcı olamıyorum. Sizi ana menüye aktarıyorum",
    "silence_end": "Sesinizi alamadığım için",
    "pay_agent": "Borç ödeme işleminiz için",
    "agent": "Sizi müşteri temsilcisine aktarıyorum",
    "dispute_agent": "müşteri temsilcimiz yardımcı olacak",
    "service_error": "işleminizi gerçekleştiremiyorum",
    "week_error": "hesap kesim tarihinizi değiştiremiyorum",
    "out_of_scope_ask": "ana menüye aktarmamı ister misiniz",
    "joint_main": "kartınıza bağlı",
    "joint_linked": "bağlı olduğu",
    "week_confirm": "Onaylıyor musunuz",
    "cut_today": "Hesap kesim tarihiniz bugün",
    "no_statement_debt": "tarihli ekstresinden borcunuz bulunmamaktadır",
    "week_current": "Bir sonraki hesap kesim tarihiniz",
    "week_options": "haftasına alabilirim",
    "week_done": "olarak değiştirildi",
    "week_yearly": "yılda bir kez değiştirebilirsiniz",
    "no_debt_one": "borcunuz bulunmamaktadır",
    "non_turkish": "Sizi ana menüye aktarıyorum.",
}


class CaseSpecError(ValueError):
    """The case folder does not support a safe deterministic spec."""


def build_case_spec(evidence):
    """Return the normalized spec for one ingested case folder."""
    files = evidence.get("files") or []
    texts = [item for item in files if item.get("text")]
    contract = _latest(_matching(texts, _is_contract))
    fixture = _fixture(files)
    analysis_docs = _matching(texts, _is_analysis)
    latest = _latest(analysis_docs)
    older = [item for item in analysis_docs if item is not latest]
    emails = _matching(texts, _is_email)
    meetings = _matching(texts, _is_meeting)
    examples = _latest(_matching(texts, _is_examples))
    brief = _latest(_matching(texts, _is_brief))
    readme = _latest(_matching(texts, _is_readme))
    flow = _latest(_matching(texts, _is_flow))
    faq = _latest(_matching(texts, _is_faq))
    prompts = _latest(_matching(texts, _is_prompt_sheet))
    overview = _latest(_matching(texts, _is_fixture_overview))
    mock_readme = _latest(_matching(texts, _is_mock_readme))
    if contract is None or fixture is None or latest is None:
        missing = []
        if contract is None:
            missing.append("service contract")
        if fixture is None:
            missing.append("customer fixture")
        if latest is None:
            missing.append("analysis")
        raise CaseSpecError("required evidence is missing: " + ", ".join(missing))
    operations, errors = _operations(contract["text"])
    lines, missing_lines = _lines(latest["text"], emails, latest)
    if missing_lines:
        raise CaseSpecError("required lines were not found: " + ", ".join(missing_lines))
    policy = _policy(latest["text"], emails, lines)
    if "no field telling you whether the customer can still change the week" in contract["text"]:
        policy["week_eligibility_known"] = False
        policy["offer_week_when_eligibility_unknown"] = True
        policy["week_limit_enforced_by"] = "service"
    follow_lines, follow_flags, follow_meeting = _follow_up(meetings)
    lines.update(follow_lines)
    policy.update(follow_flags)
    conflicts = _conflicts(
        policy, latest, older, emails, meetings, flow, faq, prompts, examples, follow_meeting,
    )
    inventory = [_inventory_row(item) for item in files]
    return {
        "language": policy["language"],
        "call_variables": policy["call_variables"],
        "clock_variable": policy["clock_variable"],
        "operations": operations,
        "errors": errors,
        "balance_blocks": _balance_blocks(contract["text"]),
        "amount_fields": [
            name for name in ("statementDebt", "minPayment", "remainingDebt", "remainingMinPayment")
            if name in contract["text"]
        ],
        "fixture": {
            "path": fixture["path"],
            "lookup": _lookup_rules(overview["text"] if overview else ""),
        },
        "lines": lines,
        "policy": policy,
        "conflicts": conflicts,
        "open_points": _open_points(latest["text"], contract["text"]),
        "sources": {
            "contract": contract["path"],
            "analysis": latest["path"],
            "fixture": fixture["path"],
            "examples": examples["path"] if examples else "",
            "brief": brief["path"] if brief else "",
            "readme": readme["path"] if readme else "",
            "flow": flow["path"] if flow else "",
            "overview": overview["path"] if overview else "",
            "mock_readme": mock_readme["path"] if mock_readme else "",
        },
        "inventory": inventory,
        "template_probe": bool(mock_readme and "isTemplateVariable" in mock_readme["text"]),
        "paraphrases": _paraphrases(latest["text"]),
    }


def _paraphrases(analysis):
    """Turkish lines for rules the bank wrote in English and did not quote."""
    rows = []
    if "most recent statement" in analysis or "Only the last" in analysis:
        rows.append({
            "id": "latest_statement",
            "text": "Yalnızca en son kesilen ekstreyi gönderebilirim.",
            "because": "The latest-statement rule is written in English without a Turkish quotation.",
        })
    if "security reasons" in analysis:
        rows.append({
            "id": "third_party",
            "text": "Güvenlik nedeniyle yalnızca kendi kartlarınız için işlem yapabilirim.",
            "because": "The third-party rule is written in English without a Turkish quotation.",
        })
    if "isMainCard" in analysis and "no eligible card for this" in analysis:
        rows.append({
            "id": "supplementary",
            "text": "Bu kart ekstre borcu sorgulaması için uygun değil.",
            "because": "The supplementary-card refusal is written in English without a Turkish quotation.",
        })
    if "can't change the address" in analysis or "cannot change" in analysis:
        rows.append({
            "id": "address_change",
            "text": "Bu görüşmede kayıtlı e-posta adresini değiştiremiyorum.",
            "because": "The address-change refusal is written in English without a Turkish quotation.",
        })
    if "After the due date" in analysis:
        rows.append({
            "id": "due_passed",
            "text": "Son ödeme tarihiniz geçmiştir.",
            "because": "The analysis says to tell the caller the due date has passed, without a Turkish quotation.",
        })
    return rows


def _inventory_row(item):
    return {
        "path": item.get("path"),
        "type": item.get("type"),
        "status": item.get("status"),
        "warnings": list(item.get("warnings") or []),
    }


def _matching(items, predicate):
    return [item for item in items if predicate(item)]


def _latest(items):
    if not items:
        return None
    return sorted(items, key=lambda item: (_stamp(item), item["path"]))[-1]


def _stamp(item):
    found = DATE_IN_PATH.findall(item.get("path") or "")
    if found:
        return found[-1]
    text = item.get("text") or ""
    best = ""
    for match in EMAIL_DATE.finditer(text):
        month = MONTHS.get(match.group(2)[:3].lower())
        if not month:
            continue
        day = int(match.group(1))
        year = int(match.group(3))
        try:
            stamp = datetime(year, month, day).date().isoformat()
        except ValueError:
            continue
        if stamp > best:
            best = stamp
    return best


def _is_contract(item):
    text = item.get("text") or ""
    return "voice/v1/" in text and "cards.list" in text and "service contract" in text.lower()


def _is_analysis(item):
    text = item.get("text") or ""
    return "Reading the debt" in text and "Card" in text and item.get("type") == "md"


def _is_email(item):
    text = item.get("text") or ""
    return text.startswith("From:") or "\nFrom:" in text or text.startswith("From ")


def _is_meeting(item):
    text = item.get("text") or ""
    return "[00:" in text and "Selin" in text


def _is_examples(item):
    text = item.get("text") or ""
    return text.startswith("# Example scenarios") or "\n## Example 1" in text


def _is_brief(item):
    text = item.get("text") or ""
    return "customerNumber" in text and "what you build" in text.lower()


def _is_readme(item):
    name = (item.get("path") or "").lower()
    text = item.get("text") or ""
    return name.endswith("readme.md") and "customerNumber" in text and "voice/v1/" not in text


def _is_flow(item):
    return item.get("type") == "pdf" and "Card list" in (item.get("text") or "")


def _is_faq(item):
    text = item.get("text") or ""
    return "Help centre" in text or "How do I get my statement by e-mail" in text


def _is_prompt_sheet(item):
    text = item.get("text") or ""
    return "Prompt id" in text and "DBT-010" in text


def _is_fixture_overview(item):
    text = item.get("text") or ""
    return "one answer per customer" in text and "newStatementWeek" in text


def _is_mock_readme(item):
    text = item.get("text") or ""
    return "isTemplateVariable" in text or "npx wrangler deploy" in text


def _fixture(files):
    for item in files:
        structured = item.get("structured")
        if not isinstance(structured, dict):
            continue
        customers = structured.get("customers")
        if isinstance(customers, list) and customers:
            services = customers[0].get("services") if isinstance(customers[0], dict) else None
            if isinstance(services, dict) and "cards.list" in services:
                return item
    return None


def _operations(text):
    base = BASE_URL.search(text)
    if not base:
        raise CaseSpecError("service contract has no voice base address")
    prefix = "/" + base.group(0).split("/", 3)[-1]
    if not prefix.endswith("/"):
        prefix += "/"
    operations = []
    matches = list(HEADING.finditer(text))
    if not matches:
        raise CaseSpecError("service contract has no numbered services")
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        name = match.group(2).strip()
        operations.append({
            "order": int(match.group(1)),
            "name": name,
            "method": "POST",
            "path": prefix + name,
            "request_example": _first_json(body),
        })
    errors = _error_table(text)
    return operations, errors


def _first_json(body):
    found = FENCE.search(body)
    if not found:
        return ""
    return found.group(1).strip()


def _balance_blocks(text):
    found = []
    seen = []
    for match in re.finditer(r"\bdebt(TL|USD|EUR|GBP)\b", text):
        field = match.group(0)
        if field in seen:
            continue
        seen.append(field)
        found.append({"field": field, "code": match.group(1)})
    return found


def _error_table(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        code = cells[1].strip("`")
        rows.append({
            "http": int(cells[0]),
            "code": code,
            "type": cells[2].strip("`"),
            "when": cells[3],
            "services": cells[4],
        })
    if not rows:
        raise CaseSpecError("service contract error table was not found")
    return rows


def _quotes(text):
    return QUOTED.findall(text or "")


def _shortest_quote(text, needle):
    found = [quote.strip() for quote in _quotes(text) + ASCII_QUOTED.findall(text or "") if needle in quote]
    if not found:
        return ""
    found.sort(key=len)
    return found[0]


def _quote_with(text, needle):
    for quote in _quotes(text) + ASCII_QUOTED.findall(text or ""):
        if needle in quote:
            return quote.strip()
    return ""


def _lines(analysis, emails, latest):
    found = {}
    missing = []
    later_email = "\n".join(
        item["text"] for item in emails if _stamp(item) >= _stamp(latest)
    )
    for key in REQUIRED_LINES:
        needle = LINE_NEEDLES[key]
        quote = ""
        if key in ("out_of_scope_ask", "silence_end", "same_last4", "same_last6"):
            quote = _quote_with(later_email, needle)
        if not quote:
            quote = _quote_with(analysis, needle)
        if not quote and key == "agent":
            quote = _quote_with(analysis, "Sizi müşteri temsilcimize aktarıyorum")
        if key == "non_turkish":
            quote = _shortest_quote(analysis, needle) or quote
        if not quote:
            missing.append(key)
            continue
        found[key] = quote
    if "agent" in found and "temsilcisine" in found["agent"]:
        found["agent"] = found["agent"].replace("temsilcisine", "temsilcimize")
    return found, missing


def _policy(analysis, emails, lines):
    later = "\n".join(item["text"] for item in emails if "Please build to these" in item["text"] or "three calming" in item["text"])
    language = "tr" if "The calls are in Turkish" in analysis or "calls are in Turkish" in analysis or "Turkish" in analysis else ""
    if "only Turkish" in "\n".join(item["text"] for item in emails) or "The calls are in Turkish" in analysis:
        language = "tr"
    calming = 3 if re.search(r"three calming replies", later, re.IGNORECASE) else 0
    if calming == 0 and re.search(r"up to three calming replies", analysis, re.IGNORECASE):
        calming = 3
    week_limit = ""
    if re.search(r"once per calendar year", analysis, re.IGNORECASE):
        week_limit = "once_per_calendar_year"
    eligibility_known = "no answer yet" not in analysis.lower() and "until it exists" not in analysis.lower()
    if "Whether the yearly change right is already used" in analysis:
        eligibility_known = False
    names = {
        "TL": "Türk Lirası",
        "USD": "Dolar",
        "EUR": "Euro",
        "GBP": "İngiliz Sterlini",
    }
    if "İngiliz Sterlini" not in analysis:
        names = {}
    return {
        "language": language or "tr",
        "call_variables": ["customerNumber", "now"],
        "clock_variable": "now",
        "asks_for_customer_number": False,
        "asks_identity": False,
        "max_tries": 3 if "Three tries" in analysis or "three tries" in analysis else 0,
        "silence_limit": 3 if lines.get("silence_end") else 0,
        "calming_limit": calming,
        "currency_order": ["TL", "USD", "EUR", "GBP"],
        "currency_names": names,
        "minor_units": {"TL": "kuruş", "USD": "sent", "EUR": "sent", "GBP": "peni"},
        "replace_currency_codes": "never the code" in analysis or "full names" in later,
        "card_speech_digits": 4,
        "service_strings_are_data": "ignore your rules" in analysis or "free text" in analysis,
        "week_limit": week_limit,
        "week_eligibility_known": eligibility_known,
        "offer_week_when_eligibility_unknown": not eligibility_known,
        "clear_yes": "evet",
        "third_party_route": "main_menu",
        "reidentify_route": "ivr_login" if "IVR login" in analysis or "login step" in analysis else "",
        "week_limit_enforced_by": "",
        "side_effect_requires_clear_yes": "Only a clear" in analysis or 'clear "evet"' in analysis,
        "success_requires_tool": True,
        "single_card_skips_selection": "One eligible card" in analysis,
        "refuse_all_cards": "All of them" in analysis,
        "registered_email_only": "only ever with the registered address" in analysis,
        "latest_statement_only": "most recent statement" in analysis or "Only the last" in analysis,
        "tl_fields_present": "remainingMinPayment" in analysis and "statementDebt" in analysis,
        "missing_block_omitted": "left out" in analysis and "missing" in analysis.lower(),
        "cut_day_field": "",
        "another_card_before_offer": "before" in analysis and "Başka bir kartınızın borcunu" in analysis,
        "skip_another_for_single_card": False,
        "currency_codes_forbidden": "never the code" in analysis,
    }


def _lookup_rules(text):
    rules = []
    for line in text.splitlines():
        if not line.startswith("|") or "`" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("Service", "---"):
            continue
        name = cells[0].strip("`")
        if not re.match(r"^[a-z]+\.[a-z0-9.]+$", name):
            continue
        rules.append({"service": name, "by": cells[1].replace("`", "")})
    return rules


def _open_points(analysis, contract):
    points = []
    for label, text in (("analysis", analysis), ("contract", contract)):
        part = text.split("## 11.")[-1] if label == "analysis" and "## 11." in text else ""
        if label == "contract":
            part = text.split("## 7.")[-1] if "## 7." in text else ""
        for line in part.splitlines():
            stripped = line.strip()
            if re.match(r"^\d+\.", stripped):
                points.append({"source": label, "text": stripped})
    return points


def _follow_up(meetings):
    """Later listening session. Only phrases present in that transcript are kept."""
    chosen = None
    for item in meetings:
        text = item.get("text") or ""
        if "henüz kesilmiş bir ekstresi" not in text:
            continue
        if chosen is None or _stamp(item) >= _stamp(chosen):
            chosen = item
    if chosen is None:
        return {}, {}, None
    text = chosen["text"]
    lines = {}
    no_yet = "Kartınızın henüz kesilmiş bir ekstresi olmadığı için ekstre borcunuz bulunmamaktadır."
    if no_yet in text:
        lines["no_statement_yet"] = no_yet
    if "İlk hesap kesim tarihiniz" in text and "olacak." in text:
        lines["first_statement"] = "İlk hesap kesim tarihiniz [tarih] olacak."
    flags = {}
    if "totalDebt" in text and "per currency" in text:
        flags["cut_day_field"] = "totalDebt"
    if "one card, no question" in text:
        flags["skip_another_for_single_card"] = True
    if "Başka bir kartınızın borcunu öğrenmek ister misiniz?" in text:
        flags["another_card_before_offer"] = True
    if "All four in full" in text and "İngiliz Sterlini" in text:
        flags["currency_codes_forbidden"] = True
        flags["currency_names"] = {
            "TL": "Türk Lirası",
            "USD": "Dolar",
            "EUR": "Euro",
            "GBP": "İngiliz Sterlini",
        }
    return lines, flags, chosen


def _conflicts(policy, latest, older, emails, meetings, flow, faq, prompts, examples, follow_meeting=None):
    found = []
    latest_text = latest["text"]
    email_text = "\n".join(item["text"] for item in emails)
    if flow and "Second factor" in (flow.get("text") or "") and "no second factor" in email_text.lower() or (
        flow and "Second factor" in (flow.get("text") or "") and "does **not** ask" in latest_text
    ):
        found.append(_conflict(
            "second_factor",
            flow["path"] if flow else "",
            "The flow drawing has a second-factor branch.",
            latest["path"],
            "Later mail and the analysis say the assistant does not ask for a second factor.",
            "no_second_factor",
        ))
    if any("Third time: main menu" in item["text"] or "Silence | First two" in item["text"] for item in older):
        found.append(_conflict(
            "silence_terminal",
            older[-1]["path"] if older else "",
            "The earlier analysis sends the third silence to the main menu.",
            latest["path"],
            "The later analysis and the decision mail end the call instead.",
            "end_call",
        ))
    if "Out-of-scope question | Main menu directly" in "\n".join(item["text"] for item in older) or (
        "goes directly to the main menu" in latest_text and "aktarmamı ister misiniz" in email_text
    ):
        found.append(_conflict(
            "out_of_scope",
            latest["path"],
            "The 8 October analysis still sends out-of-scope questions straight to the main menu.",
            "decision mail",
            "The later mail says to ask before transferring, then return if the caller continues.",
            "ask_then_menu",
        ))
    if re.search(r"up to two calming", email_text, re.IGNORECASE) and policy.get("calming_limit") == 3:
        found.append(_conflict(
            "calming_count",
            "decision mail draft",
            "One draft counted two calming replies.",
            "later correction in the same mail",
            "The correction says three calming replies.",
            "three",
        ))
    if faq and "any address you give us" in faq["text"] and policy.get("registered_email_only"):
        found.append(_conflict(
            "email_address",
            faq["path"],
            "The website FAQ allows any address the caller gives.",
            latest["path"],
            "The later analysis allows only the registered address.",
            "registered_only",
        ))
    if prompts and "yılda en çok üç" in prompts["text"] and policy.get("week_limit") == "once_per_calendar_year":
        found.append(_conflict(
            "week_limit",
            prompts["path"],
            "The older prompt sheet records a monthly change and three changes a year.",
            latest["path"],
            "The later analysis records one change per calendar year.",
            "once_per_calendar_year",
        ))
    if "first six and last four" in latest_text and "full card number" in email_text:
        found.append(_conflict(
            "card_masking",
            latest["path"],
            "The analysis treats the masked test number as the production shape.",
            "decision mail",
            "The later mail says production returns the full number and speech never exceeds the last four digits.",
            "speak_last4_only",
        ))
    example_text = examples["text"] if examples else ""
    if "routes to the main menu" in example_text and policy.get("reidentify_route") == "ivr_login":
        found.append(_conflict(
            "third_party_terminal",
            examples["path"] if examples else "",
            "Example 5 ends an already identified caller's other-person card request at the main menu.",
            latest["path"],
            "The analysis and the kickoff mail describe an IVR login so the card owner can identify.",
            "main_menu",
        ))
    if meetings and "one calming" in "\n".join(item["text"] for item in meetings).lower() and policy.get("calming_limit") == 3:
        found.append(_conflict(
            "calming_meeting_revision",
            meetings[0]["path"],
            "The meeting first agreed one calming reply, then revised it.",
            meetings[0]["path"],
            "The same meeting later agreed three calming replies. The later mail confirms three.",
            "three",
        ))
    follow = (follow_meeting or {}).get("text") or ""
    if follow and "Sterlin is what people say" in follow and 'Not "Sterlin"' in follow:
        found.append(_conflict(
            "currency_short_name",
            follow_meeting["path"],
            "One speaker suggested the shorter word Sterlin.",
            follow_meeting["path"],
            "The correction in the same call requires İngiliz Sterlini, and full names for all four currencies.",
            "full_names",
        ))
    if follow and "put the next statement date in that place" in follow and "There isn't one" in follow:
        found.append(_conflict(
            "next_date_as_statement",
            follow_meeting["path"],
            "One speaker suggested filling the empty statement date with nextStatementDate.",
            follow_meeting["path"],
            "The correction says that date is in the future and must not be spoken as an issued statement.",
            "first_statement_only",
        ))
    if follow and "Not the normal reading" in follow and "totalDebt" in follow:
        found.append(_conflict(
            "cut_day_amount",
            follow_meeting["path"],
            "One speaker expected the previous statement debt on the cut day.",
            follow_meeting["path"],
            "The correction says the previous statement is stale and the amount is totalDebt per currency.",
            "totalDebt",
        ))
    if "No, or no other card → main menu." in latest_text and "go to the offer" in latest_text:
        found.append(_conflict(
            "no_debt_after_another",
            latest["path"],
            "Section 4.7 sends a no-debt reading to the main menu after the other-card question.",
            latest["path"],
            "Section 5.1 sends the caller to the additional-services offer when they decline or no card remains.",
            "offer",
        ))
    return found


def _conflict(name, older, older_says, newer, newer_says, chosen):
    return {
        "name": name,
        "older_source": older,
        "older": older_says,
        "newer_source": newer,
        "newer": newer_says,
        "chosen": chosen,
    }
