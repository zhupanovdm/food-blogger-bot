"""Обновить эскизы реальным рендерером, на вымышленных данных, без API."""
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from food_log.charts import render_charts


def main():
    days = []
    calories = [2050, 2320, 2180, None, 2450, 2100, 1850]
    proteins = [125, 140, 130, None, 145, 135, 115]
    fats = [70, 80, 70, None, 90, 80, 70]
    carbs = [230, 260, 257.5, None, 265, 210, 190]
    for i in range(7):
        days.append(dict(date=date(2026, 11, 9) + timedelta(days=i),
            totals=None if calories[i] is None else dict(kcal=calories[i],
                protein=proteins[i], fat=fats[i], carbs=carbs[i]),
            is_today=i == 6))
    for name, content in render_charts(days, 2200):
        (Path(__file__).parent / f"{name}-preview.png").write_bytes(content)


if __name__ == "__main__":
    main()
