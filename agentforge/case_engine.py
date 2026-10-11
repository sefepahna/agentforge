"""Decision loop for a case spec. Service strings stay data."""
import re
from datetime import date

from agentforge.case_speech import copula, digits_spoken, fill_money, speak_date, speak_money, tr_lower, week_list

WEEKS = (1, 2, 3, 4)
WORD_DIGITS = {
    "sifir": "0", "sıfır": "0", "bir": "1", "iki": "2", "uc": "3", "üç": "3",
    "dort": "4", "dört": "4", "bes": "5", "beş": "5", "alti": "6", "altı": "6",
    "yedi": "7", "sekiz": "8", "dokuz": "9",
}
WEEK_WORDS = {
    "birinci": 1, "ilk": 1, "ikinci": 2, "ucuncu": 3, "üçüncü": 3,
    "dorduncu": 4, "dördüncü": 4,
}
HEDGES = ("herhalde", "belki", "sanirim", "sanırım", "galiba", "bilmiyorum")


def request_body(state, spec):
    """Build the contract envelope for the pending service call."""
    pending = state.get("pending") or ""
    data = {}
    if pending in ("cards.list", "contact.email.get", "statement.pdf.send"):
        data["customerNo"] = state.get("customer_number") or ""
    if pending == "cards.list":
        data["aiFlow"] = _flow_name(spec)
    if pending == "contact.email.get":
        data["intAddressInfoType"] = "E"
    if pending in ("cards.balance", "statement.week.get", "statement.week.decide", "statement.week.change", "statement.pdf.send"):
        data["cardNumber"] = state.get("selected") or ""
    if pending in ("statement.week.decide", "statement.week.change"):
        data["newStatementWeek"] = str(state.get("chosen_week") or "")
        data["statementDay"] = (state.get("week") or {}).get("statementDay")
    if pending == "statement.pdf.send":
        data["currencyType"] = _send_currency(state, spec)
        data["statementDate"] = str((state.get("balance") or {}).get("statementDate") or "")
        data["emailAddress"] = state.get("email") or ""
    envelope = {}
    envelope["data"] = data
    call = {}
    call["ani"] = ""
    call["lang"] = spec["policy"].get("language") or "tr"
    envelope["call"] = call
    return envelope


def _flow_name(spec):
    for operation in spec.get("operations") or []:
        if operation.get("name") == "cards.list" and "CardOps" in (operation.get("request_example") or ""):
            return "CardOps"
    return ""


def _send_currency(state, spec):
    data = state.get("balance") or {}
    for block in spec.get("balance_blocks") or []:
        raw = data.get(block["field"])
        if isinstance(raw, dict) and _kind(block["code"], raw) != "none":
            return block["code"]
    blocks = spec.get("balance_blocks") or []
    if blocks:
        return blocks[0]["code"]
    return ""


def begin(spec, customer_number, now):
    state = {}
    state["customer_number"] = "" if customer_number is None else str(customer_number).strip()
    state["now"] = "" if now is None else str(now).strip()
    state["phase"] = "boot"
    state["route"] = "api_cards_list"
    state["say"] = ""
    state["last_say"] = ""
    state["tries"] = 0
    state["silence"] = 0
    state["calming"] = 0
    state["cards"] = []
    state["ineligible"] = []
    state["candidates"] = []
    state["heard"] = []
    state["selected"] = ""
    state["announce_reading"] = False
    state["tools"] = []
    state["side_effect"] = ""
    state["pending"] = "cards.list"
    state["week_changed"] = False
    state["email_sent"] = False
    state["email"] = ""
    state["balance"] = {}
    state["week"] = {}
    state["preview"] = {}
    state["facts"] = {}
    state["reading"] = ""
    state["paraphrase"] = ""
    state["chosen_week"] = ""
    if not state["customer_number"] or not state["now"]:
        return _end(state, "end_agent", spec["lines"]["service_error"])
    state["tools"] = ["cards.list"]
    return state


def on_service(state, spec, status, body):
    pending = state.get("pending") or ""
    payload = body if isinstance(body, dict) else {}
    code = str(((payload.get("result") or {}).get("code")) or "")
    if pending == "cards.list":
        return _after_list(state, spec, status, payload, code)
    if pending == "cards.balance":
        return _after_balance(state, spec, status, payload)
    if pending == "contact.email.get":
        return _after_email(state, spec, status, payload)
    if pending == "statement.week.get":
        return _after_week(state, spec, status, payload)
    if pending == "statement.week.decide":
        return _after_decide(state, spec, status, payload)
    if pending == "statement.week.change":
        return _after_change(state, spec, status, payload)
    if pending == "statement.pdf.send":
        return _after_send(state, spec, status, payload)
    return _service_fail(state, spec, pending)


def on_user(state, spec, text):
    return _dispatch(state, spec, _classify(text, state))


def on_intent(state, spec, intent, extra=None):
    parsed = {"intent": intent, "text": "", "digits": "", "week": "", "name": ""}
    if isinstance(extra, dict):
        parsed.update(extra)
    parsed["intent"] = intent
    return _dispatch(state, spec, parsed)


