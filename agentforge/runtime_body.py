"""Deterministic call policy. Embedded into Freya code nodes. No template braces."""
import json
import re
from datetime import date, datetime, timedelta

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEK_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "twenty first": 21, "twenty-first": 21, "twenty second": 22,
    "twenty-second": 22, "twenty third": 23, "twenty-third": 23, "twenty fourth": 24, "twenty-fourth": 24,
    "twenty fifth": 25, "twenty-fifth": 25, "twenty sixth": 26, "twenty-sixth": 26, "twenty seventh": 27,
    "twenty-seventh": 27, "twenty eighth": 28, "twenty-eighth": 28, "twenty ninth": 29, "twenty-ninth": 29,
    "thirtieth": 30, "thirty first": 31, "thirty-first": 31,
}
HOURS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "noon": 12,
}
DIGITS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
VAGUE = ("week after next", "next week", "end of the month", "end of month", "when my salary", "salary comes", "sometime", "in a few weeks", "later this month")


def pol(vars):
    raw = vars.get("policy_json") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def holidays_of(p):
    return set(p.get("holidays") or [])


def bands_of(p):
    rows = []
    for row in p.get("bands") or []:
        bits = str(row).split("|")
        if len(bits) != 5:
            continue
        rows.append((int(bits[0]), int(bits[1]), bits[2], int(bits[3]), int(bits[4])))
    return rows


def floors_of(p):
    out = {}
    for row in p.get("floors") or []:
        bits = str(row).split("|")
        if len(bits) == 2:
            out[bits[0]] = bits[1]
    return out


def parse_now(vars):
    raw = str(vars.get("now") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", ""))
    except Exception:
        return datetime(2026, 1, 1, 9, 0)


def is_business(day, holidays):
    return day.weekday() < 5 and day.isoformat() not in holidays


def add_business(start, count, holidays):
    day = start
    left = count
    while left > 0:
        day = day + timedelta(days=1)
        if is_business(day, holidays):
            left = left - 1
    return day


def next_business_after(day, holidays):
    cursor = day + timedelta(days=1)
    while not is_business(cursor, holidays):
        cursor = cursor + timedelta(days=1)
    return cursor


def on_or_after_business(day, holidays):
    cursor = day
    while not is_business(cursor, holidays):
        cursor = cursor + timedelta(days=1)
    return cursor


def last_business_of_week(today, holidays, offset):
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7 * offset)
    cursor = monday + timedelta(days=4)
    while cursor >= monday and not is_business(cursor, holidays):
        cursor = cursor - timedelta(days=1)
    return cursor


def attempt_day(today, holidays):
    this_week = last_business_of_week(today, holidays, 0)
    if this_week <= today:
        return last_business_of_week(today, holidays, 1)
    return this_week


def speak_day(day):
    return WEEK_NAMES[day.weekday()] + " " + str(day.day) + " " + MONTH_NAMES[day.month - 1] + " " + str(day.year)


def money(value):
    return format(round(float(value), 2), ".2f")


def read_number(value):
    """Return (number, kind) where kind is ok, null, or malformed."""
    if value is None:
        return None, "null"
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None, "malformed"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, "malformed"
        try:
            number = float(text)
        except ValueError:
            return None, "malformed"
    else:
        number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None, "malformed"
    return number, "ok"


def field_number(raw, key):
    if key not in raw:
        return None, "missing"
    return read_number(raw.get(key))


def read_past_due(raw):
    number, kind = field_number(raw, "past_due")
    if kind == "ok" and number < 0:
        return None, "malformed"
    return number, kind


def read_days_late(raw):
    number, kind = field_number(raw, "days_late")
    if kind != "ok":
        return None, kind
    if number < 0 or abs(number - round(number)) > 0.000001:
        return None, "malformed"
    return int(round(number)), "ok"


def band_for(days_late, p):
    for low, high, name, n_days, attempts in bands_of(p):
        if low <= days_late <= high:
            return {"name": name, "n_days": n_days, "attempts": attempts}
    return None


def load_products(vars):
    raw = vars.get("products_raw")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                return loaded
        except Exception:
            pass
    found = {}
    for key in list(vars.keys()):
        text = str(key)
        marker = ".products."
        if marker not in text:
            continue
        bits = text.split(marker, 1)[1].split(".")
        if len(bits) < 2 or not bits[0].isdigit():
            continue
        bucket = found.get(bits[0])
        if bucket is None:
            bucket = {}
            found[bits[0]] = bucket
        bucket[bits[1]] = vars.get(key)
    ordered = []
    for idx in sorted(found.keys(), key=lambda item: int(item) if str(item).isdigit() else str(item)):
        ordered.append(found[idx])
    return ordered


def enrich(raw_products, today, p):
    holidays = holidays_of(p)
    floors = floors_of(p)
    enriched = []
    index = 0
    for raw in raw_products:
        index += 1
        ptype = str(raw.get("type") or "")
        last4 = str(raw.get("card_last4") or "")
        if ptype == "credit_card" and last4:
            label = "credit card ending " + last4
        elif ptype == "personal_loan":
            label = "personal loan"
        elif ptype == "car_loan":
            label = "car loan"
        else:
            label = ptype.replace("_", " ") or "account"
        past, past_kind = read_past_due(raw)
        days_late, days_kind = read_days_late(raw)
        item = {}
        item["product_id"] = str(raw.get("product_id") or ("p" + str(index)))
        item["type"] = ptype
        item["last4"] = last4
        item["label"] = label
        item["past_kind"] = past_kind
        item["days_kind"] = days_kind
        if past_kind != "ok" or days_kind != "ok":
            item["usable"] = "no"
            item["block"] = "balance"
            item["past_due"] = ""
            item["floor"] = ""
            item["days_late"] = ""
            item["band"] = ""
            item["attempts"] = 0
            item["deadline"] = ""
            item["attempt1"] = ""
            enriched.append(item)
            continue
        floor_field = floors.get(ptype) or ""
        floor_raw = raw.get(floor_field) if floor_field else None
        if floor_raw in (None, ""):
            floor = past
        else:
            floor_number, floor_kind = read_number(floor_raw)
            floor = past if floor_kind != "ok" or floor_number < 0 else floor_number
        info = band_for(days_late, p)
        if not info:
            item["usable"] = "no"
            item["block"] = "band"
            item["past_due"] = ""
            item["floor"] = ""
            item["days_late"] = days_late
            item["band"] = ""
            item["attempts"] = 0
            item["deadline"] = ""
            item["attempt1"] = ""
            enriched.append(item)
            continue
        deadline = add_business(today, info["n_days"], holidays) if info["n_days"] else today
        item["usable"] = "yes"
        item["block"] = ""
        item["past_due"] = past
        item["floor"] = floor
        item["days_late"] = days_late
        item["band"] = info["name"]
        item["attempts"] = info["attempts"]
        item["deadline"] = deadline.isoformat()
        item["attempt1"] = attempt_day(today, holidays).isoformat()
        enriched.append(item)
    return enriched


def products_state(vars):
    raw = vars.get("products_json") or "[]"
    try:
        return json.loads(raw)
    except Exception:
        return []


def save_products(vars, products):
    vars["products_json"] = json.dumps(products)


def begin(vars):
    p = pol(vars)
    bank = p.get("bank") or "the bank"
    title = str(vars.get("title") or "")
    last = str(vars.get("last_name") or "")
    vars["disclosure"] = "Hello, this is a digital assistant calling from " + bank + ". This call is recorded."
    vars["greet_line"] = "Am I speaking with " + title + " " + last + "?"
    vars["promise_recorded"] = "no"
    vars["promise_line"] = " "
    vars["extra_line"] = " "
    vars["farewell"] = "Thank you. Goodbye."
    vars["recorded_ids"] = ""
    vars["notes_queue"] = ""
    vars["noted_ids"] = ""
    vars["queue"] = ""
    vars["offer_open"] = "no"
    vars["call_phase"] = "greet"
    vars["greet_asks"] = "0"
    vars["id_index"] = "0"
    vars["id_deflect"] = "0"
    vars["cb_bad"] = "0"
    vars["route"] = "greet"
    vars["coach"] = vars["greet_line"]


def party_kind(said, vars):
    text = " " + said.lower().replace("’", "'") + " "
    last = str(vars.get("last_name") or "").lower()
    first = str(vars.get("first_name") or "").lower()
    if re.search(r"\b(passed away|has died|he died|she died|deceased|is dead|has passed)\b", text):
        return "deceased"
    if any(token in text for token in ("wrong number", "no one by that name", "nobody by that name", "doesn't live", "does not live", "not her number", "not his number")):
        return "wrong"
    relatives = ("husband", "wife", "son", "daughter", "mother", "father", "brother", "sister", "friend", "colleague", "roommate", "partner", "relative")
    if any(re.search(r"\b" + word + r"\b", text) for word in relatives):
        return "other"
    if any(token in text for token in ("not here", "isn't here", "is not here", "he's out", "she's out", "not available", "speaking for")):
        return "other"
    if any(token in text for token in ("who is this", "who's this", "who are you", "what do you want", "go ahead")):
        return "unclear"
    if last and last in text and " not " not in text:
        return "self"
    if first and ("this is " + first) in text:
        return "self"
    if any(token in text for token in ("that's me", "thats me", "that is me", "speaking", "this is he", "this is she", "yes it is", "yes i am", "i am him", "i am her")):
        return "self"
    bare = re.sub(r"[^a-z ]", "", text).strip()
    if bare in ("yes", "yeah", "yep", "ya", "correct", "right"):
        return "self"
    return "unclear"


