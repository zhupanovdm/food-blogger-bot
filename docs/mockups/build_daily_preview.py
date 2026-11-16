"""Три эскиза дневного альбома на условных данных, без изменения сервиса/API."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
import numpy as np

OUT = Path(__file__).parent
BG, INK, MUTED, GRID = "#fafaf7", "#172b35", "#5a6870", "#dfe5e4"
BLUE, ORANGE, GREEN, REST = "#176f94", "#b16c32", "#548168", "#d4dfd9"
RED = "#b54646"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                     "axes.unicode_minus": False})
MEALS = [
    dict(time="08:20", category="Завтрак", kcal=480, protein=25, fat=16, carbs=59),
    dict(time="11:10", category="Перекус", kcal=170, protein=10, fat=6, carbs=19),
    dict(time="14:05", category="Обед", kcal=720, protein=45, fat=24, carbs=81),
    dict(time="17:00", category="Полдник", kcal=230, protein=15, fat=8, carbs=24.5),
    dict(time="20:10", category="Ужин", kcal=450, protein=35, fat=16, carbs=41.5),
]
GOAL = 2200
HISTORY = [1900, 2050, 1800, 2100, 2050]
TOTALS = {key: sum(m[key] for m in MEALS) for key in ("kcal", "protein", "fat", "carbs")}


def number(value):
    return f"{value:,.0f}".replace(",", " ")


def base(title):
    fig = plt.figure(figsize=(10, 6.4), dpi=160, facecolor=BG)
    fig.text(.08, .925, title, fontsize=23, weight="bold", color=INK)
    fig.text(.08, .875, "16 ноября 2026 · На 20:15 · Условные данные", fontsize=12, color=MUTED)
    return fig


def save(fig, name):
    fig.savefig(OUT / name, facecolor=BG)
    plt.close(fig)
    print(OUT / name)


def summary(consumed=None, filename="daily-summary-preview.png"):
    consumed = TOTALS["kcal"] if consumed is None else consumed
    over = consumed > GOAL
    denominator = consumed if over else GOAL
    values = [GOAL, consumed-GOAL] if over else [consumed, GOAL-consumed]
    colors = [BLUE, RED if over else REST]
    labels = ["В пределах цели", "Превышение"] if over else ["Сегодня", "Остаток"]
    assert all(value >= 0 for value in values) and sum(values) == denominator
    fig = base("Итог за день")
    ax = fig.add_axes([.06, .16, .48, .62], facecolor=BG)
    wedges, _ = ax.pie(values, colors=colors, startangle=110,
                      wedgeprops={"linewidth": 0}, normalize=True)
    for index, (wedge, value) in enumerate(zip(wedges, values)):
        angle = np.deg2rad((wedge.theta1 + wedge.theta2)/2)
        radius = .50 if index == 0 else (.79 if value/denominator < .1 else .65)
        ax.text(radius*np.cos(angle), radius*np.sin(angle), f"{number(value)}\nккал",
                ha="center", va="center", fontsize=15 if index == 0 else (12 if over else 10),
                color=BG if index == 0 or over else INK, linespacing=1.25)
        if not over:
            percent = f"{value/denominator*100:.1f}%".replace(".", ",")
            ax.text(1.23*np.cos(angle), 1.23*np.sin(angle), percent,
                    ha="center", va="center", fontsize=13, color=INK)
    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-1.4, 1.4)
    today_color = RED if over else GREEN
    fig.text(.65, .765, "Сегодня", fontsize=13, color=today_color)
    fig.text(.65, .695, number(consumed), fontsize=32, weight="bold", color=today_color)
    today_unit = "ккал"
    if over:
        goal_percent = f"{consumed/GOAL*100:.1f}%".replace(".", ",")
        today_unit += f" · {goal_percent} от цели"
    fig.text(.65, .65, today_unit, fontsize=12, color=today_color)
    goal_y = .525
    mean_y = .285
    fig.text(.65, goal_y, "Цель", fontsize=13, color=MUTED)
    fig.text(.65, goal_y-.07, number(GOAL), fontsize=32, weight="bold", color=INK)
    fig.text(.65, goal_y-.115, "ккал", fontsize=12, color=MUTED)
    fig.text(.65, mean_y, "Среднее 09–15.11", fontsize=13, color=MUTED)
    fig.text(.65, mean_y-.07, number(sum(HISTORY)/len(HISTORY)), fontsize=32, weight="bold", color=INK)
    fig.text(.65, mean_y-.115, "ккал · записи 5/7", fontsize=12, color=MUTED)
    fig.legend(handles=[Patch(facecolor=color, label=label) for color, label in zip(colors, labels)],
               loc="lower left", bbox_to_anchor=(.08, .07), ncols=2, frameon=True,
               facecolor=BG, edgecolor=GRID, fontsize=11, labelcolor=INK, borderpad=.8)
    save(fig, filename)


def axes(fig, unit, ymax, ticks):
    ax = fig.add_axes([.095, .16, .84, .62], facecolor=BG)
    ax.set_xlim(-.55, len(MEALS)-.45)
    ax.set_ylim(0, ymax)
    ax.set_xticks(np.arange(len(MEALS)), [m["time"]+"\n"+m["category"] for m in MEALS])
    ax.set_yticks(ticks)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: number(value)))
    ax.set_ylabel(unit+" · ≈ оценка", color=MUTED, labelpad=12)
    ax.tick_params(axis="both", length=0, pad=10, colors=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=.8)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return ax


def energy():
    fig = base("Калории по приёмам пищи")
    ax = axes(fig, "ккал", 1000, [0, 250, 500, 750, 1000])
    ax.bar(np.arange(len(MEALS)), [m["kcal"] for m in MEALS], width=.46, color=BLUE)
    for i, meal in enumerate(MEALS):
        percent = f"{meal['kcal']/GOAL*100:.1f}%".replace(".", ",")
        ax.text(i, meal["kcal"]+25, number(meal["kcal"]), ha="center", va="bottom", fontsize=12, color=INK)
        ax.text(i, meal["kcal"]-25, percent, ha="center", va="top", fontsize=12, color=BG)
    ax.legend(handles=[Patch(facecolor=BLUE, label="Доля от цели 2 200 ккал, %")], loc="upper right",
              frameon=True, facecolor=BG, edgecolor=GRID, fontsize=11, labelcolor=INK, borderpad=.8)
    save(fig, "daily-meals-preview.png")


def macros():
    fig = base("Белки • Жиры • Углеводы")
    ax = axes(fig, "г", 130, [0, 25, 50, 75, 100, 125])
    handles = []
    for offset, key, label, color in zip((-.23, 0, .23), ("protein", "fat", "carbs"),
                                        ("Белки", "Жиры", "Углеводы"), (BLUE, ORANGE, GREEN)):
        values = [m[key] for m in MEALS]
        ax.bar(np.arange(len(MEALS))+offset, values, width=.20, color=color)
        for i, value in enumerate(values):
            ax.text(i+offset, value+2, f"{value:g}".replace(".", ","), ha="center", va="bottom", fontsize=10, color=INK)
        handles.append(Patch(facecolor=color, label=f"{label} · {TOTALS[key]:g} г"))
    ax.legend(handles=handles, title="Итого за день", loc="upper right", ncols=3,
              frameon=True, facecolor=BG, edgecolor=GRID, framealpha=1,
              fontsize=10, title_fontsize=11, labelcolor=INK, borderpad=.8)
    save(fig, "daily-macros-preview.png")


def main():
    assert TOTALS == dict(kcal=2050, protein=130, fat=70, carbs=225)
    assert all(abs(m["kcal"] - (m["protein"]*4 + m["fat"]*9 + m["carbs"]*4)) < .01 for m in MEALS)
    summary()
    summary(2700, "daily-summary-over-goal-preview.png")
    energy()
    macros()


if __name__ == "__main__":
    main()
