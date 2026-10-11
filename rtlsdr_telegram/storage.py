"""SQLite tabanlı kalıcı depolama: olaylar, gönderim kuyruğu, cihaz kayıt defteri,
ses kayıtları, hedef çalışma geçmişi ve hata günlüğü.

Tek bağlantı + kilit ile iş parçacığı güvenlidir (hem asyncio döngüsü hem de
tarayıcı iş parçacıkları kullanır).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .events import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL,
    target TEXT,
    freq_mhz REAL,
    summary TEXT,
    body TEXT,
    priority INTEGER DEFAULT 5,
    duration_s REAL,
    signal TEXT,
    signal_value REAL,
    lat REAL, lon REAL,
    photos INTEGER DEFAULT 0,
    audio INTEGER DEFAULT 0,
    extra TEXT,
    sent_at REAL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_cat ON events(category, ts);

CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    priority INTEGER NOT NULL,
    ts REAL NOT NULL,
    event_json TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    next_try REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_queue_order ON queue(priority, ts);

CREATE TABLE IF NOT EXISTS registry (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    count INTEGER DEFAULT 1,
    data TEXT,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS idx_registry_seen ON registry(kind, last_seen);

CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    target TEXT,
    freq_mhz REAL,
    channel TEXT,
    duration_s REAL,
    path TEXT,
    signal TEXT,
    transcript TEXT,
    event_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_rec_ts ON recordings(ts);

CREATE TABLE IF NOT EXISTS target_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    started REAL NOT NULL,
    ended REAL,
    reason TEXT,
    events INTEGER DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON target_runs(started);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    target TEXT,
    message TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _exec(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    # ------------------------------------------------------------------ events
    def insert_event(self, ev: Event) -> int:
        cur = self._exec(
            "INSERT INTO events (ts,event_type,category,target,freq_mhz,summary,body,priority,duration_s,"
            "signal,signal_value,lat,lon,photos,audio,extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ev.time_utc.timestamp(), ev.event_type, ev.category.value, ev.target, ev.freq_mhz,
             ev.summary, ev.body, ev.priority, ev.duration_s, ev.signal, ev.signal_value, ev.lat, ev.lon,
             ev.has_photos, sum(1 for a in ev.attachments if a.kind in ("voice", "audio")),
             json.dumps(ev.extra, ensure_ascii=False, default=str) if ev.extra else None),
        )
        ev.db_id = int(cur.lastrowid)
        return ev.db_id

    def mark_sent(self, event_id: int | None) -> None:
        if event_id:
            self._exec("UPDATE events SET sent_at=? WHERE id=?", (time.time(), event_id))

    def update_event_transcript(self, event_id: int | None, transcript: str | None, summary: str | None) -> None:
        if event_id:
            self._exec("UPDATE events SET summary=COALESCE(?, summary), body=body WHERE id=?", (summary, event_id))
            if transcript is not None:
                self._exec("UPDATE recordings SET transcript=? WHERE event_id=?", (transcript, event_id))

    def events_between(self, t0: float, t1: float) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM events WHERE ts>=? AND ts<? ORDER BY ts", (t0, t1))

    def count_by(self, column: str, t0: float, t1: float) -> list[tuple[str, int]]:
        assert column in ("category", "target", "event_type")
        rows = self._query(f"SELECT {column} AS k, COUNT(*) AS n FROM events WHERE ts>=? AND ts<? "
                           f"AND category!='Sistem' GROUP BY {column} ORDER BY n DESC", (t0, t1))
        return [(r["k"] or "—", r["n"]) for r in rows]

    def top_events(self, t0: float, t1: float, n: int = 5) -> list[sqlite3.Row]:
        return self._query(
            "SELECT * FROM events WHERE ts>=? AND ts<? AND category!='Sistem' "
            "ORDER BY priority ASC, COALESCE(signal_value,-999) DESC, ts DESC LIMIT ?", (t0, t1, n))

    def audio_total_s(self, t0: float, t1: float) -> float:
        rows = self._query("SELECT COALESCE(SUM(duration_s),0) AS s FROM recordings WHERE ts>=? AND ts<?", (t0, t1))
        return float(rows[0]["s"] or 0.0)

    def photos_total(self, t0: float, t1: float) -> int:
        rows = self._query("SELECT COALESCE(SUM(photos),0) AS s FROM events WHERE ts>=? AND ts<?", (t0, t1))
        return int(rows[0]["s"] or 0)

    def events_count(self, t0: float, t1: float) -> int:
        rows = self._query("SELECT COUNT(*) AS n FROM events WHERE ts>=? AND ts<? AND category!='Sistem'", (t0, t1))
        return int(rows[0]["n"])

    # ------------------------------------------------------------------- queue
    def queue_push(self, ev: Event) -> int:
        cur = self._exec("INSERT INTO queue (priority, ts, event_json) VALUES (?,?,?)",
                         (ev.priority, time.time(), ev.to_json()))
        return int(cur.lastrowid)

    def queue_pop(self) -> tuple[int, Event, int] | None:
        """Gönderilmeye hazır en öncelikli ögeyi döndürür (id, event, attempts) — silmez."""
        now = time.time()
        rows = self._query("SELECT id, event_json, attempts FROM queue WHERE next_try<=? "
                           "ORDER BY priority ASC, ts ASC LIMIT 1", (now,))
        if not rows:
            return None
        r = rows[0]
        try:
            ev = Event.from_json(r["event_json"])
        except Exception:
            self._exec("DELETE FROM queue WHERE id=?", (r["id"],))
            return None
        return int(r["id"]), ev, int(r["attempts"])

    def queue_ack(self, qid: int) -> None:
        self._exec("DELETE FROM queue WHERE id=?", (qid,))

    def queue_fail(self, qid: int, error: str, delay_s: float) -> None:
        self._exec("UPDATE queue SET attempts=attempts+1, last_error=?, next_try=? WHERE id=?",
                   (error[:500], time.time() + delay_s, qid))

    def queue_len(self) -> int:
        return int(self._query("SELECT COUNT(*) AS n FROM queue")[0]["n"])

    def queue_next_time(self) -> float | None:
        rows = self._query("SELECT MIN(next_try) AS t FROM queue")
        return rows[0]["t"] if rows and rows[0]["t"] is not None else None

    # ---------------------------------------------------------------- registry
    def registry_touch(self, kind: str, key: str, data: dict | None = None) -> tuple[bool, float, int]:
        """Kaydı günceller/oluşturur. (yeni_mi, ilk_görülme, sayaç) döndürür."""
        now = time.time()
        with self._lock:
            row = self._conn.execute("SELECT first_seen, count, data FROM registry WHERE kind=? AND key=?",
                                     (kind, key)).fetchone()
            if row is None:
                self._conn.execute("INSERT INTO registry (kind,key,first_seen,last_seen,count,data) VALUES (?,?,?,?,1,?)",
                                   (kind, key, now, now, json.dumps(data or {}, ensure_ascii=False, default=str)))
                self._conn.commit()
                return True, now, 1
            merged = {}
            try:
                merged = json.loads(row["data"] or "{}")
            except json.JSONDecodeError:
                merged = {}
            if data:
                merged.update({k: v for k, v in data.items() if v is not None})
            self._conn.execute("UPDATE registry SET last_seen=?, count=count+1, data=? WHERE kind=? AND key=?",
                               (now, json.dumps(merged, ensure_ascii=False, default=str), kind, key))
            self._conn.commit()
            return False, float(row["first_seen"]), int(row["count"]) + 1

    def registry_get(self, kind: str, key: str) -> dict | None:
        rows = self._query("SELECT * FROM registry WHERE kind=? AND key=?", (kind, key))
        if not rows:
            return None
        r = rows[0]
        try:
            data = json.loads(r["data"] or "{}")
        except json.JSONDecodeError:
            data = {}
        return {"first_seen": r["first_seen"], "last_seen": r["last_seen"], "count": r["count"], "data": data}

    def registry_set_data(self, kind: str, key: str, data: dict) -> None:
        self._exec("UPDATE registry SET data=? WHERE kind=? AND key=?",
                   (json.dumps(data, ensure_ascii=False, default=str), kind, key))

    def registry_count(self, kind: str, t0: float, t1: float, new_only: bool = False) -> int:
        col = "first_seen" if new_only else "last_seen"
        rows = self._query(f"SELECT COUNT(*) AS n FROM registry WHERE kind=? AND {col}>=? AND {col}<?", (kind, t0, t1))
        return int(rows[0]["n"])

    def registry_new(self, kind: str, t0: float, t1: float, limit: int = 20) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM registry WHERE kind=? AND first_seen>=? AND first_seen<? "
                           "ORDER BY first_seen DESC LIMIT ?", (kind, t0, t1, limit))

    def registry_kinds(self) -> list[str]:
        return [r["kind"] for r in self._query("SELECT DISTINCT kind FROM registry")]

    # -------------------------------------------------------------- recordings
    def add_recording(self, ts: float, target: str, freq_mhz: float, channel: str | None, duration_s: float,
                      path: str, signal: str | None, event_id: int | None) -> int:
        cur = self._exec("INSERT INTO recordings (ts,target,freq_mhz,channel,duration_s,path,signal,event_id) "
                         "VALUES (?,?,?,?,?,?,?,?)", (ts, target, freq_mhz, channel, duration_s, path, signal, event_id))
        return int(cur.lastrowid)

    def update_recording_path(self, rec_id: int, path: str) -> None:
        self._exec("UPDATE recordings SET path=? WHERE id=?", (path, rec_id))

    def recent_recordings(self, n: int) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM recordings ORDER BY ts DESC LIMIT ?", (n,))

    # ------------------------------------------------------------- target runs
    def run_start(self, target: str, reason: str) -> int:
        cur = self._exec("INSERT INTO target_runs (target, started, reason) VALUES (?,?,?)", (target, time.time(), reason))
        return int(cur.lastrowid)

    def run_end(self, run_id: int, events: int, error: str | None) -> None:
        self._exec("UPDATE target_runs SET ended=?, events=?, error=? WHERE id=?", (time.time(), events, error, run_id))

    def runtime_by_target(self, t0: float, t1: float) -> list[tuple[str, float, int]]:
        rows = self._query("SELECT target, SUM(COALESCE(ended, ?)-started) AS s, SUM(events) AS e FROM target_runs "
                           "WHERE started>=? AND started<? GROUP BY target ORDER BY s DESC", (time.time(), t0, t1))
        return [(r["target"], float(r["s"] or 0), int(r["e"] or 0)) for r in rows]

    # ------------------------------------------------------------------ errors
    def log_error(self, target: str, message: str) -> None:
        self._exec("INSERT INTO errors (ts, target, message) VALUES (?,?,?)", (time.time(), target, message[:1000]))

    def errors_between(self, t0: float, t1: float) -> list[tuple[str, int]]:
        rows = self._query("SELECT target, COUNT(*) AS n FROM errors WHERE ts>=? AND ts<? GROUP BY target ORDER BY n DESC",
                           (t0, t1))
        return [(r["target"] or "—", r["n"]) for r in rows]

    def error_count(self, t0: float, t1: float) -> int:
        return int(self._query("SELECT COUNT(*) AS n FROM errors WHERE ts>=? AND ts<?", (t0, t1))[0]["n"])

    # ---------------------------------------------------------------------- kv
    def kv_get(self, key: str, default: Any = None) -> Any:
        rows = self._query("SELECT value FROM kv WHERE key=?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except json.JSONDecodeError:
            return rows[0]["value"]

    def kv_set(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value, ensure_ascii=False, default=str)))

    # ----------------------------------------------------------------- cleanup
    def cleanup(self, retention_days: int) -> tuple[int, list[str]]:
        """Eski kayıtları siler; silinecek dosya yollarını döndürür."""
        cutoff = time.time() - retention_days * 86400
        rows = self._query("SELECT path FROM recordings WHERE ts<?", (cutoff,))
        paths = [r["path"] for r in rows if r["path"]]
        self._exec("DELETE FROM recordings WHERE ts<?", (cutoff,))
        self._exec("DELETE FROM events WHERE ts<?", (cutoff - 76 * 86400,))
        self._exec("DELETE FROM target_runs WHERE started<?", (cutoff,))
        self._exec("DELETE FROM errors WHERE ts<?", (cutoff,))
        self._exec("DELETE FROM queue WHERE attempts>=20")
        # kayıt defteri: 90 gündür görülmeyen uçak/gemi/cihaz/istasyon kayıtları
        self._exec("DELETE FROM registry WHERE last_seen<? AND kind IN "
                   "('aircraft','ship','ism_device','aprs_station','acars_ac','vdl2_ac','spectrum_anom','sonde_carrier')",
                   (time.time() - 90 * 86400,))
        return len(paths), paths
