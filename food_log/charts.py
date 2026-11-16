from __future__ import annotations

from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator


BG = "#fafaf7"
INK = "#172b35"
MUTED = "#5a6870"
GRID = "#dfe5e4"
BLUE = "#176f94"
ORANGE = "#b16c32"
GREEN = "#548168"
REST = "#d4dfd9"
RED = "#bd4949"
GL_COLORS = {
    "Завтрак": "#d3b89a",
    "Обед": "#b78555",
    "Ужин": "#805332",
    "Полдник": "#c19a66",
    "Перекус": "#9b6d43",
    "Без категории": "#9da7a5",
}


def _fmt(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _base(title: str, unit: str, days: list[dict], ymax: float, yticks: list[float]):
    fig = plt.figure(figsize=(10, 6.4), dpi=150, facecolor=BG)
    fig.text(0.08, 0.925, title, fontsize=23, weight="bold", color=INK)
    if days:
        fig.text(0.08, 0.874, f"{days[0]['date']:%d.%m}–{days[-1]['date']:%d.%m}", fontsize=12, color=MUTED)
    ax = fig.add_axes((0.095, 0.15, 0.84, 0.64), facecolor=BG)
    ax.set_xlim(-0.5, max(6.5, len(days) - 0.5))
    ax.set_ylim(0, ymax)
    labels = [f"{d['date']:%d.%m}\n{'Пн Вт Ср Чт Пт Сб Вс'.split()[d['date'].weekday()]}" for d in days]
    ax.set_xticks(range(len(days)), labels)
    for label, day in zip(ax.get_xticklabels(), days):
        label.set_color(RED if day["date"].weekday() >= 5 else MUTED)
    ax.set_yticks(yticks)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: _fmt(value)))
    ax.set_ylabel(f"{unit} · ≈ оценка", color=MUTED, labelpad=12)
    ax.tick_params(axis="both", length=0, pad=10)
    ax.tick_params(axis="y", colors=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return fig, ax


def _scale(values, minimum: float):
    finite = [float(v) for v in values if v is not None and np.isfinite(v)]
    top = max(finite, default=minimum)
    ymax = max(minimum, top * 1.5)
    ticks = list(MaxNLocator(nbins=5).tick_values(0, ymax))
    return float(ticks[-1]), ticks


def _legend(ax, handles):
    return ax.legend(handles=handles, loc="upper right", ncols=2, frameon=True,
                     facecolor=BG, edgecolor=GRID, framealpha=1, fontsize=10,
                     labelcolor=INK, borderpad=0.8, handlelength=2.2,
                     columnspacing=1.4)


def _png(fig) -> bytes:
    out = BytesIO()
    fig.savefig(out, format="png", facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return out.getvalue()


def _calories(days: list[dict], goal: float | None) -> bytes:
    values = [None if d.get("totals") is None else d["totals"].get("kcal") for d in days]
    ymax, ticks = _scale(values + [goal], 3000)
    fig, ax = _base("Калории · 7 дней", "ккал", days, ymax, ticks)
    x = np.arange(len(days))
    if goal is not None:
        ax.axhline(goal, color=MUTED, linewidth=1.5, linestyle=(0, (5, 4)))
    finite = np.array([np.nan if v is None else float(v) for v in values])
    ax.plot(x, finite, color=BLUE, linewidth=2.5, marker="o", markersize=7)
    for i, (value, day) in enumerate(zip(values, days)):
        if value is None:
            ax.text(i, 500, "нет\nзаписей", color=MUTED, ha="center", va="center", fontsize=10)
            continue
        if day.get("is_today"):
            ax.plot(i, value, marker="o", markersize=9, markerfacecolor=BG,
                    markeredgecolor=BLUE, markeredgewidth=2)
        ax.annotate(_fmt(float(value)), (i, value), xytext=(0, 12 if value > 2400 else -23),
                    textcoords="offset points", ha="center", color=INK, fontsize=10)
    handles = [Line2D([], [], color=BLUE, marker="o", linewidth=2, label="Потребление")]
    if goal is not None:
        handles.append(Line2D([], [], color=MUTED, linestyle=(0, (5, 4)), label=f"Цель · {_fmt(goal)} ккал"))
    if any(d.get("is_today") for d in days):
        handles.append(Line2D([], [], color=BLUE, marker="o", markerfacecolor=BG,
                               linestyle="None", label="Сегодня"))
    _legend(ax, handles)
    return _png(fig)


def _macros(days: list[dict]) -> bytes:
    series = [("Белки", BLUE, "protein"), ("Жиры", ORANGE, "fat"), ("Углеводы", GREEN, "carbs")]
    values = [d["totals"].get(key) for d in days if d.get("totals") for _, _, key in series]
    ymax, ticks = _scale(values, 400)
    fig, ax = _base("Белки · Жиры · Углеводы", "г / день", days, ymax, ticks)
    offsets = (-0.23, 0, 0.23)
    x = np.arange(len(days))
    for (label, color, key), offset in zip(series, offsets):
        for i, day in enumerate(days):
            value = None if day.get("totals") is None else day["totals"].get(key)
            if value is None:
                continue
            bar = ax.bar(i + offset, value, width=0.2, color=color)
            if day.get("is_today"):
                bar[0].set_hatch("///")
                bar[0].set_edgecolor(BG)
                bar[0].set_linewidth(0)
            ax.text(i + offset, value + 7, f"{value:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
    for i, day in enumerate(days):
        if day.get("totals") is None:
            ax.text(i, 70, "нет\nзаписей", ha="center", color=MUTED, fontsize=10)
    handles = [Patch(facecolor=color, label=label) for label, color, _ in series]
    if any(d.get("is_today") for d in days):
        handles.append(Patch(facecolor=MUTED, hatch="///", edgecolor=BG, linewidth=0, label="Сегодня"))
    _legend(ax, handles)
    return _png(fig)


def _glycemic_load(days: list[dict]) -> bytes:
    values = [d.get("gl") for d in days]
    ymax, ticks = _scale(values, 200)
    fig, ax = _base("Гликемическая нагрузка · 7 дней", "расчётная ГН, ед.", days, ymax, ticks)
    x = np.arange(len(days))
    categories = list(GL_COLORS)
    bottom = np.zeros(len(days))
    for category in categories:
        vals = np.array([float(d.get("meal_gl", {}).get(category, 0) or 0) for d in days])
        bars = ax.bar(x, vals, bottom=bottom, width=0.48, color=GL_COLORS[category], label=category)
        for i, day in enumerate(days):
            if day.get("gl_incomplete") or day.get("is_today"):
                bars[i].set_hatch("///")
                bars[i].set_edgecolor(BG)
                bars[i].set_linewidth(0)
        bottom += vals
    for i, (value, day) in enumerate(zip(bottom, days)):
        if day.get("gl") is None and not any(day.get("meal_gl", {}).values()):
            label = "нет\nоценки" if day.get("totals") is not None else "нет\nзаписей"
            ax.text(i, max(10, ymax * .15), label, ha="center", color=MUTED, fontsize=10)
        elif day.get("gl") is not None:
            suffix = " + ?" if day.get("gl_incomplete") else ""
            ax.text(i, value + 7, f"≈{value:.0f}{suffix}", ha="center", color=INK, fontsize=10)
    used = [category for category in categories if any(float(d.get("meal_gl", {}).get(category, 0) or 0) > 0 for d in days)]
    handles = [Patch(facecolor=GL_COLORS[category], label=category) for category in used]
    if any(d.get("gl_incomplete") for d in days):
        handles.append(Patch(facecolor=MUTED, hatch="///", edgecolor=BG, linewidth=0, label="Неполный итог"))
    if any(d.get("is_today") for d in days):
        handles.append(Patch(facecolor=MUTED, hatch="///", edgecolor=BG, linewidth=0, label="Сегодня"))
    _legend(ax, handles)
    return _png(fig)


def render_charts(days: list[dict], goal: float | None) -> list[tuple[str, bytes]]:
    """Render approved weekly charts. `days` must already contain at most seven days."""
    if len(days) > 7:
        raise ValueError("Ожидается не более 7 дней")
    return [("calories", _calories(days, goal)),
            ("macros", _macros(days)),
            ("glycemic-load", _glycemic_load(days))]


def _daily_png(fig) -> bytes:
    out = BytesIO()
    fig.savefig(out, format="png", facecolor=BG)
    plt.close(fig)
    return out.getvalue()


def _daily_base(title: str, day: dict, width: float | None = None):
    width = width or max(10, len(day.get("meals", [])) * 1.25)
    fig = plt.figure(figsize=(width, 6.4), dpi=150, facecolor=BG)
    fig.text(.08, .925, title, fontsize=23, weight="bold", color=INK)
    subtitle = f"{day['date']:%d.%m.%Y}"
    if day.get("as_of"):
        subtitle += f" · На {day['as_of']}"
    fig.text(.08, .875, subtitle, fontsize=12, color=MUTED)
    return fig


def _daily_summary(day: dict, history: list[dict], goal: float | None) -> bytes:
    consumed = (day.get("totals") or {}).get("kcal")
    over = goal is not None and consumed is not None and consumed > goal
    fig = _daily_base("Итог за день", day)
    ax = fig.add_axes((.06, .16, .48, .62), facecolor=BG)
    if consumed is None:
        ax.pie([1], colors=[GRID])
        ax.text(0, 0, "нет записей", ha="center", va="center", color=MUTED, fontsize=16)
    else:
        if goal is None:
            values, colors, labels = [consumed or 1], [BLUE], ["Сегодня"]
        elif over:
            values, colors, labels = [goal, consumed-goal], [BLUE, RED], ["В пределах цели", "Превышение"]
        else:
            values, colors, labels = [consumed, goal-consumed], [BLUE, REST], ["Сегодня", "Остаток"]
        wedges, _ = ax.pie(values, colors=colors, startangle=110,
                           wedgeprops={"linewidth": 0})
        denominator = consumed if over else goal
        for index, (wedge, value) in enumerate(zip(wedges, values)):
            if value <= 0:
                continue
            angle = np.deg2rad((wedge.theta1 + wedge.theta2) / 2)
            share = value / sum(values)
            radius = .50 if index == 0 else (.79 if share < .1 else .65)
            label_value = consumed if goal is None else value
            if share < .03:
                label = f"{_fmt(label_value)} ккал"
                if not over and goal is not None:
                    label += " · " + f"{value/goal*100:.1f}%".replace(".", ",")
                ax.annotate(label, xy=(.95*np.cos(angle), .95*np.sin(angle)),
                            xytext=(1.18*np.cos(angle), 1.24*np.sin(angle)),
                            ha="center", va="center", fontsize=11, color=INK,
                            arrowprops={"arrowstyle": "-", "color": MUTED})
                continue
            ax.text(radius*np.cos(angle), radius*np.sin(angle), f"{_fmt(label_value)}\nккал",
                    ha="center", va="center", color=BG if index == 0 or over else INK,
                    fontsize=15 if index == 0 else (12 if over else 10))
            if goal is not None and not over:
                percent = f"{value/denominator*100:.1f}%".replace(".", ",")
                ax.text(1.23*np.cos(angle), 1.23*np.sin(angle), percent,
                        ha="center", va="center", color=INK, fontsize=13)
        fig.legend(handles=[Patch(facecolor=c, label=l) for c, l in zip(colors, labels)],
                   loc="lower left", bbox_to_anchor=(.08, .07), ncols=2,
                   frameon=True, facecolor=BG, edgecolor=GRID, fontsize=11,
                   labelcolor=INK, borderpad=.8)
    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-1.4, 1.4)
    today_color = RED if over else GREEN
    fig.text(.65, .765, "Сегодня", fontsize=13, color=today_color)
    fig.text(.65, .695, _fmt(consumed) if consumed is not None else "нет записей",
             fontsize=32 if consumed is not None else 20, weight="bold", color=today_color)
    if consumed is not None:
        suffix = "ккал"
        if over:
            suffix += " · " + f"{consumed/goal*100:.1f}% от цели".replace(".", ",")
        fig.text(.65, .65, suffix, fontsize=12, color=today_color)
    fig.text(.65, .525, "Цель", fontsize=13, color=MUTED)
    fig.text(.65, .455, _fmt(goal) if goal is not None else "не задана",
             fontsize=32 if goal is not None else 20, weight="bold", color=INK)
    if goal is not None:
        fig.text(.65, .41, "ккал", fontsize=12, color=MUTED)
    previous = [d["totals"]["kcal"] for d in history if d.get("totals") is not None]
    period = (f"Среднее {history[0]['date']:%d.%m}–{history[-1]['date']:%d.%m}"
              if history else "Среднее за 7 дней")
    fig.text(.65, .285, period, fontsize=13, color=MUTED)
    fig.text(.65, .215, _fmt(sum(previous)/len(previous)) if previous else "нет записей",
             fontsize=32 if previous else 20, weight="bold", color=INK if previous else MUTED)
    fig.text(.65, .17, f"ккал · записи {len(previous)}/7" if previous else "нет записей · 0/7",
             fontsize=12, color=MUTED)
    return _daily_png(fig)


def _local_time(value, timezone):
    return datetime.fromisoformat(value).astimezone(ZoneInfo(timezone)).strftime("%H:%M")


def _daily_axes(title, unit, day, values, minimum):
    meals = sorted(day.get("meals") or [], key=lambda item: item["occurred_at"])
    fig = _daily_base(title, day, width=max(10, len(meals) * 1.25))
    ax = fig.add_axes((.095, .16, .84, .62), facecolor=BG)
    ymax, ticks = _scale(values, minimum)
    ax.set_ylim(0, ymax)
    ax.set_xlim(-.6, max(.6, len(meals)-.4))
    ax.set_yticks(ticks)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: _fmt(value)))
    ax.set_ylabel(f"{unit} · ≈ оценка", color=MUTED, labelpad=12)
    ax.set_xticks(range(len(meals)), [
        f"{_local_time(m['occurred_at'], day['timezone'])}\n{m['meal']}" for m in meals])
    ax.tick_params(axis="both", length=0, colors=MUTED, pad=10)
    ax.grid(axis="y", color=GRID, linewidth=.8)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if not meals:
        ax.text(0, ymax*.45, "нет записей", ha="center", va="center", color=MUTED, fontsize=13)
    return fig, ax, meals, ymax


