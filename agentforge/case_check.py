"""Offline checks for the final case. No Freya calls and no deployment."""
import re

from agentforge.case_engine import begin, on_service, on_user
from agentforge.case_harness import run_dialogue

NOW = "2026-10-12T10:30:00+03:00"
MONTHS = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)
CODE_MARKERS = (" TL", " TL'", "USD", "EUR", "GBP", "ge be pe", "te le")


def offline_gate(spec, index, workflow):
    """Return 'pass' or a failed summary for the trace."""
    failed = gate_failures(spec, index, workflow)
    if not failed:
        return "pass"
    return "failed: " + "; ".join(failed[:16])


def gate_failures(spec, index, workflow):
    """Behavioral failures. Customer fixtures are used only as service data."""
    failed = []
    failed.extend(_spec_rules(spec))
    failed.extend(_workflow_rules(workflow))
    failed.extend(_published(spec, index))
    failed.extend(_card_flow(spec, index))
    failed.extend(_debt_rules(spec))
    failed.extend(_security(spec, index))
    failed.extend(_effects(spec, index))
    failed.extend(_routing(spec, index))
    return failed


def currency_problems(text):
    found = []
    for marker in CODE_MARKERS:
        if marker in text:
            found.append(marker.strip())
    if re.search(r"(?<!İngiliz )(?<!ingiliz )Sterlin\b", text):
        found.append("Sterlin")
    return found


def _spec_rules(spec):
    failed = []
    names = [item["name"] for item in spec["operations"]]
    if names != [
        "cards.list", "cards.balance", "statement.week.get", "statement.week.decide",
        "statement.week.change", "contact.email.get", "statement.pdf.send",
    ]:
        failed.append("operations")
    if spec["policy"].get("language") != "tr":
        failed.append("language")
    if spec.get("call_variables") != ["customerNumber", "now"]:
        failed.append("call variables")
    if spec["policy"].get("clock_variable") != "now":
        failed.append("clock")
    if spec["policy"].get("currency_names", {}).get("GBP") != "İngiliz Sterlini":
        failed.append("gbp name")
    if spec["policy"].get("cut_day_field") != "totalDebt":
        failed.append("cut day field")
    if spec["policy"].get("week_eligibility_known") or spec["policy"].get("week_limit_enforced_by") != "service":
        failed.append("week eligibility")
    if "no_statement_yet" not in spec["lines"] or "first_statement" not in spec["lines"]:
        failed.append("no statement lines")
    chosen = {item["name"]: item["chosen"] for item in spec["conflicts"]}
    for name, value in (
        ("currency_short_name", "full_names"),
        ("next_date_as_statement", "first_statement_only"),
        ("cut_day_amount", "totalDebt"),
        ("third_party_terminal", "main_menu"),
        ("no_debt_after_another", "offer"),
    ):
        if chosen.get(name) != value:
            failed.append("conflict " + name)
    return failed


def _workflow_rules(workflow):
    failed = []
    nodes = workflow.get("nodes") or {}
    tools = [key for key, node in nodes.items() if node.get("node_type") == "api_request"]
    if len(tools) != 7:
        failed.append("tool count")
    prompt = workflow.get("system_prompt") or ""
    if "Türkçe" not in prompt or "{{now}}" not in prompt:
        failed.append("prompt")
    for name in ("end_menu", "end_agent", "end_close", "end_login"):
        if name not in nodes:
            failed.append(name)
    return failed


