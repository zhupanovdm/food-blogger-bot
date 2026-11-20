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


class MealDateTimeTests(unittest.TestCase):
    def stamp(self, value):
        return int(datetime.fromisoformat(value + '+03:00').timestamp())

    def resolve(self, body, source='2026-11-20T08:15:05'):
        from food_log.meal_time import resolve_meal_time
        stamp = self.stamp(source)
        return resolve_meal_time(stamp, 'Europe/Moscow', [
            {'body': body, 'version': stamp, 'sent_at': stamp}])

    def test_real_yesterday_dinner_caption_and_replies(self):
        for text in ('Вчера ужин, булгур 2 жаренные котлеты', 'Ужин вчера', 'Поздний ужин вчера'):
            with self.subTest(text=text):
                resolved = self.resolve(text)
                self.assertEqual(resolved.eaten_at, self.stamp('2026-11-19T08:15:05'))
                self.assertEqual(resolved.category, 'Ужин')
                self.assertFalse(resolved.time_explicit)

    def test_initial_clock_changes_time_and_inferred_category(self):
        resolved = self.resolve('8:00 омлет с сосиской', source='2026-11-19T13:06:00')
        self.assertEqual(resolved.eaten_at, self.stamp('2026-11-19T08:00:00'))
        self.assertEqual(resolved.category, 'Завтрак')
        self.assertTrue(resolved.time_explicit)

    def test_explicit_dates_and_clock_formats(self):
        for text in ('19.11.2026 в 20:30 ужин', '2026-11-19 ужин в 20:30',
                     '19 ноября 2026 ужин в 20:30', '19.11 ужин в 20:30', '19.11 в 20:30 ужин'):
            with self.subTest(text=text):
                value = self.resolve(text)
                self.assertEqual(value.eaten_at, self.stamp('2026-11-19T20:30:00'))
                self.assertEqual(value.category, 'Ужин')
        self.assertEqual(self.resolve('позавчера в 8 вечера').eaten_at,
                         self.stamp('2026-11-18T20:00:00'))

    def test_fields_override_independently_and_relative_dates_do_not_drift(self):
        from food_log.meal_time import resolve_meal_time
        source = self.stamp('2026-11-20T08:15:05')
        evidence = [dict(body='Вчера ужин в 20:30', version=source, sent_at=source),
                    dict(body='в 21:10', version=source+30, sent_at=source+30),
                    dict(body='порция 200 г', version=source+60, sent_at=source+60)]
        value = resolve_meal_time(source, 'Europe/Moscow', evidence)
        self.assertEqual(value.eaten_at, self.stamp('2026-11-19T21:10:00'))
        self.assertEqual(value.category, 'Ужин')
        self.assertEqual(value, resolve_meal_time(source, 'Europe/Moscow', evidence))

    def test_relative_date_anchored_to_message_not_edit_version(self):
        from food_log.meal_time import resolve_meal_time
        source = self.stamp('2026-01-01T00:15:00')
        value = resolve_meal_time(source, 'Europe/Moscow', [
            dict(body='вчера ужин', sent_at=source, version=source+86400)])
        self.assertEqual(value.eaten_at, self.stamp('2025-12-31T00:15:00'))

    def test_invalid_date_or_time_is_rejected(self):
        from food_log.meal_time import MealTimeError
        for text in ('31.02.2026 ужин', 'вчера в 25:00', 'в 8:75', '20.13.2026'):
            with self.subTest(text=text), self.assertRaises(MealTimeError):
                self.resolve(text)

    def test_metadata_only_corrections_and_casual_chat(self):
        from food_log.meal_time import metadata_only
        for text in ('вчера ужин', 'поздний ужин вчера', 'в 20:30', 'дата 19.11.2026', 'это завтрак'):
            self.assertTrue(metadata_only(text), text)
            self.assertTrue(is_food_correction(text), text)
        for text in ('после обеда созвонимся', 'Котлеты куриные', 'вчера ужин, рис 200 г'):
            self.assertFalse(metadata_only(text), text)

    def test_decimal_amounts_are_not_dates(self):
        for text in ('молоко 0.25 л', 'каша 0.50 кг', 'сахар 1.50 г', 'рис 10.11 грамма'):
            with self.subTest(text=text):
                self.assertEqual(self.resolve(text).eaten_at, self.stamp('2026-11-20T08:15:05'))

    def test_short_dates_do_not_consume_arbitrary_food_quantities(self):
        for text in ('каша 1.50 стакана', 'йогурт 3.14 ложки', '1.50 стакана каши', 'каша 2.05 чашки'):
            with self.subTest(text=text):
                self.assertEqual(self.resolve(text).eaten_at, self.stamp('2026-11-20T08:15:05'))
        self.assertEqual(self.resolve('дата 19.11').eaten_at, self.stamp('2026-11-19T08:15:05'))

    def test_period_words_before_category(self):
        from food_log.meal_time import metadata_only
        for text, category in (('Вчера вечером ужин', 'Ужин'),
                               ('Сегодня утром завтрак', 'Завтрак'),
                               ('Сегодня днем обед', 'Обед')):
            with self.subTest(text=text):
                self.assertEqual(self.resolve(text).category, category)
                self.assertTrue(metadata_only(text))
                self.assertTrue(is_food_correction(text))