def _daily_meals(day: dict, goal: float | None) -> bytes:
    fig, ax, meals, ymax = _daily_axes("Калории по приёмам пищи", "ккал", day,
        [m["totals"]["kcal"] for m in day.get("meals", [])], 500)
    values = [m["totals"]["kcal"] for m in meals]
    bars = ax.bar(range(len(meals)), values, color=BLUE, width=.58)
    for i, (bar, kcal) in enumerate(zip(bars, values)):
        ax.text(i, kcal+ymax*.025, _fmt(kcal), ha="center", va="bottom", color=INK, fontsize=11)
        if goal is not None and kcal > 0:
            percent = f"{kcal/goal*100:.1f}%".replace(".", ",")
            ax.text(i, kcal*.5, percent, ha="center", va="center", color=BG, fontsize=10)
    return _daily_png(fig)


def _daily_macros(day: dict) -> bytes:
    series = [("Белки", BLUE, "protein"), ("Жиры", ORANGE, "fat"), ("Углеводы", GREEN, "carbs")]
    fig, ax, meals, ymax = _daily_axes("Белки · Жиры · Углеводы", "г", day,
        [m["totals"][key] for m in day.get("meals", []) for _, _, key in series], 100)
    x = np.arange(len(meals))
    for offset, (label, color, key) in zip((-.23, 0, .23), series):
        values = [m["totals"][key] for m in meals]
        ax.bar(x+offset, values, width=.20, color=color)
        for i, value in enumerate(values):
            ax.text(i+offset, value+ymax*.02, _fmt(value),
                    ha="center", va="bottom", fontsize=9, color=INK)
    if day.get("totals") is not None:
        handles = [Patch(facecolor=color, label=f"{name} · {_fmt(day['totals'][key])} г")
                   for name, color, key in series]
        _legend(ax, handles)
    return _daily_png(fig)


def render_daily_charts(day: dict, history: list[dict], goal: float | None) -> list[tuple[str, bytes]]:
    """Three daily images; history contains the seven preceding calendar dates."""
    return [("summary", _daily_summary(day, history, goal)),
            ("meals", _daily_meals(day, goal)),
            ("macros", _daily_macros(day))]