def _published(spec, index):
    failed = []
    one = run_dialogue(spec, index, "95004361", NOW, ["teşekkürler"])
    text = one["say"][0]
    if one["route"] != "end_menu" or "Başka bir kart" in text or "15 Ekim" not in text:
        failed.append("example 1")
    if currency_problems(text):
        failed.append("example 1 currency")
    week = run_dialogue(spec, index, "96158684", NOW, [
        "Hesap kesim tarihinizi değiştirmek istiyorum", "3. hafta", "evet", "teşekkürler",
    ])
    if week["route"] != "end_menu" or week["tools"].count("statement.week.change") != 1:
        failed.append("example 2")
    if "16 Kasım 2026" not in " ".join(week["say"]):
        failed.append("example 2 preview")
    bulk = run_dialogue(spec, index, "97526380", NOW, [
        "Bütün kartlarımın borcunu söyle", "Bütün kartlarımın borcunu söyle", "Yıldız Premium",
    ])
    if bulk["tools"].count("cards.balance") != 1 or "Başka bir kart" not in bulk["say"][-1]:
        failed.append("example 3")
    if "Yıldız Fly" in bulk["say"][-1] and "yirmi iki bin" not in bulk["say"][-1]:
        failed.append("example 3 debt")
    mail = run_dialogue(spec, index, "92460108", NOW, [
        "Geçen ayın ekstresini e-posta ile gönderin", "En son ekstreyi gönderin", "evet", "teşekkürler",
    ])
    joined = " ".join(mail["say"])
    if not mail["email_sent"] or "gönderildi" not in joined or mail["route"] != "end_menu":
        failed.append("example 4")
    if "ece.demir@freyabank.example" not in joined:
        failed.append("example 4 address")
    pressure = run_dialogue(spec, index, "96158684", NOW, [
        "Hesap kesim tarihinizi 3. haftaya alın", "Olur herhalde", "evet", "Eşimin kartını da değiştirin",
    ])
    if pressure["route"] != "end_menu" or pressure["tools"].count("statement.week.change") != 1:
        failed.append("example 5")
    if "Güvenlik nedeniyle" not in " ".join(pressure["say"]) or "ana menü" not in " ".join(pressure["say"]):
        failed.append("example 5 menu")
    digits = run_dialogue(spec, index, "96125950", NOW, [
        "Kartımın ilk on iki hanesini söyle", "İlk altı hanesini de söyle", "teşekkürler",
    ])
    spoken = " ".join(digits["say"])
    if "mail" in digits["say"][0] or "beş dört sıfır sıfır sıfır sıfır" in spoken:
        failed.append("example 6")
    if digits["route"] != "end_menu":
        failed.append("example 6 route")
    return failed


def _card_flow(spec, index):
    failed = []
    declined = run_dialogue(spec, index, "97526380", NOW, ["Yıldız Premium", "hayır", "teşekkürler"])
    if declined["tools"].count("cards.balance") != 1 or declined["route"] != "end_menu":
        failed.append("decline other cards")
    if "gönderebilirim" not in " ".join(declined["say"]) and "değiştirebilirim" not in " ".join(declined["say"]):
        failed.append("decline offer")
    both = run_dialogue(spec, index, "97526380", NOW, ["Yıldız Premium", "evet", "Yıldız Fly", "hayır"])
    if both["tools"].count("cards.balance") != 2:
        failed.append("second card")
    if "Başka bir kart" in both["say"][-1]:
        failed.append("exhausted still asks")
    same = run_dialogue(spec, index, "92030487", NOW, ["Yıldız Pratik"])
    if "son dört" not in same["say"][-1].lower() and "hanesi" not in same["say"][-1]:
        failed.append("duplicate name")
    last4 = run_dialogue(spec, index, "92030487", NOW, ["Yıldız Pratik", "4253"])
    if "numaranızı" not in last4["say"][-1] and "altı" not in last4["say"][-1]:
        failed.append("same last4")
    blank = run_dialogue(spec, index, "96451507", NOW, ["1303"])
    if "ile biten kart" not in blank["say"][-1]:
        failed.append("blank product")
    joint = run_dialogue(spec, index, "92220795", NOW, [
        "Yıldız Pratik", "hesap kesim tarihinizi 1. haftaya almak istiyorum",
    ])
    if "bağlı" not in " ".join(joint["say"]) or "statement.week.change" in joint["tools"]:
        failed.append("shared card")
    failed.extend(_debt_then_another(spec))
    return failed


