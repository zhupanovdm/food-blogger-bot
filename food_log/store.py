import json
import sqlite3
from datetime import datetime, timedelta, timezone as utc_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .nutrition import Assessment, format_totals


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY, value INTEGER);
            INSERT OR IGNORE INTO cursor VALUES (1, 0);
            CREATE TABLE IF NOT EXISTS inbox (
                id INTEGER PRIMARY KEY, payload TEXT NOT NULL, done INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY, identity TEXT UNIQUE, chat INTEGER,
                source INTEGER, eaten_at INTEGER, result TEXT,
                state TEXT DEFAULT 'pending', ready REAL, attempts INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS photos (
                chat INTEGER, message INTEGER, meal INTEGER REFERENCES meals(id),
                file_id TEXT, caption TEXT, PRIMARY KEY(chat,message));
            CREATE TABLE IF NOT EXISTS notes (
                chat INTEGER, message INTEGER, meal INTEGER REFERENCES meals(id),
                body TEXT, PRIMARY KEY(chat,message));
            CREATE TABLE IF NOT EXISTS links (
                chat INTEGER, message INTEGER, meal INTEGER REFERENCES meals(id),
                PRIMARY KEY(chat,message));
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY, chat INTEGER, reply INTEGER,
                meal INTEGER REFERENCES meals(id), body TEXT, sent INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS outbox_media (
                entry INTEGER REFERENCES outbox(id), position INTEGER, image BLOB NOT NULL,
                PRIMARY KEY(entry,position));
        """)
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(outbox)")}
        for name, declaration in (("kind", "TEXT DEFAULT 'text'"), ("image", "BLOB")):
            if name not in columns:
                self.conn.execute(f"ALTER TABLE outbox ADD COLUMN {name} {declaration}")
        for table in ("photos", "notes"):
            columns = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if "updated_at" not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN updated_at INTEGER DEFAULT 0")
                self.conn.execute(f"UPDATE {table} SET updated_at=(SELECT eaten_at FROM meals WHERE id={table}.meal)")
            if "updated_seq" not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN updated_seq INTEGER DEFAULT 0")
        self.conn.commit()

    def close(self):
        self.conn.close()

    def offset(self):
        return self.conn.execute("SELECT value FROM cursor WHERE id=1").fetchone()[0]

    def save_updates(self, updates):
        with self.conn:
            for update in updates:
                self.conn.execute("INSERT OR IGNORE INTO inbox(id,payload) VALUES (?,?)",
                                  (update["update_id"], json.dumps(update)))
            if updates:
                self.conn.execute("UPDATE cursor SET value=MAX(value,?) WHERE id=1",
                                  (max(u["update_id"] for u in updates) + 1,))

    def advance(self, update_id):
        with self.conn:
            self.conn.execute("UPDATE cursor SET value=MAX(value,?) WHERE id=1", (update_id + 1,))

    def pending_updates(self):
        return [json.loads(r[0]) for r in self.conn.execute(
            "SELECT payload FROM inbox WHERE done=0 ORDER BY id")]

    def done(self, update_id):
        # Удаляем обработанное событие: нужные данные уже в meals/photos/notes/outbox.
        self.conn.execute("DELETE FROM inbox WHERE id=?", (update_id,))

    def add_photo(self, msg, now, edited=False, sequence=0):
        chat, mid = msg["chat"]["id"], msg["message_id"]
        ready = now + (8 if msg.get("media_group_id") else 2)
        identity = f"{chat}:" + ("album:" + msg["media_group_id"] if msg.get("media_group_id") else f"photo:{mid}")
        existing = self.conn.execute("SELECT * FROM photos WHERE chat=? AND message=?", (chat, mid)).fetchone()
        if existing:
            meal = existing["meal"]
        else:
            self.conn.execute("""INSERT OR IGNORE INTO meals(identity,chat,source,eaten_at,ready)
                              VALUES (?,?,?,?,?)""", (identity, chat, mid, msg["date"], ready))
            meal = self.conn.execute("SELECT id FROM meals WHERE identity=?", (identity,)).fetchone()[0]
        version = msg.get("edit_date", msg["date"])
        if existing and edited:
            changed = (version, sequence) >= (existing["updated_at"], existing["updated_seq"]) and (
                msg.get("caption", "") != existing["caption"] or msg["photo"][-1]["file_id"] != existing["file_id"])
            if changed:
                self.conn.execute("UPDATE photos SET caption=?,file_id=?,updated_at=?,updated_seq=? WHERE chat=? AND message=?",
                    (msg.get("caption", ""), msg["photo"][-1]["file_id"], version, sequence, chat, mid))
        elif existing:
            changed = False
        else:
            self.conn.execute("INSERT INTO photos(chat,message,meal,file_id,caption,updated_at,updated_seq) VALUES (?,?,?,?,?,?,?)",
                (chat, mid, meal, msg["photo"][-1]["file_id"], msg.get("caption", ""), version, sequence))
            changed = True
        self.link(chat, mid, meal)
        if changed:
            self.conn.execute("UPDATE meals SET state='pending',ready=?,attempts=0 WHERE id=?",
                              (ready, meal))
        self.conn.commit()
        return meal

    def text_meal(self, chat, message):
        row = self.conn.execute("SELECT id FROM meals WHERE identity=?",
                                (f"{chat}:text:{message}",)).fetchone()
        return row[0] if row else None

    def add_text_meal(self, msg, body, now, edited=False, sequence=0):
        chat, mid = msg["chat"]["id"], msg["message_id"]
        with self.conn:
            self.conn.execute("""INSERT OR IGNORE INTO meals(identity,chat,source,eaten_at,ready)
                              VALUES (?,?,?,?,?)""",
                              (f"{chat}:text:{mid}", chat, mid, msg["date"], now))
            meal = self.text_meal(chat, mid)
            self.add_note(meal, mid, body, now, edited=edited,
                          version=msg.get("edit_date", msg["date"]), sequence=sequence)
        return meal

    def link(self, chat, message, meal):
        self.conn.execute("INSERT OR IGNORE INTO links VALUES (?,?,?)", (chat, message, meal))

    def linked_meal(self, chat, message):
        row = self.conn.execute("SELECT meal FROM links WHERE chat=? AND message=?", (chat, message)).fetchone()
        return row[0] if row else None

    def add_note(self, meal, message, body, now, edited=False, version=None, sequence=0):
        row = self.conn.execute("SELECT * FROM meals WHERE id=?", (meal,)).fetchone()
        chat = row["chat"]
        version = int(now) if version is None else version
        existing = self.conn.execute("SELECT * FROM notes WHERE chat=? AND message=?", (chat, message)).fetchone()
        if existing:
            changed = edited and (version, sequence) >= (existing["updated_at"], existing["updated_seq"]) and body != existing["body"]
            if changed:
                self.conn.execute("UPDATE notes SET body=?,updated_at=?,updated_seq=? WHERE chat=? AND message=?",
                                  (body, version, sequence, chat, message))
        else:
            self.conn.execute("INSERT INTO notes(chat,message,meal,body,updated_at,updated_seq) VALUES (?,?,?,?,?,?)",
                              (chat, message, meal, body, version, sequence))
            changed = True
        self.link(chat, message, meal)
        if changed:
            ready = max(now, row["ready"]) if ":album:" in row["identity"] and row["state"] == "pending" else now
            self.conn.execute("UPDATE meals SET state='pending',ready=?,attempts=0 WHERE id=?", (ready, meal))
        self.conn.commit()

    def photos(self, meal):
        return [dict(r) for r in self.conn.execute("SELECT * FROM photos WHERE meal=? ORDER BY message", (meal,))]

    def notes(self, meal):
        return [r[0] for r in self.conn.execute("SELECT body FROM notes WHERE meal=? ORDER BY updated_at,updated_seq,message", (meal,))]

    def evidence(self, meal):
        captions = [{"kind": "caption", "body": row["caption"], "version": row["updated_at"], "sequence": row["updated_seq"]}
                    for row in self.conn.execute("SELECT * FROM photos WHERE meal=? ORDER BY message", (meal,))]
        notes = [{"kind": "correction", "body": row["body"], "version": row["updated_at"], "sequence": row["updated_seq"]}
                 for row in self.conn.execute("SELECT * FROM notes WHERE meal=? ORDER BY message", (meal,))]
        return sorted(captions + notes, key=lambda event: (event["version"], event["sequence"]))

    def latest_meal(self, chat, timestamp):
        row = self.conn.execute("""SELECT id FROM meals WHERE chat=? AND eaten_at<=? AND eaten_at>=?
                                  ORDER BY eaten_at DESC,source DESC LIMIT 1""",
                                (chat, timestamp, timestamp - 86400)).fetchone()
        return row[0] if row else None

    def next_meal(self, now):
        row = self.conn.execute("SELECT * FROM meals WHERE state='pending' AND ready<=? ORDER BY id LIMIT 1",
                                (now,)).fetchone()
        return dict(row) if row else None

    def finish(self, meal, assessment, text):
        with self.conn:
            row = self.conn.execute("SELECT * FROM meals WHERE id=?", (meal,)).fetchone()
            self.conn.execute("UPDATE meals SET result=?,state=? WHERE id=?",
                              (assessment.model_dump_json(), assessment.status, meal))
            self.queue(row["chat"], row["source"], text, meal)

    def fail(self, meal, now):
        with self.conn:
            row = self.conn.execute("SELECT * FROM meals WHERE id=?", (meal,)).fetchone()
            attempts = row["attempts"] + 1
            state = "error" if attempts >= 3 else "pending"
            self.conn.execute("UPDATE meals SET attempts=?,state=?,ready=? WHERE id=?",
                              (attempts, state, now + 30 * attempts, meal))
            if state == "error":
                self.queue(row["chat"], row["source"],
                    "Не удалось проанализировать еду после 3 попыток. Предыдущая оценка, если была, "
                    "сохранена. Ответь «повтори» на фото или этот ответ для новой попытки.", meal)

    def queue(self, chat, reply, text, meal=None):
        self.conn.execute("INSERT INTO outbox(chat,reply,meal,body) VALUES (?,?,?,?)",
                          (chat, reply, meal, text))

    def queue_photo(self, chat, reply, caption, image):
        self.conn.execute("INSERT INTO outbox(chat,reply,body,kind,image) VALUES (?,?,?,'photo',?)",
                          (chat, reply, caption, image))

    def queue_album(self, chat, reply, caption, images):
        if len(images) not in (2, 3):
            raise ValueError("Альбом отчёта должен содержать две или три диаграммы")
        entry = self.conn.execute("INSERT INTO outbox(chat,reply,body,kind) VALUES (?,?,?,'album')",
                                  (chat, reply, caption)).lastrowid
        self.conn.executemany("INSERT INTO outbox_media VALUES (?,?,?)",
                              [(entry, index, image) for index, image in enumerate(images)])

    def goal(self):
        row = self.conn.execute("SELECT value FROM settings WHERE name='goal'").fetchone()
        return float(row[0]) if row else None

    def set_goal(self, value):
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES ('goal',?)", (str(value),))
        self.conn.commit()

    def daily(self, now, days=7, timezone="Europe/Moscow"):
        zone = ZoneInfo(timezone)
        end = now.astimezone(zone).date()
        start = end - timedelta(days=days-1)
        buckets = {start + timedelta(days=i): dict(
            date=start + timedelta(days=i), totals=None, meals=[], timezone=timezone,
            is_today=(start + timedelta(days=i) == end), pending=0, errors=0)
            for i in range(days)}
        for row in self.conn.execute("SELECT * FROM meals ORDER BY eaten_at, id"):
            day = datetime.fromtimestamp(row["eaten_at"], zone).date()
            if day not in buckets:
                continue
            bucket = buckets[day]
            bucket["pending"] += row["state"] in ("pending", "clarify")
            bucket["errors"] += row["state"] == "error"
            assessment = Assessment.model_validate_json(row["result"]) if row["result"] else None
            if assessment is None or assessment.totals() is None:
                continue
            values = assessment.totals()
            bucket["meals"].append(dict(
                occurred_at=datetime.fromtimestamp(row["eaten_at"], utc_timezone.utc).isoformat(),
                meal=assessment.category, totals=values))
            if bucket["totals"] is None:
                bucket["totals"] = {key: 0 for key in values}
            for key, value in values.items():
                bucket["totals"][key] += value
        return list(buckets.values())

    def outgoing(self):
        entries = [dict(r) for r in self.conn.execute("SELECT * FROM outbox WHERE sent=0 ORDER BY id LIMIT 20")]
        for entry in entries:
            if entry["kind"] == "album":
                entry["images"] = [row[0] for row in self.conn.execute(
                    "SELECT image FROM outbox_media WHERE entry=? ORDER BY position", (entry["id"],))]
        return entries

    def delivered(self, entry, message_id):
        with self.conn:
            if entry["meal"] is not None:
                self.link(entry["chat"], message_id, entry["meal"])
            self.conn.execute("UPDATE outbox SET sent=1,image=NULL WHERE id=?", (entry["id"],))
            self.conn.execute("DELETE FROM outbox_media WHERE entry=?", (entry["id"],))

    def report(self, now, days, timezone="Europe/Moscow"):
        zone = ZoneInfo(timezone)
        end = now.astimezone(zone).date()
        start = end - timedelta(days=days - 1)
        totals = {}
        pending = errors = 0
        for row in self.conn.execute("SELECT * FROM meals"):
            day = datetime.fromtimestamp(row["eaten_at"], zone).date()
            if not start <= day <= end:
                continue
            pending += row["state"] in ("pending", "clarify")
            errors += row["state"] == "error"
            value = Assessment.model_validate_json(row["result"]).totals() if row["result"] else None
            if value is not None:
                bucket = totals.setdefault(day, dict(kcal=0, protein=0, fat=0, carbs=0))
                for key in bucket:
                    bucket[key] += value[key]
        lines = ["Дневник · приблизительные оценки", "Последние 7 дней:" if days == 7 else "Сегодня:"]
        for offset in range(days):
            day = start + timedelta(days=offset)
            lines.append(f"{day:%d.%m}: " + (format_totals(totals[day]) if day in totals else "нет записей"))
        if days > 1 and totals:
            sums = {key: sum(t[key] for t in totals.values()) for key in ("kcal", "protein", "fat", "carbs")}
            lines.append("Всего: " + format_totals(sums))
            lines.append(f"Среднее за дни с записями ({len(totals)}): " +
                         format_totals({key: v / len(totals) for key, v in sums.items()}))
        lines.append("Полнота дневника не проверена; дни без записей не считаются нулевыми.")
        if pending:
            lines.append(f"Ожидают анализа/уточнения: {pending}. При исправлениях пока учитывается предыдущая оценка.")
        if errors:
            lines.append(f"Ошибки анализа: {errors}. Предыдущие оценки сохранены, новые записи не учтены.")
        return "\n".join(lines)
