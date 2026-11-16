import unittest

import numpy as np
from datetime import date, timedelta
from unittest.mock import patch

import food_log.charts as charts
from food_log.charts import render_charts, render_daily_charts


class ChartTests(unittest.TestCase):
    def test_scale_keeps_tick_count_readable_for_extreme_values(self):
        from food_log.charts import _scale
        maximum, ticks = _scale([100000], 3000)
        self.assertGreater(maximum, 100000)
        self.assertLessEqual(len(ticks), 7)

    def days(self):
        start = date(2026, 11, 9)
        result = []
        for i in range(7):
            result.append({
                "date": start + timedelta(days=i),
                "totals": None if i == 3 else {"kcal": 2000 + i * 50, "protein": 120, "fat": 70, "carbs": 220},
                "gl": None if i == 3 else 90 + i,
                "gl_incomplete": i in (1, 6),
                "meal_gl": {} if i == 3 else {"Завтрак": 20, "Обед": 40, "Ужин": 30},
                "is_today": i == 6,
            })
        return result

    def test_renders_three_nonempty_pngs(self):
        rendered = render_charts(self.days(), 2200)
        self.assertEqual([name for name, _ in rendered], ["calories", "macros", "glycemic-load"])
        for _, content in rendered:
            self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(content), 10_000)

    def test_goal_is_optional(self):
        self.assertEqual(len(render_charts(self.days(), None)), 3)

    def test_scales_to_large_values(self):
        days = self.days()
        days[0]["totals"]["kcal"] = 8000
        days[1]["totals"]["carbs"] = 600
        days[2]["gl"] = 400
        rendered = render_charts(days, 6000)
        self.assertEqual(len(rendered), 3)
        for _, content in rendered:
            self.assertGreater(len(content), 10_000)

    def test_gl_without_estimate_is_distinguished_from_missing_day(self):
        days = self.days()
        days[0]["totals"] = {"kcal": 2000, "protein": 120, "fat": 70, "carbs": 220}
        days[0]["gl"] = None
        days[0]["meal_gl"] = {}
        with patch.object(charts, "_png", side_effect=lambda fig: fig) as capture:
            fig = charts._glycemic_load(days)
        texts = [text.get_text() for text in fig.axes[0].texts]
        self.assertIn("нет\nоценки", texts)
        self.assertNotIn("нет\nзаписей", texts[:1])
        fig.clear()

    def test_missing_day_keeps_nan_line_and_no_zero_value(self):
        days = self.days()
        captured = []
        with patch.object(charts, "_png", side_effect=lambda fig: captured.append(fig) or b"png"):
            charts._calories(days, 2200)
        line = captured[0].axes[0].lines[1] if len(captured[0].axes[0].lines) > 1 else captured[0].axes[0].lines[0]
        self.assertTrue(any(np.isnan(value) for value in line.get_ydata()))
        captured[0].clear()

    def test_rejects_more_than_seven_days(self):
        with self.assertRaises(ValueError):
            render_charts(self.days() + self.days()[:1], 2200)

    def test_missing_day_is_not_zero(self):
        days = self.days()
        days[3]["meal_gl"] = {}
        _, content = render_charts(days, 2200)[0]
        self.assertNotEqual(content, b"")

    def daily(self):
        return {
            "date": date(2026, 11, 16),
            "timezone": "Europe/Moscow",
            "meals": [
                {"occurred_at": "2026-11-16T16:00:00+00:00", "meal": "Обед", "totals": {"kcal": 700, "protein": 40, "fat": 20, "carbs": 80}},
                {"occurred_at": "2026-11-16T05:20:00+00:00", "meal": "Завтрак", "totals": {"kcal": 500, "protein": 25, "fat": 15, "carbs": 60}},
            ],
            "totals": {"kcal": 1200, "protein": 65, "fat": 35, "carbs": 140},
        }

    def test_daily_renders_approved_three_images(self):
        rendered = render_daily_charts(self.daily(), [], 2200)
        self.assertEqual([name for name, _ in rendered], ["summary", "meals", "macros"])
        self.assertTrue(all(data.startswith(b"\x89PNG\r\n\x1a\n") for _, data in rendered))

    def test_daily_summary_handles_over_goal_and_no_goal(self):
        day = self.daily()
        day["totals"]["kcal"] = 2700
        self.assertEqual(len(render_daily_charts(day, [], 2200)), 3)
        self.assertEqual(len(render_daily_charts(day, [], None)), 3)

    def test_daily_empty_meals_does_not_invent_values(self):
        day = self.daily()
        day["meals"] = []
        day["totals"] = None
        rendered = render_daily_charts(day, [], 2200)
        self.assertEqual(len(rendered), 3)

    def test_daily_summary_has_period_and_empty_history_coverage(self):
        with patch.object(charts, "_daily_png", side_effect=lambda fig: fig) as capture:
            fig = charts._daily_summary(self.daily(), [], 2200)
        texts = [text.get_text() for text in fig.texts]
        self.assertIn("Среднее за 7 дней", texts)
        self.assertIn("нет записей · 0/7", texts)
        fig.clear()

    def test_daily_over_goal_has_only_goal_percentage(self):
        day = self.daily()
        day["totals"]["kcal"] = 2700
        with patch.object(charts, "_daily_png", side_effect=lambda fig: fig):
            fig = charts._daily_summary(day, [], 2200)
        texts = [text.get_text() for text in fig.texts]
        self.assertIn("ккал · 122,7% от цели", texts)
        self.assertFalse(any(text.get_text().endswith("%") for text in fig.axes[0].texts))
        fig.clear()

    def test_daily_today_color_tracks_goal_boundary(self):
        for kcal, expected in ((2200, charts.GREEN), (2201, charts.RED)):
            day = self.daily()
            day["totals"]["kcal"] = kcal
            with patch.object(charts, "_daily_png", side_effect=lambda fig: fig):
                fig = charts._daily_summary(day, [], 2200)
            today = next(text for text in fig.texts if text.get_text() == "Сегодня")
            self.assertEqual(today.get_color(), expected)
            fig.clear()

    def test_daily_macros_empty_has_no_zero_legend(self):
        day = self.daily()
        day["meals"] = []
        day["totals"] = None
        with patch.object(charts, "_daily_png", side_effect=lambda fig: fig):
            fig = charts._daily_macros(day)
        self.assertNotIn("0 г", " ".join(text.get_text() for text in fig.texts))
        self.assertIn("нет записей", [text.get_text() for text in fig.axes[0].texts])
        fig.clear()

    def test_daily_summary_empty_and_zero_are_distinguished(self):
        for totals, expected in ((None, "нет записей"), ({"kcal": 0}, "2 200\nккал")):
            day = self.daily()
            day["totals"] = totals
            with patch.object(charts, "_daily_png", side_effect=lambda fig: fig):
                fig = charts._daily_summary(day, [], 2200)
            self.assertIn(expected, [text.get_text() for text in fig.axes[0].texts])
            charts.plt.close(fig)

    def test_daily_average_excludes_missing_days_and_labels_period(self):
        history = [{"date": date(2026, 11, 9) + timedelta(days=i),
                    "totals": {"kcal": 1000 if i == 0 else 2000} if i < 2 else None}
                   for i in range(7)]
        with patch.object(charts, "_daily_png", side_effect=lambda fig: fig):
            fig = charts._daily_summary(self.daily(), history, 2200)
        texts = [text.get_text() for text in fig.texts]
        self.assertIn("1 500", texts)
        self.assertIn("Среднее 09.11–15.11", texts)
        self.assertIn("ккал · записи 2/7", texts)
        charts.plt.close(fig)

    def test_daily_meals_sort_and_use_local_time(self):
        with patch.object(charts, "_daily_png", side_effect=lambda fig: fig):
            fig = charts._daily_meals(self.daily(), 2200)
        labels = [text.get_text() for text in fig.axes[0].get_xticklabels()]
        self.assertEqual(labels, ["08:20\nЗавтрак", "19:00\nОбед"])
        self.assertEqual([bar.get_height() for bar in fig.axes[0].patches], [500, 700])
        charts.plt.close(fig)

    def test_daily_album_canvas_is_identical_with_many_meals(self):
        import struct
        day = self.daily()
        day["meals"] = day["meals"] * 5
        sizes = [struct.unpack(">II", image[16:24]) for _, image in render_daily_charts(day, [], 2200)]
        self.assertEqual(len(set(sizes)), 1)

    def test_tiny_summary_sectors_use_callout_to_keep_label_readable(self):
        for kcal in (1, 2199, 2201):
            day = self.daily()
            day["totals"]["kcal"] = kcal
            with patch.object(charts, "_daily_png", side_effect=lambda fig: fig):
                fig = charts._daily_summary(day, [], 2200)
            callouts = [text for text in fig.axes[0].texts if getattr(text, "arrow_patch", None)]
            self.assertEqual(len(callouts), 1)
            charts.plt.close(fig)


if __name__ == "__main__":
    unittest.main()