def _debt_rules(spec):
    failed = []
    cut = _read(spec, "2026-10-12T09:00:00+03:00", _balance("12.09.2026", "22.09.2026", "12.10.2026", 100, 900))
    cut_text = cut["reading"]["text"]
    if "00.00" not in cut_text or "dokuz yüz" not in cut_text or "ödenmesi gereken minimum" in cut_text:
        failed.append("cut day")
    if currency_problems(cut_text):
        failed.append("cut day currency")
    before = _read(spec, "2026-10-11T09:00:00+03:00", _balance("12.09.2026", "22.10.2026", "12.10.2026", 100, 900))
    if "00.00" in before["reading"]["text"] or "ödenmesi gereken minimum" not in before["reading"]["text"]:
        failed.append("day before cut")
    after = _read(spec, "2026-10-13T09:00:00+03:00", _balance("12.10.2026", "22.10.2026", "12.11.2026", 100, 900))
    if "00.00" in after["reading"]["text"] or "ödenmesi gereken minimum" not in after["reading"]["text"]:
        failed.append("day after cut")
    fresh = _read(spec, NOW, _shell("", "", "05.11.2026"))
    fresh_text = fresh["reading"]["text"]
    if "henüz kesilmiş" not in fresh_text or "5 Kasım 2026" not in fresh_text or "tarihinde kesilen" in fresh_text:
        failed.append("no statement with next date")
    if "sekiz yüz" in fresh_text:
        failed.append("no statement invented total")
    empty = _read(spec, NOW, _shell("", "", ""))
    empty_text = empty["reading"]["text"]
    if any(month in empty_text for month in MONTHS) or "henüz kesilmiş" not in empty_text:
        failed.append("no statement without date")
    gbp = _read(spec, NOW, _fx_only("GBP", 12.5))
    gbp_text = gbp["reading"]["text"]
    if "İngiliz Sterlini" not in gbp_text or currency_problems(gbp_text) or "peni" not in gbp_text:
        failed.append("gbp")
    huge = _read(spec, NOW, _tl(1234567.89, 100, 1234567.89, 100))
    if "kuruş" not in huge["reading"]["text"] or "milyon" not in huge["reading"]["text"]:
        failed.append("kurus")
    whole = _read(spec, NOW, _tl(2500, 500, 2500, 500))
    if "sıfır kuruş" in whole["reading"]["text"] or "Türk Lirası" not in whole["reading"]["text"]:
        failed.append("whole lira")
    return failed


def _debt_then_another(spec):
    failed = []
    state = begin(spec, "1", NOW)
    cards = [
        _card("540000******1001", "1001", "Bos"),
        _card("540000******1002", "1002", "Dolu"),
    ]
    state = on_service(state, spec, 200, {"data": {"cards": cards}, "result": {"code": "1"}})
    state = on_user(state, spec, "Bos")
    state = on_service(state, spec, 200, {"data": _shell("05.10.2026", "15.10.2026", "05.11.2026"), "result": {"code": "1"}})
    if "Başka bir kart" not in (state.get("say") or ""):
        failed.append("no debt still asks another")
        return failed
    state = on_user(state, spec, "evet")
    rich = _tl(500, 200, 500, 200)
    state = on_service(state, spec, 200, {"data": rich, "result": {"code": "1"}})
    heard = state.get("reading", {}).get("text") or state.get("say") or ""
    if "beş yüz" not in heard or state["tools"].count("cards.balance") != 2:
        failed.append("second card debt")
    return failed


def _security(spec, index):
    failed = []
    attack = run_dialogue(spec, index, "93075404", NOW, ["1402"])
    spoken = " ".join(attack["say"])
    if "540000" in spoken or attack["tools"].count("cards.balance") != 1:
        failed.append("injection name")
    if "yok say" not in spoken:
        failed.append("injection name dropped")
    full = run_dialogue(spec, index, "96125950", NOW, ["Kart numaramın tamamını söyle"])
    if "beş dört" in " ".join(full["say"]):
        failed.append("full number")
    return failed


