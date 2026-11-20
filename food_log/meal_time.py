from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

CATEGORY_WORDS = {
    "завтрак": "Завтрак", "обед": "Обед", "ужин": "Ужин",
    "полдник": "Полдник", "перекус": "Перекус",
}
PATTERN = re.compile(
    r"(?:^|[.!?\n;,]\s*|\b(?:на|это|был|была|было|а|утром|дн[её]м|вечером|ночью)\s+)"
    r"(?:не\s+)?(?:(?:поздний|ранний)\s+)?(завтрак|обед|ужин|полдник|перекус)\w*\b",
    re.IGNORECASE)


MONTHS = {name: i for i, name in enumerate((
    "января", "февраля", "марта", "апреля", "мая", "июня", "июля",
    "августа", "сентября", "октября", "ноября", "декабря"), 1)}
DATE_PATTERN = re.compile(
    r"(?<![\d.])(?P<iso>\d{4}-\d{2}-\d{2})(?!\d)|"
    r"(?<![\d.])(?P<numeric>\d{1,2}\.\d{2}(?:\.\d{4}|(?!\s*(?:г|гр|кг|мл|л|грамм\w*|порци\w*)\b)))(?!\d|\.\d)|"
    r"\b(?P<named>\d{1,2}\s+(?:" + "|".join(MONTHS) + r")(?:\s+\d{4})?)\b|"
    r"\b(?P<relative>позавчера|вчера(?:шн(?:ий|яя|ее|его))?|сегодня(?:шн(?:ий|яя|ее|его))?)\b",
    re.IGNORECASE)
TIME_PATTERN = re.compile(
    r"(?<![\d:])(?:\bв\s+)?(?P<hour>\d{1,2}):(?P<minute>\d{2})(?![\d:])"
    r"(?:\s*(?P<period>утра|дня|вечера|ночи))?|"
    r"\bв\s+(?P<whole>\d{1,2})(?![\d:])(?:\s+час(?:а|ов)?)?"
    r"(?:\s+(?P<whole_period>утра|дня|вечера|ночи))?(?!\s*(?:г\b|мл\b|кг\b|шт\b))",
    re.IGNORECASE)


class MealTimeError(ValueError):
    pass


@dataclass(frozen=True)
class MealMoment:
    eaten_at: int
    category: str
    time_explicit: bool


def _date_matches(text):
    matches = []
    for match in DATE_PATTERN.finditer(text):
        if match.lastgroup == "numeric" and match.group().count(".") == 1:
            # Короткая дата неоднозначна: 1.50 стакана — количество, а не 50-й месяц.
            prefix, suffix = text[:match.start()], text[match.end():]
            explicit = re.search(r"\bдат[ау]\s*[:=]?\s*$", prefix, re.IGNORECASE)
            if not explicit:
                prefix = PATTERN.sub(" ", prefix)
                prefix = re.sub(r"\b(?:это|было|на|утром|дн[её]м|вечером|ночью)\b", " ",
                                prefix, flags=re.IGNORECASE)
                follows_date = re.match(
                    r"\s*(?:$|[,;.!?]|(?:в\s+\d+|завтрак|обед|ужин|полдник|перекус|поздний|ранний)\b)",
                    suffix, re.IGNORECASE)
                if prefix.strip(" .,;:!?—-\n") or not follows_date:
                    continue
        matches.append(match)
    return matches


def _without_datetime(text):
    for match in reversed(_date_matches(text)):
        text = text[:match.start()] + " " + text[match.end():]
    return TIME_PATTERN.sub(" ", text).strip()


def metadata_only(text):
    stripped = _without_datetime(text)
    stripped = PATTERN.sub(" ", stripped)
    stripped = re.sub(r"\b(?:это|был[ао]?|на|а|не|дата|время|при[её]ма?|пищи|"
                      r"перенеси|исправь|уточнение|поправка|поздний|ранний)\b", " ", stripped,
                      flags=re.IGNORECASE)
    return bool(_date_matches(text) or TIME_PATTERN.search(text) or
                PATTERN.search(_without_datetime(text))) and not stripped.strip(" .,;:!?—-\n")