def is_question(said):
    low = said.lower()
    return "?" in said or any(token in low for token in ("who is this", "who are you", "what is this", "why are you", "are you"))


def close_with(vars, outcome_key, reason_key, extra):
    p = pol(vars)
    vars["outcome"] = p.get(outcome_key) or ""
    vars["reason"] = p.get(reason_key) or ""
    spoken_extra = extra or ""
    spoken_promise = ""
    if vars.get("promise_recorded") == "yes":
        spoken_promise = p.get("sentence") or ""
    vars["extra_line"] = spoken_extra if spoken_extra else " "
    vars["promise_line"] = spoken_promise if spoken_promise else " "
    farewell = "Thank you."
    if spoken_extra:
        farewell = farewell + " " + spoken_extra
    if spoken_promise:
        farewell = farewell + " " + spoken_promise
    vars["farewell"] = farewell + " Goodbye."
    vars["route"] = "close"
    vars["offer_open"] = "no"


def callback_allowed(today, holidays):
    days = []
    if is_business(today, holidays):
        days.append(today)
    days.append(add_business(today, 1, holidays))
    return days


def parse_clock(text):
    low = text.lower()
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", low)
    hour = None
    minute = 0
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        marker = match.group(3) or ""
        if marker == "pm" and hour < 12:
            hour += 12
        if marker == "am" and hour == 12:
            hour = 0
    else:
        for word, value in HOURS.items():
            if re.search(r"\b" + word + r"\b", low):
                hour = value
                break
    if hour is None:
        return ""
    if "evening" in low or "afternoon" in low or "tonight" in low:
        if hour < 12:
            hour += 12
    if hour > 23:
        return ""
    return str(hour).zfill(2) + ":" + str(minute).zfill(2)


def weekday_date(text, today):
    low = text.lower()
    monday = today - timedelta(days=today.weekday())
    for index, name in enumerate(WEEK):
        if re.search(r"\bnext " + name + r"\b", low):
            return monday + timedelta(days=7 + index)
        if re.search(r"\bthis " + name + r"\b", low):
            return monday + timedelta(days=index)
    for index, name in enumerate(WEEK):
        if re.search(r"\b" + name + r"\b", low):
            found = monday + timedelta(days=index)
            if found < today:
                found = found + timedelta(days=7)
            return found
    return None


def spoken_day(tokens, forward=False):
    picked = []
    fillers = ("of", "the", "on", "a", "an", "and", "then", "in")
    sequence = tokens if forward else reversed(tokens)
    for token in sequence:
        if token in fillers:
            if picked:
                break
            continue
        if word_value(token) is None:
            if picked:
                break
            continue
        picked.append(token)
        if len(picked) == 3:
            break
    if not forward:
        picked.reverse()
    if not picked:
        return None
    phrase = " ".join(picked)
    if phrase in ORDINALS:
        return ORDINALS[phrase]
    value, _left = take_under_hundred(picked)
    if value and 1 <= value <= 31:
        return value
    return None


def month_day_dates(text, today):
    low = text.lower().replace(",", " ").replace("-", " ")
    found = []
    for match in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]+)\b", low):
        month = MONTHS.get(match.group(2))
        if month:
            found.append((int(match.group(1)), month))
    for match in re.finditer(r"\b([a-z]+)\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\b", low):
        month = MONTHS.get(match.group(1))
        if month:
            found.append((int(match.group(2)), month))
    tokens = re.findall(r"[a-z]+", low)
    for name, month in MONTHS.items():
        if name not in tokens:
            continue
        pivot = tokens.index(name)
        day_num = spoken_day(tokens[:pivot]) or spoken_day(tokens[pivot + 1:], forward=True)
        if day_num:
            found.append((day_num, month))
    dates = []
    for day_num, month in found:
        year = today.year
        try:
            candidate = date(year, month, day_num)
        except Exception:
            continue
        if candidate < today - timedelta(days=1):
            try:
                candidate = date(year + 1, month, day_num)
            except Exception:
                continue
        dates.append(candidate)
    return dates


def ordinal_date(text, today):
    low = text.lower()
    day_num = None
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", low)
    if match:
        day_num = int(match.group(1))
    else:
        for phrase, value in sorted(ORDINALS.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(r"\b" + re.escape(phrase) + r"\b", low):
                day_num = value
                break
    if not day_num:
        return None
    month = None
    for name, number in MONTHS.items():
        if re.search(r"\b" + name + r"\b", low):
            month = number
            break
    year = today.year
    if month is None:
        month = today.month
        if day_num < today.day:
            month += 1
            if month == 13:
                month = 1
                year += 1
    elif month < today.month:
        year += 1
    try:
        return date(year, month, day_num)
    except Exception:
        return None


def find_dates(text, today):
    low = text.lower()
    found = []
    if "tomorrow" in low:
        found.append(today + timedelta(days=1))
    explicit = month_day_dates(text, today)
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        try:
            explicit.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except Exception:
            pass
    for slash in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text):
        try:
            explicit.append(date(int(slash.group(3)), int(slash.group(2)), int(slash.group(1))))
        except Exception:
            pass
    if not explicit:
        ordinal = ordinal_date(text, today)
        if ordinal:
            explicit.append(ordinal)
    if explicit:
        found.extend(explicit)
    else:
        named = weekday_date(text, today)
        if named:
            found.append(named)
    negative = re.search(r"\b(not|cannot|can't|won't|unable|no)\b", low)
    if re.search(r"\btoday\b", low) and not negative:
        found.append(today)
    return found


def is_vague(text):
    low = text.lower()
    if find_dates(text, date(2000, 1, 1)):
        return False
    return any(phrase in low for phrase in VAGUE)


def clock_ok(hhmm, start, end):
    return bool(hhmm) and start <= hhmm <= end


def review_callback_text(said, vars, p):
    now = parse_now(vars)
    today = now.date()
    holidays = holidays_of(p)
    start = p.get("callback_start") or "10:00"
    end = p.get("callback_end") or "19:00"
    dates = find_dates(said, today)
    # "today" inside a refusal should not count; find_dates already filters most of these.
    when = None
    for candidate in dates:
        if candidate >= today:
            when = candidate
            break
    if "tomorrow" in said.lower():
        when = today + timedelta(days=1)
    hhmm = parse_clock(said)
    title = str(vars.get("title") or "")
    last = str(vars.get("last_name") or "")
    ask = "When can " + title + " " + last + " be reached? A callback can be today or the next business day, between " + start + " and " + end + "."
    if not when or not hhmm:
        if int(vars.get("cb_empty") or "0") >= 2:
            close_with(vars, "role_not_reached", "reason_no_callback", "")
            return
        vars["cb_empty"] = str(int(vars.get("cb_empty") or "0") + 1)
        vars["coach"] = ask
        vars["greet_line"] = ask
        vars["route"] = "callback"
        return
    allowed = callback_allowed(today, holidays)
    in_window = clock_ok(hhmm, start, end) and when in allowed and (when > today or hhmm > now.strftime("%H:%M"))
    if not in_window:
        bad = int(vars.get("cb_bad") or "0") + 1
        vars["cb_bad"] = str(bad)
        if bad >= 2:
            close_with(vars, "role_not_reached", "reason_no_callback", "")
            return
        vars["coach"] = "That time is outside the window. Please give a time today or on the next business day, between " + start + " and " + end + "."
        vars["route"] = "callback"
        return
    vars["cb_date"] = when.isoformat()
    vars["cb_time"] = hhmm
    vars["callback_ok"] = ""
    vars["route"] = "callback_api"


def after_greet(vars):
    said = str(vars.get("user_said") or "").strip()
    p = pol(vars)
    if not said:
        vars["route"] = "greet"
        return
    kind = party_kind(said, vars)
    if kind == "self":
        vars["call_phase"] = "verify"
        vars["id_index"] = "0"
        vars["id_line"] = field_prompt(p, 0)
        vars["route"] = "verify"
        return
    if kind == "deceased":
        close_with(vars, "role_not_reached", "reason_deceased", p.get("sorry") or "")
        return
    if kind == "wrong":
        close_with(vars, "role_not_reached", "reason_wrong_number", "")
        return
    if wants_to_end(said):
        end_conversation(vars, [], p)
        return
    if kind == "other":
        vars["call_phase"] = "callback"
        review_callback_text(said, vars, p)
        if vars.get("route") == "callback":
            vars["route"] = "callback"
        return
    asks = int(vars.get("greet_asks") or "0") + 1
    vars["greet_asks"] = str(asks)
    bank = p.get("bank") or "the bank"
    prefix = ""
    low = said.lower()
    if "robot" in low or "ai" in low or "machine" in low:
        prefix = (p.get("assistant_line") or ("I am " + bank + "'s digital assistant.")) + " "
    if "scam" in low:
        prefix = prefix + "You can verify this call by phoning " + bank + "'s customer service number. "
    if asks >= 2:
        close_with(vars, "role_not_reached", "reason_unclear", "")
        return
    title = str(vars.get("title") or "")
    last = str(vars.get("last_name") or "")
    vars["greet_line"] = prefix + "Am I speaking with " + title + " " + last + "?"
    vars["route"] = "greet"