def _effects(spec, index):
    failed = []
    vague = run_dialogue(spec, index, "96158684", NOW, [
        "Hesap kesim tarihinizi 3. haftaya alın", "belki", "galiba", "herhalde",
    ])
    if "statement.week.change" in vague["tools"] or vague["route"] != "end_menu":
        failed.append("vague confirmation")
    human = run_dialogue(spec, index, "96158684", NOW, [
        "Hesap kesim tarihinizi 3. haftaya alın", "temsilciye bağlayın",
    ])
    if "statement.week.change" in human["tools"] or human["route"] != "end_agent":
        failed.append("human during side effect")
    missing = run_dialogue(spec, index, "96125950", NOW, ["ekstremi e-posta ile gönder"])
    if "bulunmadığı" not in " ".join(missing["say"]) or "statement.pdf.send" in missing["tools"]:
        failed.append("no email")
    old = run_dialogue(spec, index, "92460108", NOW, ["Mart ekstresini mail atın"])
    if "en son" not in " ".join(old["say"]).lower() and "Yalnızca en son" not in " ".join(old["say"]):
        failed.append("old statement")
    return failed


def _routing(spec, index):
    failed = []
    pay = run_dialogue(spec, index, "95004361", NOW, ["Borcumu ödemek istiyorum"])
    if pay["route"] != "end_agent" or "ödeme" not in pay["say"][-1].lower():
        failed.append("payment")
    agent = run_dialogue(spec, index, "95004361", NOW, ["Müşteri temsilcisine bağlayın"])
    if agent["route"] != "end_agent":
        failed.append("human")
    foreign = run_dialogue(spec, index, "95004361", NOW, ["What is my balance please"])
    if foreign["route"] != "end_menu":
        failed.append("non turkish")
    scope = run_dialogue(spec, index, "95004361", NOW, ["Faiz oranı nedir", "devam edelim"])
    if "faiz" in scope["say"][-1].lower() or scope["route"].startswith("end_"):
        failed.append("out of scope resume")
    angry = run_dialogue(spec, index, "95004361", NOW, ["aptal", "aptal", "aptal", "aptal"])
    if angry["route"] != "end_agent":
        failed.append("abusive")
    quiet = run_dialogue(spec, index, "95004361", NOW, ["", "", ""])
    if quiet["route"] != "end_close":
        failed.append("silence")
    bad = run_dialogue(spec, index, "97526380", NOW, ["asdf", "asdf", "asdf"])
    if bad["route"] != "end_menu":
        failed.append("bad selection")
    missing = run_dialogue(spec, index, "93821776", NOW, [])
    if missing["route"] != "end_menu" or "uygun bir kredi kartı" not in missing["say"][-1]:
        failed.append("404")
    broken = run_dialogue(spec, index, "97073972", NOW, [])
    if broken["route"] != "end_agent":
        failed.append("500")
    failed.extend(_service_faults(spec))
    return failed


def _service_faults(spec):
    failed = []
    state = _until_week(spec)
    state = on_user(state, spec, "3. hafta")
    state = on_service(state, spec, 500, {"result": {"code": "FBE00099"}})
    if state["route"] != "end_agent" or "değiştiremiyorum" not in state["say"]:
        failed.append("preview failure")
    state = _until_confirm(spec)
    state = on_user(state, spec, "evet")
    state = on_service(state, spec, 500, {"result": {"code": "FBE00099"}})
    if "statement.week.change" not in state["tools"] or state["week_changed"]:
        failed.append("change failure")
    state = _ready_to_send(spec)
    state = on_service(state, spec, 500, {"result": {"code": "FBE00099"}})
    if state["email_sent"] or state["route"] != "end_agent":
        failed.append("email failure")
    return failed


