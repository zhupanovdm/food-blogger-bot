import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from food_log.service import Config, Service, OpenAIAnalyzer, TelegramAPI
from food_log.store import Store
from test_store import photo, result


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Store(Path(self.tmp.name) / "db.sqlite3")
        self.config = Config("telegram", "openai", "gpt-4.1-mini", -100, 7)
        self.tg = Mock()
        self.tg.download.return_value = b"image bytes"
        self.ai = Mock()
        self.ai.analyze.return_value = result()
        self.service = Service(self.config, self.db, self.tg, self.ai)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def food_message(self, text="/food Обед: гречка 200 г и курица", mid=80):
        return {"chat": {"id": -100}, "from": {"id": 7}, "message_id": mid,
                "date": photo()["date"], "text": text}

    def ingest_message(self, msg, uid=100, edited=False):
        self.service.receive([{"update_id": uid,
                               "edited_message" if edited else "message": msg}])
        self.service.ingest(now=msg.get("edit_date", msg["date"]) + 1)

    def test_food_creates_separate_meal_without_images_and_keeps_time(self):
        self.db.add_photo(photo(), now=0)
        msg = self.food_message()
        msg["reply_to_message"] = {"message_id": photo()["message_id"]}
        self.ingest_message(msg)
        self.service.analyze_one(now=msg["date"] + 2)  # предыдущее фото
        self.service.analyze_one(now=msg["date"] + 3)
        meal = self.db.conn.execute("SELECT * FROM meals WHERE source=80").fetchone()
        self.assertIsNotNone(meal)
        self.assertEqual(meal["eaten_at"], msg["date"])
        args = self.ai.analyze.call_args.kwargs
        self.assertEqual(args["images"], [])
        self.assertEqual(args["notes"], ["Обед: гречка 200 г и курица"])
        self.assertEqual(args["context"]["category"], "Обед")
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 2)

    def test_food_duplicates_after_restart_do_not_reanalyze(self):
        msg = self.food_message()
        self.ingest_message(msg)
        self.assertTrue(self.service.analyze_one(now=msg["date"] + 2))
        self.db.close()
        self.db = Store(Path(self.tmp.name) / "db.sqlite3")
        self.service.db = self.db
        self.ingest_message(msg)
        self.ingest_message(msg, uid=101)
        self.assertFalse(self.service.analyze_one(now=msg["date"] + 3))
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 1)
        self.assertEqual(self.ai.analyze.call_count, 1)

    def test_food_edit_and_reply_update_same_meal(self):
        msg = self.food_message()
        self.ingest_message(msg)
        self.assertTrue(self.service.analyze_one(now=msg["date"] + 2))
        for uid, text in ((101, "/food Ужин: гречка 100 г"), (102, "Ужин: гречка 150 г")):
            self.ingest_message(dict(msg, text=text, edit_date=msg["date"] + uid), uid, edited=True)
            self.assertTrue(self.service.analyze_one(now=msg["date"] + uid + 2))
        reply = self.food_message("съел половину", mid=81)
        reply["reply_to_message"] = {"message_id": 80}
        reply["date"] += 150
        self.ingest_message(reply, uid=103)
        self.assertTrue(self.service.analyze_one(now=msg["date"] + 200))
        args = self.ai.analyze.call_args.kwargs
        self.assertEqual(args["notes"], ["Ужин: гречка 150 г", "съел половину"])
        self.assertEqual(args["context"]["category"], "Ужин")
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 1)
        self.assertEqual(self.db.conn.execute("SELECT eaten_at FROM meals").fetchone()[0], msg["date"])

    def test_empty_food_command_shows_usage_without_meal(self):
        self.ingest_message(self.food_message("/food   "))
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 0)
        self.assertIn("/food", self.db.outgoing()[0]["body"])

    def test_food_other_members_and_other_chats_are_ignored(self):
        for uid, msg in enumerate((dict(self.food_message(), **{"from": {"id": 8}}),
                                   dict(self.food_message(), chat={"id": -200})), 100):
            self.ingest_message(msg, uid)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 0)
        self.assertFalse(self.service.analyze_one(now=photo()["date"] + 200))

    def test_food_edit_failure_preserves_previous_assessment(self):
        msg = self.food_message("/food@my_food_blogger_bot Завтрак: каша")
        self.ingest_message(msg)
        self.assertTrue(self.service.analyze_one(now=msg["date"] + 2))
        previous = self.db.conn.execute("SELECT result FROM meals").fetchone()[0]
        self.ingest_message(dict(msg, text="/food каша 100 г", edit_date=msg["date"] + 10), 101, edited=True)
        self.ai.analyze.side_effect = RuntimeError("failure")
        with self.assertLogs("food_log.service", level="WARNING"):
            self.service.analyze_one(now=msg["date"] + 12)
        self.assertEqual(self.db.conn.execute("SELECT result FROM meals").fetchone()[0], previous)

    def test_two_image_album_survives_restart(self):
        with self.db.conn:
            self.db.queue_album(-100, 80, "Неделя", [b"calories", b"macros"])
        self.db.close()
        self.db = Store(Path(self.tmp.name) / "db.sqlite3")
        self.assertEqual(self.db.outgoing()[0]["images"], [b"calories", b"macros"])

    def test_stale_food_edit_does_not_undo_newer_description(self):
        msg = self.food_message()
        self.ingest_message(msg)
        self.ingest_message(dict(msg, text="/food Ужин: каша 100 г", edit_date=msg["date"] + 20), 102, edited=True)
        self.ingest_message(dict(msg, text="/food Обед: каша 300 г", edit_date=msg["date"] + 10), 101, edited=True)
        self.assertTrue(self.service.analyze_one(now=msg["date"] + 30))
        self.assertEqual(self.ai.analyze.call_args.kwargs["notes"], ["Ужин: каша 100 г"])
        self.assertEqual(self.ai.analyze.call_args.kwargs["context"]["category"], "Ужин")

    def test_edited_unrelated_message_cannot_create_food_command(self):
        self.ingest_message(dict(self.food_message(), edit_date=photo()["date"] + 10), edited=True)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 0)

    def test_openai_text_only_request_contains_description_without_image(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=result())
        ai = OpenAIAnalyzer("key", "gpt-4.1-mini", client=client)
        ai.analyze(images=[], captions=[], notes=["каша 200 г"])
        sent = client.responses.parse.call_args.kwargs
        content = sent["input"][0]["content"]
        self.assertEqual([item["type"] for item in content], ["input_text"])
        self.assertIn("каша 200 г", content[0]["text"])
        self.assertNotIn("gi_key", str(sent["text_format"].model_json_schema()))
        self.assertFalse(sent["store"])

    def test_caption_yesterday_moves_meal_into_previous_day(self):
        from datetime import datetime, timezone
        msg = photo(caption="Вчера ужин, булгур 2 жаренные котлеты")
        self.ingest_message(msg)
        self.assertTrue(self.service.analyze_one(now=msg["date"] + 5))
        meal = self.db.conn.execute("SELECT * FROM meals").fetchone()
        self.assertEqual(meal["eaten_at"], msg["date"] - 86400)
        self.assertEqual(meal["original_at"], msg["date"])
        self.assertEqual(self.ai.analyze.call_args.kwargs["context"]["category"], "Ужин")
        days = self.db.daily(datetime.fromtimestamp(msg["date"], timezone.utc), 2)
        self.assertIsNone(days[-1]["totals"])
        self.assertEqual(days[-2]["totals"]["kcal"], 195)
        self.assertIn("14.11.2026", self.db.outgoing()[0]["body"])

    def test_metadata_reply_preserves_nutrition_without_model_and_survives_duplicates(self):
        import json
        msg = self.food_message("/food рис 200 г")
        self.ingest_message(msg)
        self.service.analyze_one(now=msg["date"] + 5)
        previous = self.db.conn.execute("SELECT result FROM meals").fetchone()[0]
        self.db.link(-100, 1000, 1)
        reply = self.food_message("вчера ужин в 20:30", mid=81)
        reply["date"] += 60
        reply["reply_to_message"] = {"message_id": 1000}
        self.ingest_message(reply, uid=101)
        self.assertFalse(self.service.analyze_one(now=reply["date"] + 5))
        meal = self.db.conn.execute("SELECT * FROM meals").fetchone()
        from datetime import datetime
        from zoneinfo import ZoneInfo
        expected = datetime.fromtimestamp(msg["date"]-86400, ZoneInfo("Europe/Moscow")).replace(hour=20,minute=30,second=0)
        self.assertEqual(meal["eaten_at"], int(expected.timestamp()))
        self.assertEqual(json.loads(meal["result"])["items"], json.loads(previous)["items"])
        self.assertEqual(json.loads(meal["result"])["category"], "Ужин")
        self.assertEqual(self.ai.analyze.call_count, 1)
        self.assertIn("20:30", self.db.outgoing()[-1]["body"])
        queued = len(self.db.outgoing())
        self.ingest_message(reply, uid=102)
        self.assertEqual(len(self.db.outgoing()), queued)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 1)
        # Свободное уточнение после переноса на вчера всё ещё относится к этой записи.
        self.ingest_message(dict(reply, message_id=82, text="в 21:15", reply_to_message=None), uid=103)
        self.assertIn("21:15", self.db.outgoing()[-1]["body"])

    def test_bad_datetime_preserves_old_result_and_can_be_corrected(self):
        msg = self.food_message()
        self.ingest_message(msg)
        self.service.analyze_one(now=msg["date"]+5)
        previous = dict(self.db.conn.execute("SELECT * FROM meals").fetchone())
        reply = self.food_message("31.02.2026 в 25:00", mid=81)
        reply["date"] += 10
        reply["reply_to_message"] = {"message_id": 80}
        self.ingest_message(reply, uid=101)
        self.service.analyze_one(now=reply["date"]+5)
        failed = self.db.conn.execute("SELECT * FROM meals").fetchone()
        self.assertEqual(failed["eaten_at"], previous["eaten_at"])
        self.assertEqual(failed["result"], previous["result"])
        self.assertIn("Неверная", self.db.outgoing()[-1]["body"])
        reply.update(text="14.11.2026 в 20:30", edit_date=reply["date"]+30)
        self.ingest_message(reply, uid=102, edited=True)
        self.service.analyze_one(now=reply["date"]+40)
        self.assertEqual(self.db.conn.execute("SELECT state FROM meals").fetchone()[0], "ok")

    def test_edited_yesterday_caption_uses_original_date_and_can_remove_date(self):
        msg = photo(caption="вчера ужин в 20:30, рис")
        self.ingest_message(msg)
        self.service.analyze_one(now=msg["date"]+5)
        edited = dict(msg, caption="вчера ужин в 21:30, рис", edit_date=msg["date"]+86400)
        self.ingest_message(edited, uid=101, edited=True)
        self.service.analyze_one(now=edited["edit_date"]+5)
        expected = msg["date"]-86400
        self.assertEqual(self.db.conn.execute("SELECT eaten_at FROM meals").fetchone()[0]//86400,
                         expected//86400)
        self.ingest_message(dict(edited, caption="рис", edit_date=edited["edit_date"]+60), uid=102, edited=True)
        self.service.analyze_one(now=edited["edit_date"]+65)
        self.assertEqual(self.db.conn.execute("SELECT eaten_at FROM meals").fetchone()[0], msg["date"])

    def test_removing_nutritional_correction_requires_reanalysis(self):
        msg = self.food_message()
        self.ingest_message(msg)
        self.service.analyze_one(now=msg["date"]+5)
        reply = self.food_message("съел половину", mid=81)
        reply["reply_to_message"] = {"message_id": 80}
        reply["date"] += 10
        self.ingest_message(reply, uid=101)
        self.service.analyze_one(now=reply["date"]+5)
        calls = self.ai.analyze.call_count
        self.ingest_message(dict(reply, text="вчера ужин", edit_date=reply["date"]+10), uid=102, edited=True)
        self.assertTrue(self.service.analyze_one(now=reply["date"]+15))
        self.assertEqual(self.ai.analyze.call_count, calls+1)
        self.assertEqual(self.ai.analyze.call_args.kwargs["notes"],
                         ["Обед: гречка 200 г и курица", "вчера ужин"])

    def test_only_owner_photos_in_allowed_group(self):
        updates = [{"update_id": 1, "message": photo()}]
        other = photo(mid=11)
        other["from"]["id"] = 8
        updates.append({"update_id": 2, "message": other})
        outsider = photo(mid=12)
        outsider["chat"]["id"] = -200
        updates.append({"update_id": 3, "message": outsider})
        self.service.receive(updates)
        self.service.ingest(now=0)
        self.service.analyze_one(now=5)
        self.assertEqual(self.ai.analyze.call_count, 1)
        self.assertEqual(self.db.offset(), 4)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 1)

    def test_caption_and_full_correction_history_sent_with_original_photo(self):
        self.service.receive([{"update_id": 1, "message": photo()}])
        self.service.ingest(now=0)
        self.service.analyze_one(now=5)
        self.db.link(-100, 1000, 1)
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 20,
               "date": photo()["date"], "text": "съел всё, без масла",
               "reply_to_message": {"message_id": 1000}}
        self.service.receive([{"update_id": 2, "message": msg}])
        self.service.ingest(now=6)
        self.service.analyze_one(now=7)
        args = self.ai.analyze.call_args.kwargs
        self.assertEqual(args["captions"], ["300 г, съел половину"])
        self.assertEqual(args["notes"], ["съел всё, без масла"])
        self.assertEqual(args["images"], [b"image bytes"])

    def test_no_external_analysis_when_nothing_pending(self):
        self.assertFalse(self.service.analyze_one(now=1))
        self.ai.analyze.assert_not_called()

    def test_two_album_images_and_caption_are_sent_together(self):
        self.service.receive([{"update_id": 1, "message": photo(album="gallery")},
                              {"update_id": 2, "message": photo(mid=11, album="gallery", caption="") }])
        self.service.ingest(now=0)
        self.service.analyze_one(now=9)
        self.assertEqual(self.ai.analyze.call_count, 1)
        args = self.ai.analyze.call_args.kwargs
        self.assertEqual(len(args["images"]), 2)
        self.assertEqual(args["captions"], ["300 г, съел половину", ""])

    def test_plain_chat_text_corrects_latest_meal(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 20,
               "date": photo()["date"] + 10, "text": "Это полдник, оцени сам"}
        self.service.receive([{"update_id": 2, "message": msg}])
        self.service.ingest(now=10)
        self.service.analyze_one(now=11)
        self.assertEqual(self.ai.analyze.call_args.kwargs["notes"], [msg["text"]])
        self.assertEqual(self.ai.analyze.call_args.kwargs["context"]["category"], "Полдник")

    def test_unrelated_chat_text_does_not_reanalyze_food(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 20,
               "date": photo()["date"] + 10, "text": "После обеда созвонимся"}
        self.service.receive([{"update_id": 2, "message": msg}])
        self.service.ingest(now=10)
        self.assertFalse(self.service.analyze_one(now=11))
        self.assertEqual(self.db.notes(meal), [])

    def test_edited_caption_updates_same_meal_and_reanalyzes(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        edited = photo(caption="Это ужин, порция 200 г")
        edited["edit_date"] = edited["date"] + 100
        self.service.receive([{"update_id": 2, "edited_message": edited}])
        self.service.ingest(now=10)
        self.service.analyze_one(now=20)
        self.assertEqual(self.db.photos(meal)[0]["caption"], edited["caption"])
        self.assertEqual(self.ai.analyze.call_args.kwargs["context"]["category"], "Ужин")
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0], 1)

    def test_edited_reply_replaces_old_text(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 20,
               "date": photo()["date"] + 10, "text": "Обед",
               "reply_to_message": {"message_id": 10}}
        self.service.receive([{"update_id": 2, "message": msg}])
        self.service.ingest(now=10)
        msg = dict(msg, text="Полдник", edit_date=msg["date"] + 10)
        self.service.receive([{"update_id": 3, "edited_message": msg}])
        self.service.ingest(now=11)
        self.assertEqual(self.db.notes(meal), ["Полдник"])

    def test_reply_to_unknown_message_does_not_modify_latest_meal(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 20,
               "date": photo()["date"] + 10, "text": "Это ужин",
               "reply_to_message": {"message_id": 9999}}
        self.service.receive([{"update_id": 2, "message": msg}])
        self.service.ingest(now=10)
        self.assertEqual(self.db.notes(meal), [])

    def test_failure_retries_and_no_fake_zero(self):
        self.service.receive([{"update_id": 1, "message": photo()}])
        self.service.ingest(now=0)
        self.ai.analyze.side_effect = RuntimeError("secret must never be logged")
        with self.assertLogs("food_log.service", level="WARNING") as logs:
            self.service.analyze_one(now=5)
        self.assertNotIn("secret must never be logged", str(logs.output))
        self.assertIsNone(self.db.conn.execute("SELECT result FROM meals").fetchone()[0])
        self.assertIsNone(self.db.next_meal(now=6))
        self.assertIsNotNone(self.db.next_meal(now=40))

    def test_owner_can_set_goal(self):
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 30,
               "date": photo()["date"], "text": "/goal 2300"}
        self.service.receive([{"update_id": 3, "message": msg}])
        self.service.ingest(now=0)
        self.assertEqual(self.db.goal(), 2300)

    def test_goal_without_value_shows_current_goal_and_edit_hint(self):
        self.db.set_goal(2200)
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 31,
               "date": photo()["date"], "text": "/goal"}
        self.service.receive([{"update_id": 4, "message": msg}])
        self.service.ingest(now=0)
        response = self.db.outgoing()[0]["body"]
        self.assertIn("2200 ккал", response)
        self.assertIn("Чтобы изменить: /goal 2200", response)

    def test_other_members_cannot_change_goal_food_or_use_owner_commands(self):
        meal = self.db.add_photo(photo(), now=0)
        self.db.finish(meal, result(), "text")
        self.db.set_goal(2200)
        queued_before = len(self.db.outgoing())
        updates = []
        for index, text in enumerate(("/goal 2300", "/whoami", "съел всё"), 1):
            updates.append({"update_id": index, "message": {
                "chat": {"id": -100}, "from": {"id": 8}, "message_id": 100+index,
                "date": photo()["date"], "text": text,
                "reply_to_message": {"message_id": 10}}})
        other_photo = photo(mid=200)
        other_photo["from"]["id"] = 8
        updates.append({"update_id": 6, "message": other_photo})
        self.service.receive(updates)
        self.service.ingest(now=10)
        self.assertEqual(self.db.goal(), 2200)
        self.assertEqual(self.db.notes(meal), [])
        responses = self.db.outgoing()[queued_before:]
        self.assertEqual(len(responses), 1)
        self.assertIn("только владелец", responses[0]["body"])
        self.assertEqual(self.db.pending_updates(), [])
        self.ai.analyze.assert_not_called()

    def test_other_members_can_view_reports_goal_and_help(self):
        self.db.set_goal(2200)
        now = photo()["date"]
        for index, text in enumerate(("/today", "/week", "/goal", "/help"), 1):
            self.service.receive([{"update_id": index, "message": {
                "chat": {"id": -100}, "from": {"id": 8}, "message_id": 100+index,
                "date": now, "text": text}}])
        self.service.ingest(now=now)
        entries = self.db.outgoing()
        self.assertEqual([e["kind"] for e in entries], ["album", "album", "text", "text"])
        self.assertIn("2200", entries[2]["body"])
        self.assertEqual([len(e["images"]) for e in entries[:2]], [3, 2])
        self.ai.analyze.assert_not_called()

    def test_bot_other_chat_and_edited_commands_are_ignored(self):
        self.db.set_goal(2200)
        base = {"chat": {"id": -100}, "from": {"id": 8}, "message_id": 60,
                "date": photo()["date"], "text": "/goal 2300"}
        updates = [
            {"update_id": 1, "message": dict(base, **{"from": {"id": 7, "is_bot": True}})},
            {"update_id": 2, "message": dict(base, chat={"id": -200})},
            {"update_id": 3, "edited_message": dict(base, **{"from": {"id": 7}})},
        ]
        self.service.receive(updates)
        self.service.ingest(now=0)
        self.assertEqual(self.db.goal(), 2200)
        self.assertEqual(self.db.outgoing(), [])

    def test_today_queues_album_and_passes_previous_seven_days_excluding_today(self):
        now = photo()["date"]
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 70,
               "date": now, "text": "/today"}
        with patch("food_log.service.render_daily_charts", return_value=[
                ("summary", b"png1"), ("meals", b"png2"), ("macros", b"png3")]) as render:
            self.service.receive([{"update_id": 1, "message": msg}])
            self.service.ingest(now=now)
        day, history, goal = render.call_args.args
        self.assertEqual(str(day["date"]), "2026-11-15")
        self.assertEqual([str(d["date"]) for d in history],
                         [f"2026-11-{n:02d}" for n in range(8, 15)])
        entry = self.db.outgoing()[0]
        self.assertEqual(entry["kind"], "album")
        self.assertEqual(entry["images"], [b"png1", b"png2", b"png3"])
        self.assertIn("15.11.2026", entry["body"])

    def test_config_has_no_coach_access_setting(self):
        with self.assertRaises(TypeError):
            Config("telegram", "openai", "gpt-4.1-mini", -100, 7, coach_ids=(8,))

    def test_invalid_goal_does_not_replace_saved_value(self):
        self.db.set_goal(2200)
        for n, text in enumerate(("/goal nan", "/goal -1", "/goal 1e100"), 1):
            msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 40+n,
                   "date": photo()["date"], "text": text}
            self.service.receive([{"update_id": 10+n, "message": msg}])
            self.service.ingest(now=0)
        self.assertEqual(self.db.goal(), 2200)

    def test_week_queues_one_album_with_two_pngs_and_period(self):
        msg = {"chat": {"id": -100}, "from": {"id": 7}, "message_id": 50,
               "date": photo()["date"], "text": "/week"}
        self.service.receive([{"update_id": 20, "message": msg}])
        self.service.ingest(now=photo()["date"])
        entries = self.db.outgoing()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "album")
        self.assertEqual(len(entries[0]["images"]), 2)
        self.assertTrue(all(image.startswith(b"\x89PNG") for image in entries[0]["images"]))
        self.assertIn("Отчёт за 09.11.2026–15.11.2026", entries[0]["body"])

    def test_album_delivery_uses_one_request_and_retains_pending_on_failure(self):
        with self.db.conn:
            self.db.queue_album(-100, 50, "Отчёт за 09.11.2026–15.11.2026", [b"one", b"two", b"three"])
        self.tg.send_album.side_effect = RuntimeError("network failure")
        with self.assertRaises(RuntimeError):
            self.service.deliver()
        self.assertEqual(len(self.db.outgoing()), 1)
        self.assertEqual(self.db.outgoing()[0]["images"], [b"one", b"two", b"three"])
        self.tg.send_album.side_effect = None
        self.tg.send_album.return_value = [{"message_id": 51}, {"message_id": 52}, {"message_id": 53}]
        self.service.deliver()
        self.assertEqual(self.db.outgoing(), [])
        self.tg.send_photo.assert_not_called()
        self.tg.send_text.assert_not_called()
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM outbox_media").fetchone()[0], 0)

    def test_openai_receives_caption_notes_and_image_without_telegram_token(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=result())
        ai = OpenAIAnalyzer("key", "gpt-4.1-mini", client=client)
        value = ai.analyze(images=[b"fake jpeg"], captions=["300 г"], notes=["половина"])
        self.assertEqual(value.totals()["kcal"], 195)
        sent = client.responses.parse.call_args.kwargs
        self.assertIn("300 г", str(sent["input"]))
        self.assertIn("половина", str(sent["input"]))
        self.assertIn("data:image/jpeg;base64,", str(sent["input"]))
        self.assertEqual(sent["text_format"].__name__, "PhotoAssessment")
        self.assertNotIn("clarify", str(sent["text_format"].model_json_schema()["properties"]["status"]))
        self.assertFalse(sent["store"])

    def test_model_refusal_is_a_failure(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
        ai = OpenAIAnalyzer("key", "gpt-4.1-mini", client=client)
        with self.assertRaises(ValueError):
            ai.analyze(images=[b"fake jpeg"], captions=[], notes=[])


class TelegramTests(unittest.TestCase):
    def test_album_upload_has_three_attachments_and_caption_only_on_first(self):
        import httpx
        from email import policy
        from email.parser import BytesParser
        import json
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(200, json={"ok": True, "result": [{"message_id": 1}]})

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            TelegramAPI("fake-token", client=client).send_album(-100, 10, "Отчёт за 09.11–15.11", [b"one", b"two", b"three"])
        request = calls[0]
        self.assertTrue(request.url.path.endswith("/sendMediaGroup"))
        raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
        parts = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                 for part in BytesParser(policy=policy.default).parsebytes(raw).iter_parts()}
        media = json.loads(parts["media"])
        self.assertEqual(len(media), 3)
        self.assertEqual(media[0]["caption"], "Отчёт за 09.11–15.11")
        self.assertTrue(all("caption" not in item for item in media[1:]))
        for item, image in zip(media, [b"one", b"two", b"three"]):
            self.assertEqual(parts[item["media"].removeprefix("attach://")], image)

    def test_command_menu_is_scoped_to_group_and_excludes_service_command(self):
        import httpx
        import json
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(200, json={"ok": True, "result": True})

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            TelegramAPI("fake-token", client=client).set_commands(-100, 7)
        payload = json.loads(calls[0].content)
        self.assertTrue(calls[0].url.path.endswith("/setMyCommands"))
        self.assertEqual(payload["scope"], {"type": "chat", "chat_id": -100})
        self.assertEqual([item["command"] for item in payload["commands"]],
                         ["food", "today", "week", "goal", "help"])

    def test_long_poll_and_photo_upload_use_expected_api(self):
        import httpx
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(200, json={"ok": True, "result": []})

        client = httpx.Client(transport=httpx.MockTransport(handle))
        tg = TelegramAPI("fake-token", client=client)
        self.assertEqual(tg.poll(42, 1), [])
        tg.send_photo(-100, 10, "Калории", b"png")
        self.assertIn(b'"offset":42', calls[0].content)
        self.assertIn(b'filename="report.png"', calls[1].content)
        self.assertIn(b"png", calls[1].content)


class OpenAISDKTests(unittest.TestCase):
    def test_real_sdk_serializes_schema_and_parses_response_without_network(self):
        import httpx
        import json
        from openai import OpenAI

        requests = []

        def handle(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 1,
                "status": "completed", "model": "gpt-4.1-mini", "error": None,
                "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text",
                            "text": result().model_dump_json(), "annotations": []}]}]})

        with OpenAI(api_key="fake-key", http_client=httpx.Client(
                transport=httpx.MockTransport(handle))) as client:
            ai = OpenAIAnalyzer("fake-key", "gpt-4.1-mini", client=client)
            parsed = ai.analyze(images=[b"fake image"], captions=["половина"], notes=[])
        self.assertEqual(parsed.totals()["kcal"], 195)
        self.assertEqual(requests[0]["text"]["format"]["type"], "json_schema")
        self.assertTrue(requests[0]["text"]["format"]["strict"])