def _dispatch(state, spec, parsed):
    if state.get("route", "").startswith("end_"):
        return state
    handled = _global(state, spec, parsed)
    if handled is not None:
        return handled
    phase = state.get("phase") or ""
    if phase == "select":
        return _on_select(state, spec, parsed)
    if phase in ("last4", "last6", "full"):
        return _on_digits(state, spec, parsed)
    if phase == "another":
        return _on_another(state, spec, parsed)
    if phase == "offer":
        return _on_offer(state, spec, parsed)
    if phase == "email_confirm":
        return _on_email_confirm(state, spec, parsed)
    if phase == "week_pick":
        return _on_week_pick(state, spec, parsed)
    if phase == "week_confirm":
        return _on_week_confirm(state, spec, parsed)
    if phase == "scope_confirm":
        return _on_scope(state, spec, parsed)
    if phase == "after_effect":
        if state.get("week_changed") and parsed.get("intent") in ("week", "week_change"):
            yearly = spec["lines"].get("week_yearly") or ""
            return _end(state, "end_menu", (yearly + " " + spec["lines"]["menu_normal"]).strip())
        return _end(state, "end_menu", spec["lines"]["menu_normal"])


def _global(state, spec, parsed):
    intent = parsed.get("intent") or ""
    if intent == "silence":
        state["silence"] = int(state.get("silence") or 0) + 1
        if state["silence"] >= int(spec["policy"]["silence_limit"] or 3):
            return _end(state, "end_close", spec["lines"]["silence_end"])
        state["say"] = state.get("last_say") or state.get("say") or ""
        state["route"] = "talk"
        return state
    if intent == "repeat":
        state["say"] = state.get("last_say") or state.get("say") or ""
        state["route"] = "talk"
        return state
    if intent == "agent":
        return _end(state, "end_agent", spec["lines"]["agent"])
    if intent == "pay":
        return _end(state, "end_agent", spec["lines"]["pay_agent"])
    if intent == "dispute":
        return _end(state, "end_agent", spec["lines"]["dispute_agent"])
    if intent == "non_turkish":
        return _end(state, "end_menu", spec["lines"]["non_turkish"])
    if intent == "abusive":
        limit = int(spec["policy"]["calming_limit"] or 3)
        if int(state.get("calming") or 0) >= limit:
            return _end(state, "end_agent", spec["lines"]["agent"])
        state["calming"] = int(state.get("calming") or 0) + 1
        state["say"] = state.get("last_say") or state.get("say") or ""
        state["route"] = "talk"
        return state
    if intent == "third_party":
        route = spec["policy"].get("third_party_route") or "main_menu"
        target = "end_login" if route == "ivr_login" else "end_menu"
        text = _paraphrase(spec, "third_party")
        if target == "end_menu":
            text = (text + " " + spec["lines"]["menu_normal"]).strip()
        return _end(state, target, text)
    if intent == "reidentify" and spec["policy"].get("reidentify_route") == "ivr_login":
        return _end(state, "end_login", spec["lines"]["menu_normal"])
    if intent == "reveal":
        card = _selected(state)
        spoken = digits_spoken(card.get("last4") or "")
        state["say"] = "Sonu " + spoken + " ile biten kart"
        state["last_say"] = state["say"]
        state["route"] = "talk"
        state["paraphrase"] = ""
        return state
    if intent == "out_of_scope" and state.get("phase") != "scope_confirm":
        state["return_phase"] = state.get("phase") or ""
        state["return_say"] = state.get("last_say") or ""
        return _ask(state, spec["lines"]["out_of_scope_ask"], "scope_confirm")
    return None


def _after_list(state, spec, status, payload, code):
    if int(status) == 404 and code == "FB_IVR_CHANNEL_102":
        return _end(state, "end_menu", spec["lines"]["no_card"])
    if int(status) != 200:
        return _service_fail(state, spec, "cards.list")
    cards = []
    ineligible = []
    for card in ((payload.get("data") or {}).get("cards") or []):
        if not isinstance(card, dict):
            continue
        item = {}
        item["cardNumber"] = str(card.get("cardNumber") or "")
        item["last4"] = str(card.get("cardNumberLast4") or "")
        item["productName"] = str(card.get("productName") or "")
        item["isMainCard"] = card.get("isMainCard") is not False
        if item["isMainCard"]:
            cards.append(item)
        else:
            ineligible.append(item)
    state["cards"] = cards
    state["ineligible"] = ineligible
    if not cards:
        return _end(state, "end_menu", spec["lines"]["no_card"])
    if len(cards) == 1 and spec["policy"].get("single_card_skips_selection"):
        state["selected"] = cards[0]["cardNumber"]
        return _api(state, "cards.balance")
    return _ask(state, _select_line(spec, cards), "select")


def _after_balance(state, spec, status, payload):
    if int(status) != 200 or not isinstance(payload.get("data"), dict):
        return _service_fail(state, spec, "cards.balance")
    state["balance"] = payload["data"]
    _mark_heard(state)
    state["reading"] = _reading(state, spec)
    state["facts"] = state["reading"]["facts"]
    unread = _unread(state)
    if unread and len(state.get("cards") or []) > 1:
        text = state["reading"]["text"] + " " + spec["lines"]["another_card"]
        state["announce_reading"] = False
        return _ask(state, text, "another")
    state["announce_reading"] = True
    return _api(state, "contact.email.get")