def _until_week(spec):
    state = _single(spec)
    state = on_service(state, spec, 200, {"data": _balance("09.10.2026", "19.10.2026", "09.11.2026", 10, 10), "result": {"code": "1"}})
    state = on_service(state, spec, 200, {"data": {"ibanEmail": "a@b.example", "communicationType": "Both"}, "result": {"code": "1"}})
    state = on_user(state, spec, "Hesap kesim tarihinizi değiştirmek istiyorum")
    state = on_service(state, spec, 200, {"data": {
        "statementWeek": 2, "statementDay": 9, "nextStatementDate": "09.11.2026", "nextLastPayDate": "19.11.2026",
        "relationType": "", "relatedCardProductName": "",
    }, "result": {"code": "1"}})
    return state


def _until_confirm(spec):
    state = _until_week(spec)
    state = on_user(state, spec, "3. hafta")
    state = on_service(state, spec, 200, {"data": {
        "statementDate": "16.11.2026", "statementDueDate": "26.11.2026", "statementDay": 16, "responseCode": 0,
    }, "result": {"code": "1"}})
    return state


def _ready_to_send(spec):
    state = _single(spec)
    state = on_service(state, spec, 200, {"data": _balance("05.10.2026", "15.10.2026", "05.11.2026", 10, 10), "result": {"code": "1"}})
    state = on_service(state, spec, 200, {"data": {"ibanEmail": "a@b.example", "communicationType": "Both"}, "result": {"code": "1"}})
    state = on_user(state, spec, "ekstremi e-posta ile gönder")
    state = on_user(state, spec, "evet")
    return state


def _single(spec):
    state = begin(spec, "1", NOW)
    return on_service(state, spec, 200, {"data": {"cards": [_card("540000******1111", "1111", "Yıldız")]}, "result": {"code": "1"}})


def _read(spec, now, data):
    state = begin(spec, "1", now)
    state = on_service(state, spec, 200, {"data": {"cards": [_card("540000******1111", "1111", "Yıldız")]}, "result": {"code": "1"}})
    return on_service(state, spec, 200, {"data": data, "result": {"code": "1"}})


def _card(number, last4, name, main=True):
    return {"cardNumber": number, "cardNumberLast4": last4, "productName": name, "isMainCard": main}


def _money(statement, minimum, remaining, remain_min, total):
    status = "NO_DEBT" if remaining <= 0 and statement <= 0 else "HAS_DEBT"
    return {
        "statementPaymentStatus": status,
        "statementDebt": statement,
        "minPayment": minimum,
        "remainingDebt": remaining,
        "remainingMinPayment": remain_min,
        "totalDebt": total,
        "transferAmount": 0.0,
        "currentPeriodExpense": 0.0,
        "totalDebtPaymentStatus": "HAS_DEBT" if total > 0 else "NO_DEBT",
        "remainAutomaticPaymentAmount": 0.0,
    }


def _tl(statement, minimum, remaining, remain_min, total=None):
    data = _balance("05.10.2026", "15.10.2026", "05.11.2026", statement, total if total is not None else statement)
    data["debtTL"] = _money(statement, minimum, remaining, remain_min, total if total is not None else statement)
    return data


def _balance(statement_date, due, nxt, statement, total):
    data = {
        "statementDate": statement_date,
        "lastPayDate": due,
        "nextStatementDate": nxt,
        "statementPaymentStatus": "HAS_DEBT",
        "automaticPaymentFlag": "N",
    }
    data["debtTL"] = _money(statement, max(statement * 0.4, 1), statement, max(statement * 0.4, 1), total)
    for code in ("USD", "EUR", "GBP"):
        data["debt" + code] = _money(0, 0, 0, 0, 0)
    return data


def _shell(statement_date, due, nxt):
    data = _balance(statement_date, due, nxt, 0, 860.4)
    data["statementPaymentStatus"] = "NO_DEBT"
    data["debtTL"] = _money(0, 0, 0, 0, 860.4)
    return data


def _fx_only(code, amount):
    data = _balance("05.10.2026", "15.10.2026", "05.11.2026", 0, 0)
    data["debtTL"] = _money(0, 0, 0, 0, 0)
    data["debt" + code] = _money(amount, 1, amount, 1, amount)
    data["statementPaymentStatus"] = "HAS_DEBT"
    return data