def field_prompt(p, index):
    fields = p.get("id_fields") or ["date_of_birth", "phone_last4"]
    if index >= len(fields):
        return "Thank you."
    field = fields[index]
    if field == "phone_last4":
        return "Please tell me the last four digits of the phone number on file."
    return "Please tell me your date of birth."


SMALL_WORDS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def word_value(token):
    if token in SMALL_WORDS:
        return SMALL_WORDS[token]
    if token in ORDINALS:
        return ORDINALS[token]
    return None


def spoken_year(tokens):
    if not tokens:
        return None
    if tokens[0] == "nineteen":
        rest, _left = take_under_hundred(tokens[1:])
        if rest is None:
            return None
        return 1900 + rest
    if tokens[0] == "two" and len(tokens) > 1 and tokens[1] == "thousand":
        rest, _left = take_under_hundred(tokens[2:])
        return 2000 + (rest or 0)
    if tokens[0] == "twenty":
        rest, _left = take_under_hundred(tokens[1:])
        if rest is None:
            return 2000
        return 2000 + rest
    return None


def take_number(tokens):
    if not tokens:
        return None, tokens
    if tokens[0] in ("nineteen", "twenty") and len(tokens) > 1 and word_value(tokens[1]) is not None:
        base = 1900 if tokens[0] == "nineteen" else 2000
        rest, left = take_under_hundred(tokens[1:])
        if rest is None:
            return None, tokens
        return base + rest, left
    return take_under_hundred(tokens)


def take_under_hundred(tokens):
    if not tokens:
        return None, tokens
    first = word_value(tokens[0])
    if first is None:
        return None, tokens
    if first >= 20 and first % 10 == 0 and len(tokens) > 1:
        second = word_value(tokens[1])
        if second is not None and second < 10:
            return first + second, tokens[2:]
    return first, tokens[1:]


def parse_dob(text):
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        return match.group(1) + "-" + match.group(2) + "-" + match.group(3)
    slash = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if slash:
        day_num = int(slash.group(1))
        month = int(slash.group(2))
        year = int(slash.group(3))
        try:
            return date(year, month, day_num).isoformat()
        except Exception:
            return ""
    low = text.lower().replace(",", " ")
    month = None
    month_name = ""
    month_at = None
    for name, number in MONTHS.items():
        found = re.search(r"\b" + name + r"\b", low)
        if found and (month_at is None or found.start() < month_at):
            month = number
            month_name = name
            month_at = found.start()
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", low)
    days = re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", low)
    if month and years and days:
        try:
            return date(int(years[-1]), month, int(days[0])).isoformat()
        except Exception:
            return ""
    if not month or not month_name:
        return ""
    tokens = re.findall(r"[a-z]+", low.replace("-", " "))
    if month_name not in tokens:
        return ""
    pivot = tokens.index(month_name)
    day_num, _left = take_under_hundred(tokens[:pivot])
    year = spoken_year(tokens[pivot + 1:])
    if not day_num or not year or year < 1900 or day_num > 31:
        return ""
    try:
        return date(year, month, day_num).isoformat()
    except Exception:
        return ""


def parse_word_date(low):
    month = None
    for name, number in MONTHS.items():
        if name in low:
            month = number
            break
    if not month:
        return ""
    day_num = None
    for phrase, value in ORDINALS.items():
        if phrase in low:
            day_num = value
            break
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", low)
    if day_num and years:
        try:
            return date(int(years[-1]), month, day_num).isoformat()
        except Exception:
            return ""
    return ""


def parse_phone(text):
    low = text.lower().replace("-", " ")
    low = low.replace("double ", "X")
    tokens = re.findall(r"[a-z]+|\d+", low)
    digits = ""
    for token in tokens:
        if token.isdigit():
            digits += token
            continue
        if token.startswith("X") and token[1:] in DIGITS:
            digits += DIGITS[token[1:]] * 2
            continue
        if token in DIGITS:
            digits += DIGITS[token]
    digits = re.sub(r"\D", "", digits)
    if len(digits) < 4:
        digits = re.sub(r"\D", "", text)
    if len(digits) >= 4:
        return digits[-4:]
    return ""


def id_deflect(said):
    low = said.lower()
    phrases = ("won't answer", "will not answer", "not going to answer", "none of your business", "refuse", "what is this about", "what's this about", "why do you need", "why would you", "don't want to give", "do not want to give", "rather not")
    return any(phrase in low for phrase in phrases)


def flag_from_keys(vars, suffix):
    mapped = pick(vars, suffix)
    if mapped != "":
        return mapped
    tail = suffix.split(".")[-1]
    for key in vars.keys():
        text = str(key)
        if text.endswith("data." + tail) and ("verify" in text or text.startswith("id_")):
            return vars.get(key)
    return ""


def after_id_utterance(vars):
    said = str(vars.get("user_said") or "").strip()
    p = pol(vars)
    vars["call_phase"] = "verify"
    turns = int(vars.get("id_turns") or "0") + 1
    vars["id_turns"] = str(turns)
    if turns > 8:
        close_with(vars, "role_not_verified", "reason_failed", p.get("app_line") or "")
        return
    if not said:
        vars["route"] = "speak"
        return
    fields = p.get("id_fields") or ["date_of_birth", "phone_last4"]
    index = int(vars.get("id_index") or "0")
    if wants_to_end(said) and not parse_dob(said) and not parse_phone(said):
        end_conversation(vars, [], p)
        return
    if id_deflect(said) and not parse_dob(said) and not parse_phone(said):
        count = int(vars.get("id_deflect") or "0") + 1
        vars["id_deflect"] = str(count)
        if count >= 2:
            close_with(vars, "role_not_verified", "reason_declined", "")
            return
        vars["id_line"] = "These questions protect your account. " + field_prompt(p, index)
        vars["route"] = "speak"
        return
    if "robot" in said.lower() or "scam" in said.lower():
        bank = p.get("bank") or "the bank"
        extra = ""
        if "robot" in said.lower():
            extra = (p.get("assistant_line") or "") + " "
        if "scam" in said.lower():
            extra += "You can verify this call by phoning " + bank + "'s customer service number. "
        vars["id_line"] = extra + field_prompt(p, index)
        vars["route"] = "speak"
        return
    if index >= len(fields):
        vars["route"] = "account"
        return
    field = fields[index]
    if field == "date_of_birth":
        iso = parse_dob(said)
        if not iso:
            misses = int(vars.get("id_miss") or "0") + 1
            vars["id_miss"] = str(misses)
            if misses >= 3:
                close_with(vars, "role_not_verified", "reason_failed", p.get("app_line") or "")
                return
            vars["id_line"] = "Please say your date of birth with the day, the month as a word, and the year."
            vars["route"] = "speak"
            return
        vars["id_miss"] = "0"
        vars["id_field"] = "date_of_birth"
        vars["id_answer"] = iso
        vars["id_ok"] = ""
        vars["id_verified"] = ""
        vars["id_all"] = ""
        vars["id_left"] = ""
        vars["id_hint"] = ""
        vars["route"] = "verify_api"
        return
    digits = parse_phone(said)
    if len(digits) != 4:
        misses = int(vars.get("id_miss") or "0") + 1
        vars["id_miss"] = str(misses)
        if misses >= 3:
            close_with(vars, "role_not_verified", "reason_failed", p.get("app_line") or "")
            return
        vars["id_line"] = "Please tell me the last four digits of the phone number on file."
        vars["route"] = "speak"
        return
    vars["id_miss"] = "0"
    vars["id_field"] = field
    vars["id_answer"] = digits
    vars["id_ok"] = ""
    vars["id_verified"] = ""
    vars["id_all"] = ""
    vars["id_left"] = ""
    vars["id_hint"] = ""
    vars["route"] = "verify_api"


def truthy(value):
    return str(value).strip() in ("true", "True", "yes", "1")


def falsey(value):
    return str(value).strip() in ("false", "False", "no", "0")


def pick(vars, *keys):
    for key in keys:
        if key in vars and vars.get(key) not in (None, ""):
            return vars.get(key)
    return ""


def after_id_api(vars):
    p = pol(vars)
    fields = p.get("id_fields") or ["date_of_birth", "phone_last4"]
    index = int(vars.get("id_index") or "0")
    hint = str(flag_from_keys(vars, "id_hint") or flag_from_keys(vars, "verify_identity_response.data.hint") or "")
    all_ok = truthy(flag_from_keys(vars, "id_all") or flag_from_keys(vars, "verify_identity_response.data.all_verified"))
    verified = truthy(flag_from_keys(vars, "id_verified") or flag_from_keys(vars, "verify_identity_response.data.verified"))
    left_raw = flag_from_keys(vars, "id_left")
    if left_raw == "":
        left_raw = flag_from_keys(vars, "verify_identity_response.data.wrong_answers_left")
    ok_raw = flag_from_keys(vars, "id_ok")
    if ok_raw == "":
        ok_raw = flag_from_keys(vars, "verify_identity_response.data.ok")
    if "day_month" in hint or hint == "day_month_swapped":
        vars["id_line"] = "Please say the month as a word."
        vars["route"] = "speak"
        return
    if all_ok:
        vars["route"] = "account"
        vars["call_phase"] = "negotiate"
        return
    if verified:
        index += 1
        vars["id_index"] = str(index)
        if index >= len(fields):
            vars["route"] = "account"
            return
        vars["id_line"] = field_prompt(p, index)
        vars["route"] = "speak"
        return
    if str(left_raw) == "0":
        close_with(vars, "role_not_verified", "reason_failed", p.get("app_line") or "")
        return
    if falsey(verified) or falsey(ok_raw):
        if falsey(ok_raw) and left_raw == "":
            vars["id_line"] = "I could not read that. " + field_prompt(p, index)
        else:
            vars["id_line"] = "That does not match our records. " + field_prompt(p, index)
        vars["route"] = "speak"
        return
    vars["id_line"] = field_prompt(p, index)
    vars["route"] = "speak"


