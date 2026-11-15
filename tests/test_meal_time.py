import unittest
from datetime import datetime, timezone

from food_log.meal_time import meal_category, is_food_correction


class MealTimeTests(unittest.TestCase):
    def test_generic_chat_prefixes_are_not_food_corrections(self):
        for text in ("Это надо обсудить", "Там уже всё готово", "После обеда созвонимся"):
            self.assertFalse(is_food_correction(text), text)
        for text in ("Это ужин", "Порция 200 г", "Съел половину", "Без сахара", "Уточнение: это гречка"):
            self.assertTrue(is_food_correction(text), text)

    def test_local_time_windows(self):
        for hour, expected in ((8, "Завтрак"), (13, "Обед"), (16, "Полдник"),
                               (20, "Ужин"), (2, "Перекус")):
            stamp = datetime(2026, 11, 15, hour, tzinfo=timezone.utc).timestamp() - 3*3600
            self.assertEqual(meal_category(stamp, "Europe/Moscow", []), expected)

    def test_latest_explicit_text_overrides_time_and_old_caption(self):
        self.assertEqual(meal_category(0, "Europe/Moscow", [
            {"body": "это завтрак", "version": 10},
            {"body": "не завтрак, а полдник", "version": 20}]), "Полдник")

    def test_edited_caption_can_override_an_older_note(self):
        self.assertEqual(meal_category(0, "Europe/Moscow", [
            {"body": "это ужин", "version": 30},
            {"body": "Обед, оцени сам", "version": 20}]), "Ужин")

    def test_same_second_caption_edit_uses_event_order(self):
        self.assertEqual(meal_category(0, "Europe/Moscow", [
            {"body": "Ужин", "version": 20, "sequence": 3},
            {"body": "Обед", "version": 20, "sequence": 2}]), "Ужин")

    def test_casual_mention_does_not_change_category(self):
        stamp = datetime(2026, 11, 15, 17, tzinfo=timezone.utc).timestamp()
        self.assertEqual(meal_category(stamp, "Europe/Moscow", [
            {"body": "После обеда созвонимся", "version": 1}]), "Ужин")
