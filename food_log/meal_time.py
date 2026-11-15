from datetime import datetime
import re
from zoneinfo import ZoneInfo

CATEGORY_WORDS = {
    "завтрак": "Завтрак", "обед": "Обед", "ужин": "Ужин",
    "полдник": "Полдник", "перекус": "Перекус",
}
PATTERN = re.compile(
    r"(?:^|[.!?\n;,]\s*|\b(?:на|это|был|была|было|а)\s+)"
    r"(?:не\s+)?(?:(?:поздний|ранний)\s+)?(завтрак|обед|ужин|полдник|перекус)\w*\b",
    re.IGNORECASE)


def is_food_correction(text):
    if PATTERN.search(text):
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
        matches = list(PATTERN.finditer(event["body"]))
        if matches:
            category = CATEGORY_WORDS[matches[-1].group(1).lower()]
    return category