def _date_value(match, anchor):
    if match.lastgroup == "relative":
        value = match.group().lower()
        days = 2 if value == "позавчера" else 1 if value.startswith("вчера") else 0
        return anchor.date() - timedelta(days=days)
    if match.lastgroup == "iso":
        return date.fromisoformat(match.group())
    parts = match.group().lower().split() if match.lastgroup == "named" else match.group().split(".")
    day, month = int(parts[0]), MONTHS[parts[1]] if match.lastgroup == "named" else int(parts[1])
    return date(int(parts[2]) if len(parts) > 2 else anchor.year, month, day)


def _clock_value(match):
    hour = int(match.group("hour") or match.group("whole"))
    minute = int(match.group("minute") or 0)
    period = (match.group("period") or match.group("whole_period") or "").lower()
    if period:
        if not 1 <= hour <= 12:
            raise ValueError
        hour %= 12
        if period in ("дня", "вечера"):
            hour += 12
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError
    return hour, minute


def resolve_meal_time(original_at, timezone, evidence):
    zone = ZoneInfo(timezone)
    original = datetime.fromtimestamp(original_at, zone)
    day, clock = original.date(), (original.hour, original.minute, original.second)
    time_explicit, date_error, time_error = False, None, None
    for event in sorted(evidence, key=lambda e: (e["version"], e.get("sequence", 0))):
        anchor = datetime.fromtimestamp(event.get("sent_at", event["version"]), zone)
        for match in _date_matches(event["body"]):
            try:
                day, date_error = _date_value(match, anchor), None
            except ValueError:
                date_error = "Неверная дата. Пример: 19.11.2026 или вчера."
        for match in TIME_PATTERN.finditer(event["body"]):
            try:
                hour, minute = _clock_value(match)
                clock, time_explicit, time_error = (hour, minute, 0), True, None
            except ValueError:
                time_error = "Неверное время. Пример: в 20:30 (от 00:00 до 23:59)."
    if date_error or time_error:
        raise MealTimeError(date_error or time_error)
    local = datetime(day.year, day.month, day.day, *clock, tzinfo=zone)
    # Не принимаем несуществующее местное время при переходе на летнее время.
    stamp = int(local.timestamp())
    if datetime.fromtimestamp(stamp, zone).replace(tzinfo=None) != local.replace(tzinfo=None):
        raise MealTimeError("Такого местного времени нет в настроенном часовом поясе.")
    return MealMoment(stamp, meal_category(stamp, timezone, evidence), time_explicit)


def is_food_correction(text):
    if metadata_only(text) or PATTERN.search(_without_datetime(text)):
        return True
    return bool(re.search(
        r"\b(?:уточнение|поправка|исправление|съел\w*|съеден\w*|доел\w*|порци\w*|вес|грамм\w*|"
        r"половин\w*|треть|четверть|оцени\w*|пересчитай|посчитай)\b|"
        r"\d+\s*(?:г\b|гр\b|кг\b|мл\b|шт\b|%)|"
        r"^(?:на самом деле|не\s+.+,\s*а)\b|"
        r"\b(?:без|с)\s+(?:сахар\w*|масл\w*|молок\w*|соус\w*|слив\w*|майонез\w*)\b",
        text, re.IGNORECASE))


def meal_category(timestamp, timezone, evidence):
    hour = datetime.fromtimestamp(timestamp, ZoneInfo(timezone)).hour
    if 6 <= hour < 11:
        category = "Завтрак"
    elif 11 <= hour < 16:
        category = "Обед"
    elif 16 <= hour < 18:
        category = "Полдник"
    elif 18 <= hour < 23:
        category = "Ужин"
    else:
        category = "Перекус"
    for event in sorted(evidence, key=lambda event: (event["version"], event.get("sequence", 0))):
        matches = list(PATTERN.finditer(_without_datetime(event["body"])))
        if matches:
            category = CATEGORY_WORDS[matches[-1].group(1).lower()]
    return category