def gap_notice(broken):
    balance = [item["label"] for item in broken if item.get("block") != "band"]
    bands = [item["label"] for item in broken if item.get("block") == "band"]
    parts = []
    if balance:
        parts.append("I could not read the balance on your " + " and ".join(balance) + ".")
    if bands:
        parts.append("I cannot record a payment for your " + " and ".join(bands) + ".")
    if not parts:
        return ""
    return " ".join(parts) + " "


def account_rejected(vars):
    if "account_ok" not in vars:
        return False
    raw = vars.get("account_ok")
    if raw in (None, ""):
        return False
    return falsey(raw)


def prepare_account(vars):
    p = pol(vars)
    today = parse_now(vars).date()
    vars["call_phase"] = "negotiate"
    vars["neg_phase"] = "ask_all"
    vars["pi"] = "0"
    vars["attempt_map"] = ""
    if account_rejected(vars):
        save_products(vars, [])
        vars["notes_queue"] = ""
        close_with(vars, "role_no_promise", "reason_service_error", "I could not open the account.")
        return
    raw = load_products(vars)
    products = enrich(raw, today, p)
    usable = [item for item in products if item.get("usable") == "yes"]
    broken = [item for item in products if item.get("usable") != "yes"]
    save_products(vars, usable)
    if not usable:
        if not products:
            close_with(vars, "role_no_promise", "reason_service_error", "I could not open the account.")
            return
        if p.get("notes") == "yes":
            service = p.get("reason_service_error") or "service_error"
            for item in broken:
                mark_note(vars, item["product_id"], service)
            drain_notes_or_close(vars, usable, p)
            return
        if any(item.get("block") == "balance" for item in broken):
            close_with(vars, "role_no_promise", "reason_service_error", "I could not read the balance.")
        else:
            close_with(vars, "role_no_promise", "reason_service_error", "I cannot record a payment on these terms.")
        return
    bits = []
    for item in usable:
        bits.append("Your " + item["label"] + " is " + money(item["past_due"]) + " past due and " + str(item["days_late"]) + " days late.")
    unread = gap_notice(broken)
    if broken and p.get("notes") == "yes":
        service = p.get("reason_service_error") or "service_error"
        for item in broken:
            mark_note(vars, item["product_id"], service)
    if len(usable) > 1:
        ask = "Can you pay all of them today?"
    else:
        ask = "Can you make this payment today?"
    vars["coach"] = "I am calling from the collections team about a late payment. " + unread + " ".join(bits) + " " + ask
    vars["route"] = "speak"
    vars["offer_open"] = "no"


def attempt_count(vars, product_id):
    for bit in str(vars.get("attempt_map") or "").split(","):
        if bit.startswith(product_id + "="):
            return int(bit.split("=")[1] or 0)
    return 0


def set_attempt(vars, product_id, count):
    bits = []
    found = False
    for bit in str(vars.get("attempt_map") or "").split(","):
        if not bit:
            continue
        if bit.startswith(product_id + "="):
            bits.append(product_id + "=" + str(count))
            found = True
        else:
            bits.append(bit)
    if not found:
        bits.append(product_id + "=" + str(count))
    vars["attempt_map"] = ",".join(bits)


def split_queue(raw):
    if not raw:
        return []
    return [bit for bit in str(raw).split(";") if bit]


def mentioned(text, products):
    low = text.lower()
    hits = []
    for index, item in enumerate(products):
        if item["type"] == "credit_card" and "credit card" in low:
            hits.append(index)
        if item["type"] == "personal_loan" and "personal loan" in low:
            hits.append(index)
        if item["type"] == "car_loan" and ("car loan" in low or "auto loan" in low):
            hits.append(index)
        if item.get("last4") and item["last4"] and item["last4"] in low:
            hits.append(index)
    return hits


def wants_all(text, products):
    low = text.lower()
    if any(token in low for token in ("all of them", "all three", "pay all", "both", "everything", "all products")):
        return True
    if len(products) > 1 and "all" in low:
        return True
    return False


def fit_date(day, product, today, holidays):
    deadline = date.fromisoformat(product["deadline"])
    if day < today:
        return deadline, "after_deadline"
    if day > deadline:
        return deadline, "after_deadline"
    if not is_business(day, holidays):
        nxt = next_business_after(day, holidays)
        if nxt > deadline:
            return deadline, "after_deadline"
        return nxt, "not_business"
    return day, "ok"


def product_by_id(products, product_id):
    for item in products:
        if item["product_id"] == product_id:
            return item
    return None


def set_offer(vars, amount, day, product_ids, speech):
    vars["offer_open"] = "yes"
    vars["offer_amount"] = money(amount)
    vars["offer_date"] = day.isoformat()
    vars["offer_ids"] = ",".join(product_ids)
    vars["coach"] = speech
    vars["route"] = "speak"
    vars["neg_phase"] = "offer"


def queue_pending(vars, rows):
    packed = []
    for row in rows:
        packed.append("|".join([row["product_id"], money(row["amount"]), row["date"], row["label"].replace("|", "/")]))
    vars["pending"] = ";".join(packed)


def pending_rows(vars):
    rows = []
    for bit in split_queue(vars.get("pending") or ""):
        parts = bit.split("|")
        if len(parts) < 4:
            continue
        row = {}
        row["product_id"] = parts[0]
        row["amount"] = parts[1]
        row["date"] = parts[2]
        row["label"] = parts[3]
        rows.append(row)
    return rows


def readback(vars, preface):
    rows = pending_rows(vars)
    bits = []
    for row in rows:
        when = date.fromisoformat(row["date"])
        bits.append("your " + row["label"] + " for " + row["amount"] + " on " + speak_day(when))
    text = (preface + " " if preface else "") + "I will record " + "; ".join(bits) + ". Do you confirm?"
    vars["coach"] = text
    vars["neg_phase"] = "confirm"
    vars["offer_open"] = "no"
    vars["route"] = "speak"


def add_pending(vars, rows):
    incoming = set(row["product_id"] for row in rows)
    kept = [row for row in pending_rows(vars) if row["product_id"] not in incoming]
    kept.extend(rows)
    queue_pending(vars, kept)


def build_from_date(products, day, amount_for, today, holidays):
    rows = []
    notes = []
    adjusted = False
    for item in products:
        fitted, why = fit_date(day, item, today, holidays)
        if why != "ok":
            adjusted = True
            if why == "not_business":
                notes.append(speak_day(day) + " is not a business day for your " + item["label"] + ". The next business day is " + speak_day(fitted) + ".")
            else:
                notes.append("The latest date I can record for your " + item["label"] + " is " + speak_day(fitted) + ".")
        row = {}
        row["product_id"] = item["product_id"]
        row["amount"] = amount_for(item)
        row["date"] = fitted.isoformat()
        row["label"] = item["label"]
        rows.append(row)
    return rows, notes, adjusted


def explicit_amounts(text, products):
    months = "|".join(MONTHS.keys())
    low = " " + text.lower().replace(",", " ") + " "
    low = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", low)
    low = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", " ", low)
    low = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:" + months + r")\b", " ", low)
    low = re.sub(r"\b(?:" + months + r")\s+(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\b", " ", low)
    low = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)\b", " ", low)
    low = re.sub(r"\b\d{1,3}\s+days?\b", " ", low)
    low = re.sub(r"\b(?:19|20)\d{2}\b", " ", low)
    for item in products or []:
        last4 = str(item.get("last4") or "")
        if last4:
            low = re.sub(r"\b" + re.escape(last4) + r"\b", " ", low)
    found = []
    for match in re.finditer(r"(?<!\d)(\d{1,6}(?:\.\d{1,2})?)(?!\d)", low):
        found.append((match.start(), float(match.group(1))))
    return found


def customer_proposal(said, products, today):
    if explicit_amounts(said, products):
        return True
    if any(day >= today for day in find_dates(said, today)):
        return True
    low = said.lower()
    return any(phrase in low for phrase in VAGUE)


def held_map(vars):
    found = {}
    for bit in str(vars.get("held_amounts") or "").split(","):
        if "=" not in bit:
            continue
        pid, raw = bit.split("=", 1)
        try:
            found[pid] = float(raw)
        except Exception:
            continue
    return found


def save_held(vars, mapping):
    bits = []
    for pid in mapping:
        bits.append(str(pid) + "=" + money(mapping[pid]))
    vars["held_amounts"] = ",".join(bits)


def product_positions(text, products):
    low = text.lower()
    spots = []
    for item in products:
        labels = []
        if item.get("type") == "credit_card":
            labels.append("credit card")
        elif item.get("type") == "personal_loan":
            labels.append("personal loan")
        elif item.get("type") == "car_loan":
            labels.extend(["car loan", "auto loan"])
        label = str(item.get("label") or "")
        if label:
            labels.append(label)
        last4 = str(item.get("last4") or "")
        if last4:
            labels.append(last4)
        best = None
        for name in labels:
            at = low.find(name.lower())
            if at >= 0 and (best is None or at < best):
                best = at
        if best is not None:
            spots.append((best, item["product_id"]))
    return spots