def _after_email(state, spec, status, payload):
    if int(status) != 200 or not isinstance(payload.get("data"), dict):
        text = (state.get("reading") or {}).get("text") or ""
        if text:
            state["say"] = text + " " + spec["lines"]["service_error"]
        return _end(state, "end_agent", state.get("say") or spec["lines"]["service_error"])
    data = payload["data"]
    email = str(data.get("ibanEmail") or "").strip()
    spoken = str(data.get("ttsEmail") or "").strip() or email
    phone_only = str(data.get("communicationType") or "") == "Phone"
    state["email"] = "" if phone_only else email
    state["email_speech"] = "" if phone_only else spoken
    offer = _offer_line(state, spec)
    prefix = (state.get("reading") or {}).get("text") or ""
    if state.get("announce_reading") and prefix:
        text = prefix + " " + offer
        state["announce_reading"] = False
    else:
        text = offer
    follow = state.get("follow") or ""
    state["follow"] = ""
    state = _ask(state, text.strip(), "offer")
    if follow:
        parsed = {"intent": follow, "week": state.get("queued_week") or "", "text": "", "digits": "", "name": ""}
        return _on_offer(state, spec, parsed)
    return state


def _after_week(state, spec, status, payload):
    if int(status) != 200 or not isinstance(payload.get("data"), dict):
        return _end(state, "end_agent", spec["lines"]["week_error"])
    state["week"] = payload["data"]
    current = int(state["week"].get("statementWeek") or 0)
    queued = str(state.get("queued_week") or "")
    allowed = [str(item) for item in WEEKS if item != current]
    if queued and queued in allowed:
        state["chosen_week"] = queued
        state["queued_week"] = ""
        state["week_intro"] = _week_current(spec, state)
        return _api(state, "statement.week.decide")
    text = _week_current(spec, state) + " " + _week_options(spec, current)
    relation = str(state["week"].get("relationType") or "")
    related = str(state["week"].get("relatedCardProductName") or "")
    joint = _joint(spec, relation, related)
    if joint:
        text = joint + " " + text
    return _ask(state, text, "week_pick")


def _after_decide(state, spec, status, payload):
    if int(status) != 200 or not isinstance(payload.get("data"), dict):
        return _end(state, "end_agent", spec["lines"]["week_error"])
    state["preview"] = payload["data"]
    text = _week_confirm(spec, state)
    intro = state.get("week_intro") or ""
    if intro:
        stated = intro.split("Hesap kesim tarihinizi değiştirmek ister misiniz?")[0].strip()
        text = (stated + " " + text).strip()
        state["week_intro"] = ""
    relation = str((state.get("week") or {}).get("relationType") or "")
    related = str((state.get("week") or {}).get("relatedCardProductName") or "")
    joint = _joint(spec, relation, related)
    if joint:
        text = joint + " " + text
    return _ask(state, text, "week_confirm")


