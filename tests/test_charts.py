import unittest

import numpy as np
from datetime import date, timedelta
from unittest.mock import patch

import food_log.charts as charts
from food_log.charts import render_charts


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


if __name__ == "__main__":
    unittest.main()