def negotiation_targets(said, products, vars, phase):
    if len(products) == 1 or (wants_all(said, products) and not is_no(said)):
        return list(products)
    low = said.lower()
    hits = mentioned(said, products)
    cut = len(low)
    for token in ("refus", "not the", "won't", "will not pay", "but not"):
        at = low.find(token)
        if at >= 0:
            cut = min(cut, at)
    pay_hits = []
    for index in hits:
        label = products[index]["type"].replace("_", " ")
        pos = low.find(label)
        if pos >= 0 and pos < cut:
            pay_hits.append(index)
    if pay_hits:
        return [products[index] for index in pay_hits]
    if hits and not is_no(said):
        return [products[index] for index in hits]
    if phase in ("per", "offer"):
        current = current_product(vars, products) or products[0]
        return [current]
    return list(products)


def proposed_amount_map(text, products, targets):
    found = explicit_amounts(text, products)
    mapping = {}
    if not found:
        return mapping
    target_ids = [item["product_id"] for item in targets]
    if len(found) == 1 and len(targets) == 1:
        mapping[targets[0]["product_id"]] = found[0][1]
        return mapping
    spots = [(pos, pid) for pos, pid in product_positions(text, products) if pid in target_ids]
    if not spots:
        return mapping
    for pos, amount in found:
        nearest = spots[0][1]
        best = None
        for spot, pid in spots:
            dist = abs(spot - pos)
            if best is None or dist < best:
                best = dist
                nearest = pid
        mapping[nearest] = amount
    return mapping


def pending_day(vars, item):
    for row in pending_rows(vars):
        if row["product_id"] == item["product_id"]:
            return date.fromisoformat(row["date"])
    offer_ids = [bit for bit in str(vars.get("offer_ids") or "").split(",") if bit]
    if vars.get("offer_date") and item["product_id"] in offer_ids:
        return date.fromisoformat(str(vars.get("offer_date")))
    return None


def chosen_amount(item, said, products, targets, vars):
    """Return (amount, explicit). Explicit amounts are never replaced by the balance here."""
    mapping = proposed_amount_map(said, products, targets)
    if item["product_id"] in mapping:
        return mapping[item["product_id"]], True
    held = held_map(vars)
    if item["product_id"] in held:
        return held[item["product_id"]], True
    for row in pending_rows(vars):
        if row["product_id"] == item["product_id"]:
            return float(row["amount"]), False
    if is_too_much(said) or vars.get("too_much") == "yes":
        return float(item["floor"]), False
    return float(item["past_due"]), False


def date_note(day, fitted, why, item):
    if why == "ok":
        return ""
    if why == "not_business":
        return speak_day(day) + " is not a business day for your " + item["label"] + ". The next business day is " + speak_day(fitted) + "."
    return "The latest date I can record for your " + item["label"] + " is " + speak_day(fitted) + "."


def bound_note(kind, proposed, bound):
    if kind == "below":
        return "I cannot record " + money(proposed) + ". The least I can record is " + money(bound) + ". The rest stays overdue."
    return "I cannot record " + money(proposed) + ". The most I can record is " + money(bound) + "."


def classify_explicit(item, amount):
    floor = float(item["floor"])
    past = float(item["past_due"])
    if amount + 0.001 < floor:
        return "below", floor
    if amount > past + 0.001:
        return "above", past
    return "ok", amount


def is_yes(said):
    low = said.lower()
    if re.search(r"\b(no|not|won't|cannot|can't)\b", low) or "don't" in low or "do not" in low:
        if "confirm" not in low:
            return False
    bare = re.sub(r"[^a-z ]", "", low).strip()
    if bare in ("yes", "yes i confirm", "i confirm", "confirm", "yeah", "yep", "ok", "okay", "correct", "that is right", "sure"):
        return True
    if "i confirm" in low or "yes i confirm" in low:
        return True
    if any(token in low for token in ("i accept", "that works", "i agree", "i can do that", "sounds good", "i will pay that", "i'll pay that", "that's fine", "thats fine")):
        return True
    return False


END_PHRASES = (
    "do not want to talk", "don't want to talk", "do not want to speak", "don't want to speak",
    "do not want to continue", "don't want to continue", "stop talking", "end the call",
    "end this call", "hang up", "leave me alone",
)
UNAVAILABLE_PHRASES = (
    "can't talk", "cannot talk", "can't speak", "cannot speak", "not a good time", "bad time",
    "call me back", "call you back", "callback", "call later", "busy right now", "in a meeting",
)


def wants_to_end(said):
    low = said.lower()
    return any(phrase in low for phrase in END_PHRASES)


def is_unavailable(said):
    if wants_to_end(said):
        return False
    low = said.lower()
    if any(token in low for token in ("pay", "promise", "amount", "balance")):
        return False
    return any(phrase in low for phrase in UNAVAILABLE_PHRASES)


def is_no(said):
    if wants_to_end(said) or is_unavailable(said):
        return False
    low = said.lower()
    if is_yes(said) and not re.search(r"\bno\b", low):
        return False
    if re.search(r"\b(no|nope|cannot|can't|won't|refuse|nothing|unable)\b", low):
        return True
    return any(phrase in low for phrase in ("will not", "not paying", "i don't want", "i do not want"))


def is_hardship(said):
    low = said.lower()
    return any(token in low for token in ("lost my job", "lost his job", "lost her job", "job loss", "unemployed", "laid off", "illness", "i am ill", "i'm ill", "sick", "hospital", "death in the family", "passed away", "funeral", "bereave"))


def is_paid(said):
    low = said.lower()
    return any(token in low for token in ("already paid", "i paid", "i've paid", "paid it", "paid this", "made the payment", "paid in the app"))


def is_dispute(said):
    low = said.lower()
    return any(token in low for token in ("not mine", "never had", "don't owe", "do not owe", "not my debt", "never took", "closed the account", "paid off"))


def is_restructure(said):
    low = said.lower()
    return any(token in low for token in ("payment plan", "lower instal", "lower install", "restructur", "reduce the instal", "reduce the install", "new plan"))


def is_human(said):
    low = said.lower()
    return any(token in low for token in ("real person", "human", "speak to someone", "speak to a person", "representative", "transfer me", "actual person"))


def is_too_much(said):
    low = said.lower()
    return any(token in low for token in ("too much", "too high", "can't afford the full", "cannot afford the full", "can't afford that", "cannot afford that", "more than i can"))


def is_discount(said):
    low = said.lower()
    return any(token in low for token in ("discount", "waiver", "write off", "write-off"))


def current_product(vars, products):
    index = int(vars.get("pi") or "0")
    if index < 0 or index >= len(products):
        return None
    return products[index]


def reserved_ids(vars):
    ids = set(filter(None, str(vars.get("noted_ids") or "").split(",")))
    ids.update(filter(None, str(vars.get("note_blocked") or "").split(",")))
    for bit in split_queue(vars.get("notes_queue") or ""):
        pid = bit.split("|", 1)[0]
        if pid:
            ids.add(pid)
    inflight = str(vars.get("note_inflight") or "")
    if inflight:
        ids.add(inflight)
    return ids


def unresolved(products, vars):
    done = set(filter(None, str(vars.get("recorded_ids") or "").split(",")))
    noted = reserved_ids(vars)
    pending_ids = set(row["product_id"] for row in pending_rows(vars))
    left = []
    for item in products:
        if item.get("usable") == "no":
            continue
        if item["product_id"] in done or item["product_id"] in noted or item["product_id"] in pending_ids:
            continue
        left.append(item)
    return left


def mark_note(vars, product_id, reason):
    if not product_id or product_id in reserved_ids(vars):
        return
    current = split_queue(vars.get("notes_queue") or "")
    current.append(str(product_id) + "|" + str(reason))
    vars["notes_queue"] = ";".join(current)


def clear_note_result(vars):
    vars["note_ok"] = ""
    vars["add_note_response.data.ok"] = ""


def speak_offer_for(vars, item, amount, day, tail):
    speech = "Can you pay " + money(amount) + " on " + speak_day(day) + " for your " + item["label"] + "?"
    if tail:
        speech = tail + " " + speech
    set_offer(vars, amount, day, [item["product_id"]], speech)


def start_attempt(vars, item, p, today, holidays, use_floor, preface):
    used = attempt_count(vars, item["product_id"])
    allowed = int(item["attempts"])
    if used >= allowed:
        reason = p.get("reason_refused") or "refused"
        mark_note(vars, item["product_id"], reason)
        advance_or_finish(vars, products_state(vars), p, today, holidays)
        return
    if used == 0:
        day = date.fromisoformat(item["attempt1"])
        amount = item["floor"] if use_floor else item["past_due"]
        fitted, _why = fit_date(day, item, today, holidays)
        tail = preface or ""
        if use_floor:
            tail = (tail + " " if tail else "") + "The least I can record is " + money(item["floor"]) + ". The rest stays overdue."
        speak_offer_for(vars, item, amount, fitted, tail.strip())
        set_attempt(vars, item["product_id"], 1)
        return
    day = date.fromisoformat(item["deadline"])
    tail = preface or ""
    tail = (tail + " " if tail else "") + "The least I can record is " + money(item["floor"]) + " on " + speak_day(day) + ". The rest stays overdue."
    speak_offer_for(vars, item, item["floor"], day, tail.strip())
    set_attempt(vars, item["product_id"], used + 1)


