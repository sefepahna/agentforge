"""Turn service amounts and dates into speech using a case spec."""

ONES = (
    "sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz",
)
TENS = (
    "", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan",
)
MONTHS = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)
FRONT = set("eiöü")
ROUND = set("oöuü")
VOICELESS = set("çfhkpşst")
HUNDRED = 100
THOUSAND = 1000
MILLION = 1000000
MINOR_SCALE = 100


def digits_spoken(text):
    parts = []
    for char in str(text):
        if char.isdigit():
            parts.append(ONES[int(char)])
    return " ".join(parts)


def cardinal(value):
    number = int(value)
    if number == 0:
        return ONES[0]
    return _cardinal(number)


def speak_date(value):
    day_text, month_text, year_text = str(value).split(".")
    month = MONTHS[int(month_text) - 1]
    return str(int(day_text)) + " " + month + " " + year_text


def copula(word):
    last_vowel = "a"
    for char in tr_lower(word):
        if char in "aeıioöuü":
            last_vowel = char
    if last_vowel in FRONT and last_vowel in ROUND:
        vowel = "ü"
    elif last_vowel in FRONT:
        vowel = "i"
    elif last_vowel in ROUND:
        vowel = "u"
    else:
        vowel = "ı"
    tail = tr_lower(word)[-1:] or "a"
    consonant = "t" if tail in VOICELESS else "d"
    return "'" + consonant + vowel + "r"


def tr_lower(text):
    return str(text).replace("İ", "i").replace("I", "ı").lower()


def speak_money(amount, code, spec):
    names = spec["policy"]["currency_names"]
    name = names[code]
    whole, minor = _split(amount)
    if minor == 0:
        return cardinal(whole) + " " + name
    unit = "lira" if code == "TL" else tr_lower(name)
    minor_name = spec["policy"]["minor_units"][code]
    return cardinal(whole) + " " + unit + " " + cardinal(minor) + " " + minor_name


def fill_money(template, token, amount, code, spec):
    spoken = speak_money(amount, code, spec)
    name = spec["policy"]["currency_names"][code]
    with_copula = token + " " + code + "'dir"
    plain = token + " " + code
    has_minor = any(unit in spoken for unit in spec["policy"]["minor_units"].values())
    if with_copula in template:
        suffix = "" if has_minor else copula(name)
        return template.replace(with_copula, spoken + suffix, 1)
    if plain in template:
        return template.replace(plain, spoken, 1)
    return template


def week_list(weeks):
    labels = [str(week) + "." for week in weeks]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " ya da " + labels[-1]


def _split(amount):
    text = "%.2f" % abs(float(amount))
    whole, minor = text.split(".")
    return int(whole), int(minor)


def _cardinal(number):
    parts = []
    millions = number // MILLION
    thousands = (number % MILLION) // THOUSAND
    rest = number % THOUSAND
    if millions:
        parts.append("milyon" if millions == 1 else _under_thousand(millions) + " milyon")
    if thousands:
        parts.append("bin" if thousands == 1 else _under_thousand(thousands) + " bin")
    if rest or not parts:
        parts.append(_under_thousand(rest))
    return " ".join(parts)


def _under_thousand(number):
    if number < HUNDRED:
        return _under_hundred(number)
    hundreds = number // HUNDRED
    rest = number % HUNDRED
    head = "yüz" if hundreds == 1 else ONES[hundreds] + " yüz"
    if rest == 0:
        return head
    return head + " " + _under_hundred(rest)


def _under_hundred(number):
    if number < 10:
        return ONES[number]
    ten = number // 10
    rest = number % 10
    if rest == 0:
        return TENS[ten]
    return TENS[ten] + " " + ONES[rest]