def _after_change(state, spec, status, payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    ok = int(status) == 200 and isinstance(data, dict) and str(data.get("exitState")) == "OK"
    if not ok:
        return _end(state, "end_agent", spec["lines"]["week_error"])
    state["week_changed"] = True
    state["side_effect"] = "statement.week.change"
    return _ask(state, _week_done(spec, state), "after_effect")


def _after_send(state, spec, status, payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    ok = int(status) == 200 and isinstance(data, dict) and str(data.get("exitState")) == "DONE"
    if not ok:
        return _end(state, "end_agent", spec["lines"]["service_error"])
    state["email_sent"] = True
    state["side_effect"] = "statement.pdf.send"
    return _ask(state, spec["lines"]["email_sent"], "after_effect")


def _on_select(state, spec, parsed):
    if parsed.get("intent") == "all_cards" and spec["policy"].get("refuse_all_cards"):
        return _miss(state, spec, _select_line(spec, state.get("cards") or []))
    if parsed.get("intent") in ("week_change", "email", "email_old"):
        return _miss(state, spec, state.get("last_say") or "")
    pool = _unread(state) or state.get("cards") or []
    chosen = _match_cards(pool, parsed)
    if not chosen:
        chosen = _match_cards(state.get("cards") or [], parsed)
    if len(chosen) == 1:
        state["selected"] = chosen[0]["cardNumber"]
        return _api(state, "cards.balance")
    if len(chosen) > 1:
        return _narrow(state, spec, chosen)
    if _match_cards(state.get("ineligible") or [], parsed):
        return _miss(state, spec, _ineligible_line(spec, state.get("cards") or []))
    return _miss(state, spec, _select_line(spec, state.get("cards") or []))


def _on_digits(state, spec, parsed):
    digits = parsed.get("digits") or ""
    chosen = _filter_digits(state.get("candidates") or [], digits, state.get("phase") or "")
    if len(chosen) == 1:
        state["selected"] = chosen[0]["cardNumber"]
        state["candidates"] = []
        return _api(state, "cards.balance")
    if len(chosen) > 1:
        return _narrow(state, spec, chosen)
    return _miss(state, spec, state.get("last_say") or "")


def _on_another(state, spec, parsed):
    if parsed.get("intent") == "all_cards" and spec["policy"].get("refuse_all_cards"):
        return _miss(state, spec, spec["lines"]["another_card"])
    if parsed.get("intent") in ("week", "week_change", "email", "email_old"):
        state["follow"] = parsed.get("intent")
        state["queued_week"] = parsed.get("week") or ""
        state["announce_reading"] = False
        return _api(state, "contact.email.get")
    if parsed.get("intent") in ("no", "thanks"):
        state["reading_kept"] = True
        state["announce_reading"] = False
        return _api(state, "contact.email.get")
    unread = _unread(state)
    if parsed.get("intent") == "yes":
        if len(unread) == 1:
            state["selected"] = unread[0]["cardNumber"]
            return _api(state, "cards.balance")
        return _ask(state, _select_line(spec, unread or state.get("cards") or []), "select")
    chosen = _match_cards(unread or state.get("cards") or [], parsed)
    if len(chosen) == 1:
        state["selected"] = chosen[0]["cardNumber"]
        return _api(state, "cards.balance")
    if _match_cards(state.get("ineligible") or [], parsed):
        return _miss(state, spec, _ineligible_line(spec, unread or state.get("cards") or []))
    return _miss(state, spec, spec["lines"]["another_card"])


def _on_offer(state, spec, parsed):
    intent = parsed.get("intent") or ""
    if intent in ("thanks", "no"):
        return _end(state, "end_menu", spec["lines"]["menu_normal"])
    if intent == "email_old":
        state["paraphrase"] = "latest_statement"
        return _ask(state, _paraphrase(spec, "latest_statement"), "offer")
    if intent == "email":
        if not state.get("email"):
            follow = spec["lines"]["no_email"]
            if spec["policy"].get("offer_week_when_eligibility_unknown"):
                follow = follow + " " + spec["lines"]["offer_week"]
            return _ask(state, follow, "offer")
        return _ask(state, _email_confirm_line(spec, state.get("email_speech") or state.get("email") or ""), "email_confirm")
    if intent in ("week_change", "week"):
        if state.get("week_changed"):
            yearly = spec["lines"].get("week_yearly") or ""
            return _end(state, "end_menu", (yearly + " " + spec["lines"]["menu_normal"]).strip())
        week = parsed.get("week") or ""
        state["queued_week"] = week
        return _api(state, "statement.week.get")
    return _miss(state, spec, state.get("last_say") or "")


def _on_email_confirm(state, spec, parsed):
    intent = parsed.get("intent") or ""
    if intent == "yes" and spec["policy"].get("side_effect_requires_clear_yes"):
        return _api(state, "statement.pdf.send")
    if intent == "vague":
        return _miss(state, spec, _email_confirm_line(spec, state.get("email_speech") or state.get("email") or ""))
    if intent == "no":
        extra = ""
        if parsed.get("address_rejected"):
            extra = _paraphrase(spec, "address_change") + " "
        return _end(state, "end_menu", (extra + spec["lines"]["menu_normal"]).strip())
    return _miss(state, spec, _email_confirm_line(spec, state.get("email_speech") or state.get("email") or ""))


def _on_week_pick(state, spec, parsed):
    if parsed.get("intent") == "no":
        return _end(state, "end_menu", spec["lines"]["menu_normal"])
    week = parsed.get("week") or ""
    current = str((state.get("week") or {}).get("statementWeek") or "")
    if not week:
        return _miss(state, spec, state.get("last_say") or "")
    if week == current:
        return _miss(state, spec, _week_options(spec, int(current or 0)))
    allowed = [str(item) for item in WEEKS if str(item) != current]
    if week not in allowed:
        return _miss(state, spec, _week_options(spec, int(current or 0)))
    state["chosen_week"] = week
    return _api(state, "statement.week.decide")


def _on_week_confirm(state, spec, parsed):
    intent = parsed.get("intent") or ""
    if intent == "yes" and not state.get("week_changed"):
        return _api(state, "statement.week.change")
    if intent == "vague":
        return _miss(state, spec, state.get("last_say") or "")
    if intent == "no":
        return _end(state, "end_menu", spec["lines"]["menu_normal"])
    return _miss(state, spec, state.get("last_say") or "")


def _on_scope(state, spec, parsed):
    intent = parsed.get("intent") or ""
    if intent == "yes":
        return _end(state, "end_menu", spec["lines"]["menu_normal"])
    if intent in ("no", "continue"):
        phase = state.get("return_phase") or "offer"
        say = state.get("return_say") or state.get("last_say") or ""
        return _ask(state, say, phase)
    return _miss(state, spec, spec["lines"]["out_of_scope_ask"])


def _narrow(state, spec, chosen):
    state["candidates"] = chosen
    last4s = []
    for card in chosen:
        if card["last4"] not in last4s:
            last4s.append(card["last4"])
    if len(last4s) > 1:
        name = chosen[0]["productName"].strip() or "Kart"
        line = spec["lines"]["same_name"]
        line = re.sub(r"[A-ZÇĞİÖŞÜa-zçğıöşü]+ isimli", name + " isimli", line, count=1)
        return _ask(state, line, "last4")
    if _can_split(chosen, 6):
        spoken = digits_spoken(last4s[0])
        line = re.sub(r"\d{4}", spoken, spec["lines"]["same_last4"], count=1)
        return _ask(state, line, "last6")
    return _ask(state, spec["lines"]["same_last6"], "full")


def _can_split(cards, count):
    tails = []
    for card in cards:
        tail = _known_tail(card["cardNumber"], count)
        if not tail:
            return False
        tails.append(tail)
    return len(set(tails)) > 1


def _known_tail(number, count):
    tail = str(number)[-count:]
    if "*" in tail or len(tail) < count:
        return ""
    return tail


def _filter_digits(cards, digits, phase):
    if phase == "last4":
        return [card for card in cards if card["last4"] == digits[-4:]] if len(digits) >= 4 else []
    if phase == "last6":
        found = []
        for card in cards:
            tail = _known_tail(card["cardNumber"], 6)
            if tail and digits.endswith(tail):
                found.append(card)
            elif not tail and digits[-4:] == card["last4"]:
                found.append(card)
        return found
    found = []
    for card in cards:
        if _full_match(card["cardNumber"], digits):
            found.append(card)
    return found


def _full_match(stored, spoken):
    if len(spoken) != len(stored) or not spoken.isdigit():
        return False
    for index, char in enumerate(stored):
        if char == "*":
            continue
        if spoken[index] != char:
            return False
    return True


def _match_cards(cards, parsed):
    digits = parsed.get("digits") or ""
    if len(digits) >= 12:
        return [card for card in cards if _full_match(card["cardNumber"], digits)]
    if len(digits) == 4:
        return [card for card in cards if card["last4"] == digits]
    name = _fold(parsed.get("name") or "")
    if not name:
        return []
    found = []
    for card in cards:
        label = _fold(card["productName"])
        if label and (label in name or name in label):
            found.append(card)
    return found


def _fold(text):
    return tr_lower(text).translate(str.maketrans("çğıöşüı", "cgiosui"))


def _classify(text, state):
    raw = " ".join(str(text or "").strip().split())
    folded = tr_lower(raw)
    parsed = {"intent": "", "text": raw, "digits": _digits(folded), "week": "", "name": raw, "address_rejected": False}
    if not folded:
        parsed["intent"] = "silence"
        return parsed
    if any(hedge in folded for hedge in HEDGES):
        parsed["intent"] = "vague"
        return parsed
    if any(word in folded for word in ("temsilci", "yetkili", "operator", "operatör", "insanla")):
        parsed["intent"] = "agent"
        return parsed
    if _abusive(folded):
        parsed["intent"] = "abusive"
        return parsed
    if _reveal(folded):
        parsed["intent"] = "reveal"
        return parsed
    if _reidentify(folded):
        parsed["intent"] = "reidentify"
        return parsed
    if _other_person(folded):
        parsed["intent"] = "third_party"
        return parsed
    if re.search(r"\b(ode|öde)", folded) and "ogren" not in folded and "öğren" not in folded:
        parsed["intent"] = "pay"
        return parsed
    if re.search(r"\bevet\b", folded):
        parsed["intent"] = "yes"
        return parsed
    if any(word in folded for word in ("yanlis", "yanlış", "gorunmuyor", "görünmüyor", "yansimiyor", "yansımıyor")):
        parsed["intent"] = "dispute"
        return parsed
    if any(word in folded for word in ("butun kart", "bütün kart", "tum kart", "tüm kart", "hepsi")):
        parsed["intent"] = "all_cards"
        return parsed
    if any(word in folded for word in ("tekrar", "yeniden", "anlayamadim", "anlayamadım")):
        parsed["intent"] = "repeat"
        return parsed
    if any(word in folded for word in ("tesekkur", "teşekkür", "sagol", "sağol", "gorusuruz", "görüşürüz")):
        parsed["intent"] = "thanks"
        return parsed
    if re.search(r"\b(hayir|hayır)\b", folded) or "istemiyorum" in folded or "vazgec" in folded or "vazgeç" in folded:
        parsed["intent"] = "no"
        if "adres" in folded:
            parsed["address_rejected"] = True
        return parsed
    if "devam" in folded:
        parsed["intent"] = "continue"
        return parsed
    week = _week(folded)
    if week:
        parsed["week"] = week
    if any(word in folded for word in ("mail", "e-posta", "eposta", "e posta")) or ("gonder" in folded or "gönder" in folded):
        if any(word in folded for word in ("gecen ay", "geçen ay", "eski", "onceki", "önceki", "mart")):
            parsed["intent"] = "email_old"
        else:
            parsed["intent"] = "email"
        return parsed
    if week and ("hafta" in folded or "degis" in folded or "değiş" in folded or state.get("phase") == "week_pick"):
        parsed["intent"] = "week"
        return parsed
    if any(word in folded for word in ("hafta", "ekstre tarihi", "hesap kesim")) and (
        "degis" in folded or "değiş" in folded or re.search(r"\bal\b", folded)
    ):
        parsed["intent"] = "week_change"
        parsed["week"] = week
        return parsed
    if any(word in folded for word in ("limit", "faiz", "taksit", "puan")):
        parsed["intent"] = "out_of_scope"
        return parsed
    if _english(folded):
        parsed["intent"] = "non_turkish"
        return parsed
    if parsed["digits"]:
        parsed["intent"] = "digits"
        return parsed
    parsed["intent"] = "name"
    parsed["name"] = raw
    return parsed


def _reveal(folded):
    asks = "soyle" in folded or "söyle" in folded or "oku" in folded
    if not asks:
        return False
    secret = (
        "hane" in folded or "ilk" in folded or "tam numara" in folded
        or "tum numara" in folded or "tüm numara" in folded or "kart numara" in folded
    )
    return secret


def _abusive(folded):
    markers = (
        "aptal", "salak", "gerizekali", "gerizekalı", "serefsiz", "şerefsiz",
        "orospu", "siktir", "amk", "kahrol",
    )
    return any(word in folded for word in markers)


def _english(folded):
    if re.search(r"[çğıöşü]", folded):
        return False
    return folded.startswith("what ") or folded.startswith("hello") or " please " in " " + folded + " "


def _digits(folded):
    numbers = re.findall(r"\d+", folded)
    if numbers:
        return "".join(numbers)
    tokens = re.findall(r"[a-zçğıöşü]+", folded)
    found = []
    for token in tokens:
        if token in WORD_DIGITS:
            found.append(WORD_DIGITS[token])
    return "".join(found)


def _week(folded):
    for word, number in WEEK_WORDS.items():
        if word in folded:
            return str(number)
    match = re.search(r"\b([1-4])\s*\.?\s*hafta", folded)
    if match:
        return match.group(1)
    if re.fullmatch(r"[1-4]", folded.strip()):
        return folded.strip()
    return ""


def _mark_heard(state):
    heard = list(state.get("heard") or [])
    selected = state.get("selected") or ""
    if selected and selected not in heard:
        heard.append(selected)
    state["heard"] = heard


def _unread(state):
    heard = set(state.get("heard") or [])
    return [card for card in state.get("cards") or [] if card.get("cardNumber") not in heard]


def _reading(state, spec):
    card = _selected(state)
    data = state.get("balance") or {}
    facts = {}
    facts["last4"] = card.get("last4") or ""
    facts["product_name"] = card.get("productName") or ""
    facts["statement_date"] = str(data.get("statementDate") or "").strip()
    facts["next_statement_date"] = str(data.get("nextStatementDate") or "").strip()
    facts["due"] = str(data.get("lastPayDate") or "").strip()
    facts["currencies"] = []
    facts["no_debt"] = []
    facts["omitted"] = []
    today = _call_day(state.get("now") or "")
    issued_day = _service_day(facts["statement_date"]) if facts["statement_date"] else None
    next_day = _service_day(facts["next_statement_date"]) if facts["next_statement_date"] else None
    facts["due_today"] = bool(today and facts["due"] and _service_day(facts["due"]) == today)
    facts["due_passed"] = bool(today and facts["due"] and _service_day(facts["due"]) < today)
    # The issued statement date stays on the previous cycle. The cut day is the coming date.
    facts["cut_today"] = bool(today and next_day == today and issued_day != today)
    facts["no_statement_yet"] = issued_day is None
    if facts["no_statement_yet"] and not facts["cut_today"]:
        text = _unissued_text(spec, card, facts["next_statement_date"])
        return {"text": text, "facts": facts}
    if facts["cut_today"]:
        lines = [_card_label(card), spec["lines"]["cut_today"]]
        lines.extend(_total_lines(spec, data))
        return {"text": " ".join(part for part in lines if part), "facts": facts}
    if str(data.get("statementPaymentStatus") or "") == "NO_DEBT":
        return {"text": _no_statement(spec, card, data), "facts": facts}
    if facts["due_passed"]:
        lines = [_card_label(card), _paraphrase(spec, "due_passed")]
        lines.extend(_total_lines(spec, data))
        return {"text": " ".join(part for part in lines if part), "facts": facts}
    lines = []
    first = True
    clear = []
    for block in spec.get("balance_blocks") or []:
        code = block["code"]
        raw = data.get(block["field"])
        if not isinstance(raw, dict):
            facts["omitted"].append(code)
            continue
        kind = _kind(code, raw)
        row = {"code": code, "kind": kind}
        for field in spec.get("amount_fields") or []:
            row[field] = raw.get(field)
        facts["currencies"].append(row)
        if kind == "none":
            clear.append(code)
            continue
        sentence = _currency_line(spec, code, raw, kind)
        if first:
            sentence = _opening(card, facts["statement_date"]) + sentence
            first = False
        lines.append(sentence)
    facts["no_debt"] = clear
    if clear and not lines:
        return {"text": _no_statement(spec, card, data), "facts": facts}
    if clear and lines:
        lines.append(_clear_sentence(spec, clear))
    if facts["due_today"]:
        lines.append(spec["lines"]["due_today"])
    elif facts["due"]:
        lines.append(_due_line(spec, facts["due"]))
    packed = {"text": " ".join(lines), "facts": facts}
    return packed


def _kind(code, block):
    remaining = _amount(block.get("remainingDebt"))
    if code == "TL":
        remaining_min = _amount(block.get("remainingMinPayment"))
        minimum = _amount(block.get("minPayment"))
        if remaining <= 0:
            return "none"
        if remaining_min <= 0:
            return "minimum_paid"
        if remaining_min + 0.001 >= minimum:
            return "unpaid"
        return "partial"
    statement = _amount(block.get("statementDebt"))
    minimum = _amount(block.get("minPayment"))
    if statement <= 0 and remaining <= 0 and minimum <= 0:
        return "none"
    if str(block.get("statementPaymentStatus") or "") == "NO_DEBT" and statement <= 0:
        return "none"
    return "debt"


def _currency_line(spec, code, block, kind):
    if code == "TL" and kind == "unpaid":
        text = spec["lines"]["tl_unpaid"]
    elif code == "TL" and kind == "minimum_paid":
        text = spec["lines"]["tl_minimum_paid"]
    elif code == "TL":
        text = spec["lines"]["tl_partial"]
    else:
        name = spec["policy"]["currency_names"][code]
        text = spec["lines"]["fx_debt"].replace("Dolar borcunuz", name + " borcunuz", 1).replace("USD", code)
    if code == "TL":
        text = fill_money(text, "XXX", block.get("statementDebt"), code, spec)
        text = fill_money(text, "ZZZ", block.get("minPayment"), code, spec)
        text = fill_money(text, "YYY", block.get("remainingDebt"), code, spec)
        text = fill_money(text, "TTT", block.get("remainingMinPayment"), code, spec)
        return text
    text = fill_money(text, "XXX", block.get("statementDebt"), code, spec)
    text = fill_money(text, "YYY", block.get("remainingDebt"), code, spec)
    return fill_money(text, "ZZZ", block.get("minPayment"), code, spec)


def _opening(card, statement_date):
    spoken_digits = digits_spoken(card.get("last4") or "")
    name = (card.get("productName") or "").strip()
    when = _safe_spoken_date(statement_date)
    head = "Sonu " + spoken_digits + " ile biten "
    if name:
        head += name + " "
    head += "kartınıza ait "
    if when:
        head += when + " tarihinde kesilen ekstre "
    return head


def _clear_sentence(spec, codes):
    names = [spec["policy"]["currency_names"][code] for code in codes]
    if len(names) == 1:
        return names[0] + " borcunuz bulunmamaktadır."
    if len(names) == 2:
        return names[0] + " ve " + names[1] + " borcunuz bulunmamaktadır."
    return ", ".join(names[:-1]) + " ve " + names[-1] + " borcunuz bulunmamaktadır."


def _due_line(spec, value):
    spoken = speak_date(value)
    day, month, year = spoken.split()
    return "Borçlarınız için son ödeme tarihiniz " + day + " " + month + copula(month) + " " + year + "."


def _card_label(card):
    spoken_digits = digits_spoken(card.get("last4") or "")
    name = (card.get("productName") or "").strip()
    if name:
        return "Sonu " + spoken_digits + " ile biten " + name + " kartınız."
    return "Sonu " + spoken_digits + " ile biten kartınız."


def _safe_spoken_date(value):
    text = str(value or "").strip()
    if text.count(".") != 2:
        return ""
    try:
        return speak_date(text)
    except (ValueError, IndexError):
        return ""


def _unissued_text(spec, card, next_date):
    base = spec["lines"].get("no_statement_yet") or ""
    text = (_card_label(card) + " " + base).strip()
    spoken = _safe_spoken_date(next_date)
    pattern = spec["lines"].get("first_statement") or ""
    if spoken and pattern:
        text = text + " " + pattern.replace("[tarih]", spoken)
    return text


def _total_lines(spec, data):
    field_name = (spec.get("policy") or {}).get("cut_day_field") or "totalDebt"
    lines = []
    clear = []
    present = []
    for block in spec.get("balance_blocks") or []:
        raw = data.get(block["field"])
        if not isinstance(raw, dict):
            continue
        present.append(block["code"])
        if _amount(raw.get(field_name)) <= 0:
            clear.append(block["code"])
            continue
        name = spec["policy"]["currency_names"][block["code"]]
        spoken = speak_money(raw.get(field_name), block["code"], spec)
        lines.append(name + " toplam borcunuz " + spoken + ".")
    if clear and len(clear) < len(present):
        lines.append(_clear_sentence(spec, clear))
    elif present and not lines:
        lines.append(_clear_sentence(spec, present))
    return lines


def _no_statement(spec, card, data):
    text = spec["lines"]["no_statement_debt"]
    text = text.replace("[son 4 hane]", digits_spoken(card.get("last4") or ""))
    text = text.replace("[kart adı]", (card.get("productName") or "").strip())
    when = _safe_spoken_date(data.get("statementDate"))
    if when:
        text = text.replace("[hesap kesim tarihi]", when)
    else:
        text = text.replace("[hesap kesim tarihi] tarihli ", "")
    total = (data.get("debtTL") or {}).get("totalDebt") if isinstance(data.get("debtTL"), dict) else None
    if total is not None and str(total) != "":
        text = text.replace("GGG TL", speak_money(total, "TL", spec))
    else:
        text = text.replace("Gelecek dönemler dahil toplam borcunuz GGG TL'dir.", "")
    due = _safe_spoken_date(data.get("lastPayDate"))
    if due:
        text = text.replace("[son ödeme tarihi]", due)
    else:
        text = text.replace("Son ödeme tarihiniz [son ödeme tarihi] olacaktır.", "")
    return " ".join(text.split())


def _week_current(spec, state):
    week = state.get("week") or {}
    text = spec["lines"]["week_current"]
    text = text.replace("[kart adı]", (_selected(state).get("productName") or "").strip())
    text = text.replace("[hafta]", str(week.get("statementWeek") or ""))
    text = text.replace("[tarih]", speak_date(week.get("nextStatementDate") or ""), 1)
    return text.replace("[tarih]", speak_date(week.get("nextLastPayDate") or ""), 1)


def _week_options(spec, current):
    others = [item for item in WEEKS if item != int(current)]
    sample = spec["lines"]["week_options"]
    if " ayın " not in sample or " haftasına " not in sample:
        return sample
    prefix, _rest = sample.split(" ayın ", 1)
    tail = sample.split(" haftasına ", 1)[1]
    return prefix + " ayın " + week_list(others) + " haftasına " + tail


def _week_confirm(spec, state):
    preview = state.get("preview") or {}
    text = spec["lines"]["week_confirm"]
    text = re.sub(r"\d+\. haftası", str(state.get("chosen_week") or "") + ". haftası", text, count=1)
    text = text.replace("[tarih]", speak_date(preview.get("statementDate") or ""), 1)
    return text.replace("[tarih]", speak_date(preview.get("statementDueDate") or ""), 1)


def _week_done(spec, state):
    preview = state.get("preview") or {}
    card = _selected(state)
    text = spec["lines"]["week_done"]
    text = text.replace("[son 4 hane]", digits_spoken(card.get("last4") or ""))
    text = text.replace("[kart adı]", (card.get("productName") or "").strip())
    text = re.sub(r"\d+\. haftası", str(state.get("chosen_week") or "") + ". haftası", text, count=1)
    text = text.replace("[tarih]", speak_date(preview.get("statementDate") or ""), 1)
    return text.replace("[tarih]", speak_date(preview.get("statementDueDate") or ""), 1)


def _joint(spec, relation, related):
    if relation == "M":
        return spec["lines"]["joint_main"].replace("[bağlı kart adı]", related)
    if relation == "C":
        return spec["lines"]["joint_linked"].replace("[asıl kart adı]", related)
    return ""


def _select_line(spec, cards):
    labels = []
    for card in cards:
        if len(labels) == 2:
            break
        name = (card.get("productName") or "").strip()
        labels.append(name or ("sonu " + digits_spoken(card.get("last4") or "") + " ile biten kart"))
    line = spec["lines"]["select_card"]
    if len(labels) >= 2:
        line = line.replace("[kart adı]", labels[0], 1).replace("[kart adı]", labels[1], 1)
    elif labels:
        line = line.replace("[kart adı] veya [kart adı]", labels[0])
    return line


def _offer_line(state, spec):
    has_mail = bool(state.get("email"))
    has_week = bool(spec["policy"].get("offer_week_when_eligibility_unknown")) or bool(spec["policy"].get("week_eligibility_known"))
    if state.get("week_changed"):
        has_week = False
    if has_mail and has_week:
        return spec["lines"]["offer_both"]
    if has_week:
        return spec["lines"]["offer_week"]
    if has_mail:
        return spec["lines"]["offer_email"]
    return spec["lines"]["menu_normal"]


def _email_confirm_line(spec, address):
    line = spec["lines"]["email_confirm"]
    if "…" in line:
        return line.replace("…", address)
    return line.replace("...", address)


def _ineligible_line(spec, eligible):
    note = _paraphrase(spec, "supplementary")
    question = _select_line(spec, eligible)
    return (note + " " + question).strip()


def _other_person(folded):
    return re.search(
        r"\b("
        r"esimin|eşimin|esim|eşim|karimin|karımın|karim|karım|"
        r"kocamin|kocamın|kocam|"
        r"annemin|annem|babamin|babamın|babam|"
        r"oglumun|oğlumun|oglum|oğlum|kizimin|kızımın|kizim|kızım|"
        r"kardesimin|kardeşimin|kardesim|kardeşim|"
        r"arkadasimin|arkadaşımın|"
        r"baskasinin|başkasının|baska birinin|başka birinin|"
        r"partnerimin|partnerim"
        r")\b",
        folded,
    ) is not None


def _reidentify(folded):
    return "yanlis musteri" in folded or "yanlış müşteri" in folded or "bu musteri degilim" in folded or "bu müşteri değilim" in folded


def _paraphrase(spec, name):
    for row in spec.get("paraphrases") or []:
        if row.get("id") == name:
            return row.get("text") or ""
    return ""


def _api(state, name):
    tools = list(state.get("tools") or [])
    tools.append(name)
    state["tools"] = tools
    state["pending"] = name
    state["route"] = "api_" + name.replace(".", "_")
    state["say"] = ""
    return state


def _ask(state, text, phase):
    state["phase"] = phase
    state["say"] = text
    state["last_say"] = text
    state["route"] = "talk"
    state["pending"] = ""
    state["tries"] = 0
    state["silence"] = 0
    return state


def _miss(state, spec, again):
    state["tries"] = int(state.get("tries") or 0) + 1
    if state["tries"] >= int(spec["policy"]["max_tries"] or 3):
        return _end(state, "end_menu", spec["lines"]["tries_exhausted"])
    state["say"] = again
    state["last_say"] = again
    state["route"] = "talk"
    return state


def _end(state, route, text):
    state["route"] = route
    state["say"] = text
    state["last_say"] = text
    state["phase"] = "done"
    state["pending"] = ""
    return state


def _service_fail(state, spec, name):
    if str(name).startswith("statement.week"):
        return _end(state, "end_agent", spec["lines"]["week_error"])
    return _end(state, "end_agent", spec["lines"]["service_error"])


def _selected(state):
    for card in state.get("cards") or []:
        if card.get("cardNumber") == state.get("selected"):
            return card
    if state.get("cards"):
        return state["cards"][0]
    return {"cardNumber": "", "last4": "", "productName": "", "isMainCard": True}


def _amount(value):
    if value is None or value == "":
        return 0.0
    return float(value)


def _call_day(value):
    text = str(value)[:10]
    parts = text.split("-")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _service_day(value):
    parts = str(value).split(".")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except ValueError:
        return None