def advance_or_finish(vars, products, p, today, holidays):
    left = unresolved(products, vars)
    if left:
        vars["pi"] = str(products.index(left[0]))
        vars["neg_phase"] = "per"
        use_floor = vars.get("too_much") == "yes"
        start_attempt(vars, left[0], p, today, holidays, use_floor, "")
        return
    if pending_rows(vars):
        readback(vars, "")
        return
    drain_notes_or_close(vars, products, p)


def drain_notes_or_close(vars, products, p):
    if p.get("notes") == "yes":
        queue = split_queue(vars.get("notes_queue") or "")
        if queue:
            product_id, reason = queue[0].split("|", 1)
            vars["notes_queue"] = ";".join(queue[1:])
            vars["note_product"] = product_id
            vars["note_reason"] = reason
            vars["note_text"] = reason
            vars["note_inflight"] = product_id
            vars["note_tries"] = "0"
            clear_note_result(vars)
            vars["route"] = "note"
            return
    fault = "I could not store that note." if vars.get("note_fault") == "yes" else ""
    recorded = set(filter(None, str(vars.get("recorded_ids") or "").split(",")))
    if recorded:
        vars["promise_recorded"] = "yes"
        close_with(vars, "role_promise", "reason_blank", fault)
        vars["reason"] = ""
        return
    if p.get("notes") == "yes":
        paid_name = p.get("reason_paid") or "paid"
        reason = ""
        for bit in split_queue(vars.get("done_notes") or ""):
            _pid, why = bit.split("|", 1)
            if why != paid_name and not reason:
                reason = why
        if not reason:
            covered = set()
            for bit in split_queue(vars.get("done_notes") or ""):
                pid, why = bit.split("|", 1)
                if why == paid_name:
                    covered.add(pid)
            all_paid = bool(products)
            for item in products:
                if item["product_id"] not in covered:
                    all_paid = False
            if all_paid and vars.get("note_fault") != "yes":
                close_with(vars, "role_paid", "reason_blank", p.get("paid_line") or "")
                vars["reason"] = ""
                return
        if vars.get("note_fault") == "yes" and not reason:
            close_with(vars, "role_no_promise", "reason_service_error", fault)
            return
        vars["outcome"] = p.get("role_no_promise") or ""
        vars["reason"] = reason or (p.get("reason_refused") or "")
        vars["extra_line"] = fault if fault else " "
        vars["promise_line"] = " "
        farewell = "Thank you."
        if fault:
            farewell = farewell + " " + fault
        vars["farewell"] = farewell + " Goodbye."
        vars["route"] = "close"
        vars["offer_open"] = "no"
        return
    close_with(vars, "role_no_promise", "reason_refused", "")


def remember_done_note(vars, product_id, reason):
    current = split_queue(vars.get("done_notes") or "")
    current.append(product_id + "|" + reason)
    vars["done_notes"] = ";".join(current)


def arm_record(vars):
    queue = split_queue(vars.get("queue") or "")
    pos = int(vars.get("queue_pos") or "0")
    if pos >= len(queue):
        return False
    parts = queue[pos].split("|")
    vars["rec_product"] = parts[0]
    vars["rec_amount"] = parts[1]
    vars["rec_date"] = parts[2]
    vars["promise_ok"] = ""
    return True


def start_recording(vars):
    vars["held_amounts"] = ""
    rows = pending_rows(vars)
    packed = []
    for row in rows:
        packed.append(row["product_id"] + "|" + row["amount"] + "|" + row["date"])
    vars["queue"] = ";".join(packed)
    vars["queue_pos"] = "0"
    vars["record_tries"] = "0"
    vars["pending"] = ""
    if arm_record(vars):
        vars["route"] = "record"
    else:
        vars["route"] = "speak"


def accept_offer(vars):
    products = products_state(vars)
    ids = [bit for bit in str(vars.get("offer_ids") or "").split(",") if bit]
    rows = []
    for product_id in ids:
        item = product_by_id(products, product_id)
        if not item:
            continue
        row = {}
        row["product_id"] = product_id
        row["amount"] = vars.get("offer_amount") or money(item["past_due"])
        row["date"] = vars.get("offer_date") or item["deadline"]
        row["label"] = item["label"]
        rows.append(row)
    existing = pending_rows(vars)
    # Replace rows for the same products.
    kept = [row for row in existing if row["product_id"] not in ids]
    kept.extend(rows)
    queue_pending(vars, kept)
    for product_id in ids:
        mark_resolved_pending(vars, product_id)
    vars["offer_open"] = "no"


def mark_resolved_pending(vars, product_id):
    # Pending itself tracks the promise. Nothing else to mark.
    return product_id


def handle_paid(vars, products, p):
    if p.get("notes") == "yes" and len(products) > 1:
        item = current_product(vars, products) or products[0]
        # If they speak before per-product mode, note every product and close paid only when all are paid.
        if vars.get("neg_phase") == "ask_all" or wants_all(str(vars.get("user_said") or ""), products):
            for prod in products:
                if prod["product_id"] not in reserved_ids(vars):
                    mark_note(vars, prod["product_id"], p.get("reason_paid") or "paid")
            drain_notes_or_close(vars, products, p)
            return
        mark_note(vars, item["product_id"], p.get("reason_paid") or "paid")
        advance_or_finish(vars, products, p, parse_now(vars).date(), holidays_of(p))
        return
    close_with(vars, "role_paid", "reason_blank", p.get("paid_line") or "")
    vars["reason"] = ""


def handle_dispute(vars, products, p, today, holidays):
    if p.get("notes") == "yes" and len(products) > 1:
        hits = mentioned(str(vars.get("user_said") or ""), products)
        targets = [products[index] for index in hits] or unresolved(products, vars)[:1]
        for item in targets:
            mark_note(vars, item["product_id"], p.get("reason_dispute") or "dispute")
        advance_or_finish(vars, products, p, today, holidays)
        return
    close_with(vars, "role_no_promise", "reason_dispute", "I will not argue, and I will not take a promise.")


def refuse_current(vars, products, p, today, holidays):
    item = current_product(vars, products)
    if item is None:
        left = unresolved(products, vars)
        if not left:
            drain_notes_or_close(vars, products, p)
            return
        item = left[0]
        vars["pi"] = str(products.index(item))
    used = attempt_count(vars, item["product_id"])
    allowed = int(item["attempts"])
    # An open offer was just refused. used already counts offers made.
    if vars.get("offer_open") == "yes":
        if used >= allowed:
            mark_note(vars, item["product_id"], p.get("reason_refused") or "refused")
            vars["offer_open"] = "no"
            advance_or_finish(vars, products, p, today, holidays)
            return
        start_attempt(vars, item, p, today, holidays, vars.get("too_much") == "yes" or used >= 1, "")
        return
    start_attempt(vars, item, p, today, holidays, vars.get("too_much") == "yes", "")


def end_conversation(vars, products, p):
    """Count an explicit stop. The first one does not open a payment offer."""
    count = int(vars.get("stop_asks") or "0") + 1
    vars["stop_asks"] = str(count)
    vars["pending"] = ""
    vars["offer_open"] = "no"
    vars["held_amounts"] = ""
    phase = str(vars.get("call_phase") or "greet")
    if count < 2:
        line = "If you do not want to continue, please say so again and I will end the call."
        vars["coach"] = line
        vars["greet_line"] = line
        vars["id_line"] = line
        if phase == "verify":
            vars["route"] = "speak"
        elif phase == "callback":
            vars["route"] = "callback"
        elif phase == "greet":
            vars["route"] = "greet"
        else:
            vars["route"] = "speak"
        return
    if phase in ("greet", "verify", "callback"):
        close_with(vars, "role_not_verified", "reason_declined", "")
        return
    if p.get("notes") == "yes":
        reason = p.get("reason_refused") or "refused"
        for item in unresolved(products, vars):
            mark_note(vars, item["product_id"], reason)
        drain_notes_or_close(vars, products, p)
        return
    close_with(vars, "role_no_promise", "reason_refused", "")


def note_unavailable(vars, prefix):
    vars["pending"] = ""
    vars["offer_open"] = "no"
    vars["held_amounts"] = ""
    vars["neg_phase"] = "unavailable"
    line = "I will not take a payment while this is a bad time. Tell me if you want to continue, or say again if you want to end the call."
    vars["coach"] = (prefix + " " + line).strip()
    vars["route"] = "speak"


