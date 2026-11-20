import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from food_log.nutrition import Assessment
from food_log.store import Store


def photo(mid=10, album=None, caption="300 г, съел половину", stamp=1794733200):
    msg = dict(message_id=mid, date=stamp, chat={"id": -100},
               **{"from": {"id": 7}}, photo=[{"file_id": f"file{mid}"}], caption=caption)
    if album:
        msg["media_group_id"] = album
    return msg


def result(kcal=195):
    return Assessment.model_validate(dict(status="ok", explanation="Оценка", question="",
        items=[dict(name="Рис", portion_grams=150, eaten_fraction=1,
                    kcal=kcal, protein=4.5, fat=1.5, carbs=42)]))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "food.sqlite3"
        self.db = Store(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_datetime_migration_preserves_old_records_and_is_repeatable(self):
        meal = self.db.add_photo(photo(caption="вчера ужин"), now=0)
        self.db.add_note(meal, 20, "вчера ужин", now=photo()["date"]+10)
        self.db.finish(meal, result(), "text")
        # Имитируем схему v1.1.0 без новых колонок времени.
        with self.db.conn:
            self.db.conn.execute("ALTER TABLE meals DROP COLUMN original_at")
            self.db.conn.execute("ALTER TABLE photos DROP COLUMN sent_at")
            self.db.conn.execute("ALTER TABLE notes DROP COLUMN sent_at")
        previous = self.db.conn.execute("SELECT result FROM meals").fetchone()[0]
        for _ in range(2):
            self.db.close()
            self.db = Store(self.path)
            row = self.db.conn.execute("SELECT * FROM meals").fetchone()
            self.assertEqual(row["eaten_at"], photo()["date"])
            self.assertEqual(row["original_at"], photo()["date"])
            self.assertEqual(row["result"], previous)
            evidence = self.db.evidence(meal)
            self.assertEqual([e["sent_at"] for e in evidence], [photo()["date"], photo()["date"]+10])

    def test_explicit_note_sent_time_survives_edits_and_restart(self):
        meal = self.db.add_photo(photo(), now=0)
        sent = photo()["date"]+10
        self.db.add_note(meal, 20, "вчера ужин", now=sent, sent_at=sent, version=sent)
        self.db.add_note(meal, 20, "вчера обед", now=sent+86400, sent_at=sent,
                         version=sent+86400, edited=True)
        self.db.close()
        self.db = Store(self.path)
        event = self.db.evidence(meal)[-1]
        self.assertEqual(event["sent_at"], sent)
        self.assertEqual(event["version"], sent+86400)

    def test_duplicate_photo_not_counted_twice(self):
        a = self.db.add_photo(photo(), now=0)
        b = self.db.add_photo(photo(), now=1)
        self.assertEqual(a, b)
        self.assertEqual(len(self.db.photos(a)), 1)

    def test_daily_meals_preserve_chronology_categories_and_local_midnight(self):
        now = datetime(2026, 11, 16, 22, tzinfo=timezone.utc)
        stamps = [int(datetime(2026, 11, 16, hour, tzinfo=timezone.utc).timestamp())
                  for hour in (23, 21, 20)]
        for index, stamp in enumerate(stamps):
            meal = self.db.add_photo(photo(mid=50+index, stamp=stamp), now=0)
            assessment = result(100+index)
            assessment.category = "Перекус"
            self.db.finish(meal, assessment, "text")
        # Correction keeps the original source time and previous assessment.
        self.db.add_note(2, 100, "съел половину", now=10)
        days = self.db.daily(now, 8)
        today = days[-1]
        self.assertEqual(today["timezone"], "Europe/Moscow")
        self.assertEqual([m["totals"]["kcal"] for m in today["meals"]], [101, 100])
        self.assertEqual([m["meal"] for m in today["meals"]], ["Перекус", "Перекус"])
        self.assertEqual(today["pending"], 1)
        self.assertEqual(today["totals"]["kcal"], 201)
        self.assertEqual(days[-2]["totals"]["kcal"], 102)
        self.assertEqual(len(days[:-1]), 7)

    def test_album_keeps_all_captions_and_one_meal(self):
        a = self.db.add_photo(photo(album="a"), now=0)
        b = self.db.add_photo(photo(mid=11, album="a", caption="без масла"), now=1)
        self.assertEqual(a, b)
        self.assertEqual([p["caption"] for p in self.db.photos(a)],
                         ["300 г, съел половину", "без масла"])
        self.assertIsNone(self.db.next_meal(now=2))
        self.assertIsNone(self.db.next_meal(now=4))
        self.assertEqual(self.db.next_meal(now=10)["id"], a)

    def test_album_waits_for_late_photo_and_note_cannot_bypass_wait(self):
        meal = self.db.add_photo(photo(album="late"), now=0)
        self.assertIsNone(self.db.next_meal(now=3))
        self.db.add_photo(photo(mid=11, album="late"), now=5)
        self.db.add_note(meal, 20, "это один обед", now=6)
        self.assertIsNone(self.db.next_meal(now=10))
        self.assertEqual(len(self.db.photos(self.db.next_meal(now=14)["id"])), 2)

    def test_pending_and_cursor_survive_restart(self):
        self.db.save_updates([{"update_id": 42, "message": photo()}])
        self.db.close()
        self.db = Store(self.path)
        self.assertEqual(self.db.offset(), 43)
        self.assertEqual(self.db.pending_updates()[0]["update_id"], 42)

    def test_correction_replaces_totals_and_duplicate_note_is_ignored(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        self.db.add_note(meal, 20, "съел всё", now=5)
        self.db.add_note(meal, 20, "съел всё", now=5)
        self.assertEqual(self.db.notes(meal), ["съел всё"])
        self.db.finish(meal, result(390), "corrected")
        report = self.db.report(datetime.fromtimestamp(photo()["date"], timezone.utc), 1)
        self.assertIn("390 ккал", report)
        self.assertNotIn("585", report)

    def test_moscow_midnight_and_missing_days(self):
        stamp = int(datetime(2026, 11, 14, 21, 1, tzinfo=timezone.utc).timestamp())
        meal = self.db.add_photo(photo(stamp=stamp), now=0)
        self.db.finish(meal, result(), "text")
        text = self.db.report(datetime(2026, 11, 15, 1, tzinfo=timezone.utc), 7)
        self.assertIn("15.11: 195 ккал", text)
        self.assertIn("14.11: нет записей", text)
        self.assertIn("за дни с записями (1): 195", text)

    def test_model_failure_keeps_previous_result_and_has_bounded_retry(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        self.db.add_note(meal, 20, "новый состав", now=5)
        for _ in range(3):
            self.db.fail(meal, now=10)
        self.assertIsNone(self.db.next_meal(now=1000))
        text = self.db.report(datetime.fromtimestamp(photo()["date"], timezone.utc), 1)
        self.assertIn("195 ккал", text)
        self.assertIn("ошиб", text.lower())

    def test_clarification_is_excluded(self):
        meal = self.db.add_photo(photo(), now=0)
        pending = Assessment(status="clarify", items=[], explanation="", question="Вес всей порции?")
        self.db.finish(meal, pending, "question")
        self.assertIsNone(self.db.next_meal(now=1000))
        text = self.db.report(datetime.fromtimestamp(photo()["date"], timezone.utc), 1)
        self.assertIn("нет записей", text)
        self.assertIn("уточнен", text)

    def test_daily_chart_data_preserves_missing_and_totals(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        days = self.db.daily(datetime.fromtimestamp(photo()["date"], timezone.utc), 7)
        self.assertEqual(len(days), 7)
        self.assertIsNone(days[-2]["totals"])
        self.assertEqual(days[-1]["totals"]["kcal"], 195)
        self.assertNotIn("gl", days[-1])
        self.assertNotIn("gl_incomplete", days[-1])

    def test_goal_persists_after_reopening(self):
        self.db.set_goal(2200)
        self.db.close()
        self.db = Store(self.path)
        self.assertEqual(self.db.goal(), 2200)

    def test_pending_album_survives_restart_with_image_order(self):
        with self.db.conn:
            self.db.queue_album(-100, 10, "Отчёт за 09.11–15.11", [b"calories", b"macros", b"daily-macros"])
        self.db.close()
        self.db = Store(self.path)
        entry = self.db.outgoing()[0]
        self.assertEqual(entry["images"], [b"calories", b"macros", b"daily-macros"])
        self.assertEqual(entry["body"], "Отчёт за 09.11–15.11")

    def test_caption_edit_is_newer_than_old_correction_and_duplicate_does_not_undo_it(self):
        from food_log.meal_time import meal_category
        original = photo(caption="Завтрак")
        meal = self.db.add_photo(original, now=0)
        self.db.add_note(meal, 20, "Обед", now=1, version=original["date"] + 10)
        edited = dict(original, caption="Ужин", edit_date=original["date"] + 20)
        self.db.add_photo(edited, now=2, edited=True)
        self.db.add_photo(original, now=3)
        self.assertEqual(self.db.photos(meal)[0]["caption"], "Ужин")
        self.assertEqual(meal_category(original["date"], "Europe/Moscow", self.db.evidence(meal)), "Ужин")

    def test_plain_text_cannot_attach_to_a_future_or_old_meal(self):
        msg = photo()
        meal = self.db.add_photo(msg, now=0)
        self.assertIsNone(self.db.latest_meal(-100, msg["date"] - 1))
        self.assertIsNone(self.db.latest_meal(-100, msg["date"] + 86401))
        self.assertEqual(self.db.latest_meal(-100, msg["date"] + 1), meal)

    def test_album_caption_edit_without_group_id_uses_event_order_and_same_meal(self):
        from food_log.meal_time import meal_category
        original = photo(album="album", caption="Завтрак")
        meal = self.db.add_photo(original, now=0, sequence=1)
        stamp = original["date"] + 10
        self.db.add_note(meal, 20, "Обед", now=1, version=stamp, sequence=2)
        edited = dict(original, caption="Ужин", edit_date=stamp)
        del edited["media_group_id"]
        self.assertEqual(self.db.add_photo(edited, now=2, edited=True, sequence=3), meal)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 1)
        self.assertEqual(meal_category(original["date"], "Europe/Moscow", self.db.evidence(meal)), "Ужин")
