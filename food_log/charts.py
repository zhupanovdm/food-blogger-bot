from __future__ import annotations

from io import BytesIO

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