def after_customer(vars):
    said = str(vars.get("user_said") or "").strip()
    p = pol(vars)
    products = products_state(vars)
    today = parse_now(vars).date()
    holidays = holidays_of(p)
    vars["call_phase"] = "negotiate"
    if not products:
        close_with(vars, "role_no_promise", "reason_service_error", "")
        return
    if not said:
        vars["route"] = "speak"
        return
    low = said.lower()
    phase = vars.get("neg_phase") or "ask_all"
    prefix = ""
    if "robot" in low or re.search(r"\bai\b", low):
        prefix = (p.get("assistant_line") or "") + " "
    if "scam" in low:
        bank = p.get("bank") or "the bank"
        prefix += "You can verify this call by phoning " + bank + "'s customer service number. "

    if wants_to_end(said):
        end_conversation(vars, products, p)
        if prefix and vars.get("route") == "speak":
            vars["coach"] = prefix + str(vars.get("coach") or "")
        return
    paying = any(token in low for token in ("pay", "promise", "amount", "balance"))
    if is_unavailable(said) or (phase == "unavailable" and not paying and not is_dispute(said) and not is_paid(said) and not is_hardship(said)):
        note_unavailable(vars, prefix)
        return

    proposal = customer_proposal(said, products, today) or is_too_much(said)
    if phase == "confirm":
        other_intent = is_dispute(said) or is_paid(said) or is_restructure(said) or is_human(said) or (is_hardship(said) and not proposal)
        if other_intent:
            if is_dispute(said) and len(products) > 1 and mentioned(said, products):
                named = set(products[index]["product_id"] for index in mentioned(said, products))
                kept = [row for row in pending_rows(vars) if row["product_id"] not in named]
                if kept:
                    queue_pending(vars, kept)
                else:
                    vars["pending"] = ""
            else:
                vars["pending"] = ""
            vars["offer_open"] = "no"
            vars["held_amounts"] = ""
            vars["neg_phase"] = "ask_all"
        elif is_yes(said) and not proposal:
            start_recording(vars)
            return
        elif proposal:
            vars["neg_phase"] = "ask_all"
            vars["offer_open"] = "no"
        elif is_no(said):
            vars["pending"] = ""
            vars["held_amounts"] = ""
            vars["neg_phase"] = "ask_all"
            vars["offer_open"] = "no"
            refuse_current(vars, products, p, today, holidays)
            if prefix and vars.get("route") == "speak":
                vars["coach"] = prefix + str(vars.get("coach") or "")
            return
        else:
            vars["coach"] = prefix + "Do you confirm the amount and the date I just read back?"
            vars["route"] = "speak"
            return

    if phase == "hardship":
        if customer_proposal(said, products, today):
            vars["neg_phase"] = "ask_all"
        elif any(token in low for token in ("yes", "please", "connect", "transfer", "support")) and not is_no(said):
            vars["transfer_queue"] = p.get("queue_support") or ""
            vars["route"] = "transfer"
            vars["pending"] = ""
            return
        elif is_no(said) or "decline" in low:
            if p.get("notes") == "yes" and len(products) > 1:
                for item in unresolved(products, vars):
                    mark_note(vars, item["product_id"], p.get("reason_hardship") or "hardship")
                vars["pending"] = ""
                drain_notes_or_close(vars, products, p)
                return
            close_with(vars, "role_no_promise", "reason_hardship", "")
            return
        elif is_discount(said):
            vars["coach"] = prefix + "I cannot offer a discount, a waiver, or a new plan. I can connect you with the customer support team. Would you like that?"
            vars["route"] = "speak"
            return

    if phase == "human":
        if is_no(said) or is_human(said) or "insist" in low:
            vars["transfer_queue"] = p.get("queue_general") or ""
            vars["route"] = "transfer"
            vars["pending"] = ""
            return
        vars["neg_phase"] = "ask_all"
        vars["coach"] = prefix + (vars.get("coach_hold") or "Can you make this payment today?")
        vars["route"] = "speak"
        return

    if is_hardship(said) and not customer_proposal(said, products, today):
        vars["neg_phase"] = "hardship"
        vars["pending"] = ""
        vars["held_amounts"] = ""
        vars["offer_open"] = "no"
        sorry = "I am sorry to hear that."
        discount = ""
        if is_discount(said):
            discount = " I cannot offer a discount, a waiver, or a new plan."
        vars["coach"] = prefix + sorry + discount + " I can connect you with the customer support team. Would you like that?"
        vars["route"] = "speak"
        return
    if is_hardship(said) and "sorry" not in prefix.lower():
        prefix = "I am sorry to hear that. " + prefix
    if is_dispute(said):
        handle_dispute(vars, products, p, today, holidays)
        if prefix and vars.get("route") == "speak":
            vars["coach"] = prefix + str(vars.get("coach") or "")
        return
    if is_paid(said):
        handle_paid(vars, products, p)
        return
    if is_restructure(said):
        vars["transfer_queue"] = p.get("queue_restructuring") or ""
        vars["pending"] = ""
        vars["route"] = "transfer"
        return
    if is_human(said):
        vars["neg_phase"] = "human"
        vars["coach_hold"] = vars.get("coach") or ""
        vars["coach"] = prefix + "I can help with this first. Would you like to continue with me?"
        vars["route"] = "speak"
        return
    if is_discount(said):
        vars["coach"] = prefix + "I cannot offer a discount, a waiver, or a new plan. " + (vars.get("coach") or "")
        vars["route"] = "speak"
        return

    dates = [item for item in find_dates(said, today) if item >= today]
    vague = any(phrase in low for phrase in VAGUE) and not dates
    targets = negotiation_targets(said, products, vars, phase)
    held = held_map(vars)
    if held and not mentioned(said, products) and not wants_all(said, products):
        held_targets = [item for item in products if item["product_id"] in held]
        if held_targets:
            targets = held_targets
    stated = explicit_amounts(said, products)
    amount_map = proposed_amount_map(said, products, targets)

    def finish_rows(rows, notes, blocked):
        vars["held_amounts"] = ""
        if blocked:
            banned = set(item["product_id"] for item, _bound, _proposed, _kind, _fitted in blocked)
            kept_rows = [row for row in pending_rows(vars) if row["product_id"] not in banned]
            if kept_rows:
                queue_pending(vars, kept_rows)
            else:
                vars["pending"] = ""
        if not rows and not blocked:
            vars["coach"] = prefix + "Which product should I record that payment against?"
            vars["route"] = "speak"
            vars["offer_open"] = "no"
            return True
        if blocked and not rows:
            item, bound, proposed, kind, fitted = blocked[0]
            speak_offer_for(vars, item, bound, fitted, (prefix + " " + bound_note(kind, proposed, bound)).strip())
            return True
        if rows:
            add_pending(vars, rows)
        if blocked:
            item, bound, proposed, kind, fitted = blocked[0]
            speech = " ".join(bit for bit in notes if bit)
            tail = (speech + " " + bound_note(kind, proposed, bound)).strip()
            speak_offer_for(vars, item, bound, fitted, (prefix + " " + tail).strip())
            return True
        speech = " ".join(bit for bit in notes if bit)
        left = unresolved(products, vars)
        if left and len(targets) != len(products):
            vars["preface"] = ((vars.get("preface") or "") + " " + speech).strip()
            vars["pi"] = str(products.index(left[0]))
            vars["neg_phase"] = "per"
            start_attempt(vars, left[0], p, today, holidays, vars.get("too_much") == "yes", prefix.strip())
            if prefix and vars.get("coach"):
                vars["coach"] = prefix + str(vars.get("coach") or "")
            return True
        stored = ((vars.get("preface") or "") + " " + speech).strip()
        readback(vars, (prefix + " " + stored).strip())
        return True

    def split_amounts(day_for):
        rows = []
        notes = []
        blocked = []
        for item in targets:
            raw, explicit = chosen_amount(item, said, products, targets, vars)
            if stated and not explicit and item["product_id"] not in amount_map and len(targets) > 1:
                continue
            day = day_for(item)
            fitted, why = fit_date(day, item, today, holidays)
            if explicit:
                kind, bound = classify_explicit(item, raw)
                if kind != "ok":
                    blocked.append((item, bound, raw, kind, fitted))
                    continue
            note = date_note(day, fitted, why, item)
            if note:
                notes.append(note)
            row = {}
            row["product_id"] = item["product_id"]
            row["amount"] = money(raw)
            row["date"] = fitted.isoformat()
            row["label"] = item["label"]
            rows.append(row)
        if is_too_much(said) and not stated:
            vars["too_much"] = "yes"
            notes = ["The least I can record is the minimum, and the rest stays overdue."] + notes
        return rows, notes, blocked

    if vague:
        if stated:
            blocked = []
            kept = {}
            for item in targets:
                if item["product_id"] not in amount_map:
                    continue
                kind, bound = classify_explicit(item, amount_map[item["product_id"]])
                if kind != "ok":
                    blocked.append((item, bound, amount_map[item["product_id"]], kind, date.fromisoformat(item["attempt1"])))
                else:
                    kept[item["product_id"]] = amount_map[item["product_id"]]
            if blocked:
                finish_rows([], [], blocked)
                return
            if kept:
                save_held(vars, kept)
        if vars.get("asked_exact") == "yes":
            rows = []
            pool = [item for item in (unresolved(products, vars) or products) if not held or item["product_id"] in held or item["product_id"] in amount_map]
            if not pool:
                pool = unresolved(products, vars) or products
            saved = held_map(vars)
            for item in pool:
                row = {}
                row["product_id"] = item["product_id"]
                row["amount"] = money(saved.get(item["product_id"], item["past_due"]))
                row["date"] = item["deadline"]
                row["label"] = item["label"]
                rows.append(row)
            vars["held_amounts"] = ""
            queue_pending(vars, rows)
            readback(vars, (prefix + " I still need a day, so I will use the latest date I can record.").strip())
            return
        vars["asked_exact"] = "yes"
        vars["coach"] = prefix + "I need the exact day. Which date should I record?"
        vars["route"] = "speak"
        vars["offer_open"] = "no"
        return

    if dates:
        day = dates[-1]
        rows, notes, blocked = split_amounts(lambda _item: day)
        finish_rows(rows, notes, blocked)
        return

    if stated:
        if not amount_map and len(targets) > 1:
            vars["coach"] = prefix + "Which product should I record " + money(stated[-1][1]) + " against?"
            vars["route"] = "speak"
            vars["offer_open"] = "no"
            return
        dated = [item for item in targets if pending_day(vars, item)]
        if dated:
            rows, notes, blocked = split_amounts(lambda item: pending_day(vars, item) or today)
            finish_rows(rows, notes, blocked)
            return
        blocked = []
        kept = {}
        for item in targets:
            if item["product_id"] not in amount_map:
                continue
            kind, bound = classify_explicit(item, amount_map[item["product_id"]])
            if kind != "ok":
                blocked.append((item, bound, amount_map[item["product_id"]], kind, date.fromisoformat(item["attempt1"])))
            else:
                kept[item["product_id"]] = amount_map[item["product_id"]]
        if blocked and not kept:
            finish_rows([], [], blocked)
            return
        if kept:
            save_held(vars, kept)
            shown = money(list(kept.values())[-1])
            vars["coach"] = prefix + "Which day should I record " + shown + "?"
            vars["route"] = "speak"
            vars["offer_open"] = "no"
            return

    if is_too_much(said):
        vars["too_much"] = "yes"
        item = current_product(vars, products) if phase == "per" else products[0]
        if len(products) > 1 and phase == "ask_all":
            item = products[int(vars.get("pi") or "0")]
        day = date.fromisoformat(item["attempt1"])
        speech = "The least I can record is " + money(item["floor"]) + ". The rest stays overdue. Can you pay " + money(item["floor"]) + " on " + speak_day(day) + " for your " + item["label"] + "?"
        set_offer(vars, item["floor"], day, [item["product_id"]], prefix + speech)
        set_attempt(vars, item["product_id"], max(1, attempt_count(vars, item["product_id"])))
        return

    if (is_yes(said) or "you tell me" in low) and vars.get("offer_open") == "yes":
        if "you tell me" in low:
            vars["coach"] = prefix + str(vars.get("coach") or "")
            vars["route"] = "speak"
            return
        accept_offer(vars)
        if len(products) > 1:
            left = unresolved(products, vars)
            if left and phase != "confirm":
                vars["pi"] = str(products.index(left[0]))
                start_attempt(vars, left[0], p, today, holidays, vars.get("too_much") == "yes", prefix.strip())
                return
        readback(vars, prefix.strip())
        return

    if phase == "ask_all" and is_yes(said) and not is_no(said):
        rows, notes, adjusted = build_from_date(products, today, lambda item: item["past_due"], today, holidays)
        queue_pending(vars, rows)
        readback(vars, " ".join(notes))
        return

    if is_no(said) or (phase == "ask_all" and re.search(r"\btoday\b", low) and is_no(said)):
        if len(products) > 1 and phase == "ask_all" and not vars.get("offer_open") == "yes":
            vars["neg_phase"] = "per"
            vars["pi"] = "0"
            start_attempt(vars, products[0], p, today, holidays, vars.get("too_much") == "yes", prefix.strip())
            return
        refuse_current(vars, products, p, today, holidays)
        if prefix and vars.get("route") == "speak":
            vars["coach"] = prefix + str(vars.get("coach") or "")
        return

    vars["coach"] = prefix + (vars.get("coach") or "Can you make this payment today?")
    vars["route"] = "speak"


def after_record(vars):
    p = pol(vars)
    products = products_state(vars)
    ok = truthy(pick(vars, "promise_ok", "create_promise_response.data.ok"))
    tries = int(vars.get("record_tries") or "0")
    if ok:
        product_id = str(vars.get("rec_product") or "")
        recorded = [bit for bit in str(vars.get("recorded_ids") or "").split(",") if bit]
        if product_id and product_id not in recorded:
            recorded.append(product_id)
        vars["recorded_ids"] = ",".join(recorded)
        vars["promise_recorded"] = "yes"
        vars["promise_line"] = p.get("sentence") or ""
        vars["record_tries"] = "0"
        vars["queue_pos"] = str(int(vars.get("queue_pos") or "0") + 1)
        if arm_record(vars):
            vars["route"] = "record"
            return
        drain_notes_or_close(vars, products, p)
        if vars.get("promise_recorded") == "yes" and vars.get("route") == "close":
            vars["promise_line"] = p.get("sentence") or ""
            vars["outcome"] = p.get("role_promise") or vars.get("outcome") or ""
            if not split_queue(vars.get("notes_queue") or ""):
                vars["reason"] = ""
        return
    tries += 1
    vars["record_tries"] = str(tries)
    if tries < 2:
        vars["promise_ok"] = ""
        vars["promise_line"] = ""
        vars["route"] = "record"
        return
    product_id = str(vars.get("rec_product") or "")
    if p.get("notes") == "yes":
        mark_note(vars, product_id, p.get("reason_service_error") or "service_error")
    vars["queue_pos"] = str(int(vars.get("queue_pos") or "0") + 1)
    if arm_record(vars):
        vars["record_tries"] = "0"
        vars["route"] = "record"
        return
    if vars.get("promise_recorded") == "yes":
        drain_notes_or_close(vars, products, p)
        return
    close_with(vars, "role_no_promise", "reason_service_error", "I could not record that.")


def after_note(vars):
    p = pol(vars)
    ok_raw = pick(vars, "note_ok", "add_note_response.data.ok")
    product_id = str(vars.get("note_product") or "")
    reason = str(vars.get("note_reason") or "")
    if truthy(ok_raw):
        if product_id:
            noted = set(filter(None, str(vars.get("noted_ids") or "").split(",")))
            noted.add(product_id)
            vars["noted_ids"] = ",".join(sorted(noted))
            remember_done_note(vars, product_id, reason)
        vars["note_tries"] = "0"
        vars["note_inflight"] = ""
        vars["note_ok"] = ""
        drain_notes_or_close(vars, products_state(vars), p)
        return
    # A false ok means nothing was stored, so one repeat is safe. A missing ok can be a
    # timeout after the write. There is no idempotency key and no note lookup, so do not resend.
    if falsey(ok_raw) and int(vars.get("note_tries") or "0") < 1:
        vars["note_tries"] = "1"
        clear_note_result(vars)
        vars["route"] = "note"
        return
    vars["note_tries"] = "0"
    vars["note_fault"] = "yes"
    vars["note_inflight"] = ""
    clear_note_result(vars)
    if product_id:
        blocked = set(filter(None, str(vars.get("note_blocked") or "").split(",")))
        blocked.add(product_id)
        vars["note_blocked"] = ",".join(sorted(blocked))
    drain_notes_or_close(vars, products_state(vars), p)


def after_transfer(vars):
    p = pol(vars)
    ok = truthy(pick(vars, "transfer_ok", "transfer_to_agent_response.data.ok"))
    queue = str(vars.get("transfer_queue") or pick(vars, "transfer_to_agent_args.queue") or "")
    if not ok and int(vars.get("transfer_tries") or "0") < 1:
        vars["transfer_tries"] = "1"
        vars["route"] = "transfer"
        return
    vars["notes_queue"] = ""
    vars["pending"] = ""
    if queue == (p.get("queue_support") or ""):
        reason_key = "reason_support"
    elif queue == (p.get("queue_restructuring") or ""):
        reason_key = "reason_restructuring"
    else:
        reason_key = "reason_human"
    extra = "I am connecting you now."
    close_with(vars, "role_transferred", reason_key, extra)
    if not ok:
        vars["extra_line"] = "I could not transfer the call."


def after_callback_utterance(vars):
    vars["call_phase"] = "callback"
    said = str(vars.get("user_said") or "").strip()
    if not said:
        vars["route"] = "callback"
        return
    if party_kind(said, vars) == "deceased":
        close_with(vars, "role_not_reached", "reason_deceased", pol(vars).get("sorry") or "")
        return
    if party_kind(said, vars) == "wrong":
        close_with(vars, "role_not_reached", "reason_wrong_number", "")
        return
    review_callback_text(said, vars, pol(vars))


def stall(vars):
    if str(vars.get("outcome") or ""):
        vars["route"] = "close"
        if not vars.get("extra_line"):
            vars["extra_line"] = ""
        if not vars.get("promise_line"):
            vars["promise_line"] = ""
        return
    phase = str(vars.get("call_phase") or "")
    if phase in ("greet", "callback"):
        close_with(vars, "role_not_reached", "reason_unclear", "")
    elif phase == "verify":
        close_with(vars, "role_not_verified", "reason_declined", "")
    elif vars.get("promise_recorded") == "yes":
        close_with(vars, "role_promise", "reason_blank", "")
        vars["reason"] = ""
    else:
        close_with(vars, "role_no_promise", "reason_refused", "")


def after_callback_api(vars):
    ok = truthy(pick(vars, "callback_ok", "schedule_callback_response.data.ok"))
    if ok:
        close_with(vars, "role_not_reached", "reason_callback", "I have scheduled the callback.")
        return
    if int(vars.get("cb_api_tries") or "0") < 1:
        vars["cb_api_tries"] = "1"
        vars["route"] = "callback_api"
        return
    close_with(vars, "role_not_reached", "reason_no_callback", "I could not schedule a callback.")
