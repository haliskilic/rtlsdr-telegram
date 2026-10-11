"""Event dispatcher: takes events from the persistent priority queue and sends them to Telegram.

- Every event goes to the same topic (message_thread_id); events are told apart
  by the structured header fields (spec section 5).
- An event is sent as: header+body text -> audio/image attachments (as replies
  to the text, in the same thread). The transcript is part of the text.
- Emergency events (lowest priority number) jump the queue (ORDER BY priority).
- When the network is down sending fails; the event stays queued and is retried
  when connectivity returns (spec section 9).
- Sending is rate limited (telegram.min_interval_s). Only the configured chat
  (or an admin's command context) is ever written to.
"""
from __future__ import annotations

import os
import threading
import time
from zoneinfo import ZoneInfo

from .events import Event, Category, PRIO_EMERGENCY
from .telegram import TelegramClient, TelegramError


class Dispatcher:
    def __init__(self, cfg, storage, client: TelegramClient, logger):
        self.cfg = cfg
        self.st = storage
        self.client = client
        self.log = logger
        tg = cfg.section("telegram")
        self.chat_id = tg.get("chat_id")
        self.thread_id = tg.get("thread_id") or None
        self.min_interval = float(tg.get("min_interval_s", 2.0))
        self.quiet_priority_from = int(tg.get("quiet_priority_from", 4))
        try:
            self.tz = ZoneInfo(cfg.get("timezone", "Europe/Istanbul"))
        except Exception:
            self.tz = ZoneInfo("UTC")
        self.station_lat = cfg.get("station.lat")
        self.station_lon = cfg.get("station.lon")
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_send = 0.0
        self.online = True
        self.sent_count = 0
        self.transcriber = None  # assigned by the application
        self.scheduler = None    # assigned by the application (mute checks)

    # ----------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def submit(self, ev: Event) -> None:
        """Append the event to the persistent queue and wake the sender."""
        try:
            if ev.category != Category.SISTEM:
                self.st.insert_event(ev)
        except Exception as e:
            self.log.warning("event could not be stored: %s", e)
        self.st.queue_push(ev)
        self._wake.set()

    # ---------------------------------------------------------------- loop
    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self.st.queue_pop()
            if item is None:
                self._wake.wait(timeout=5)
                self._wake.clear()
                continue
            qid, ev, attempts = item
            # rate limiting (except emergencies)
            if ev.priority > PRIO_EMERGENCY:
                gap = self.min_interval - (time.time() - self._last_send)
                if gap > 0:
                    self._stop.wait(gap)
            try:
                if self._muted(ev):
                    self.log.debug("muted category, skipped: %s", ev.category.value)
                    self.st.queue_ack(qid)
                    continue
                self._send_event(ev, qid)
                self.st.queue_ack(qid)
                self.st.mark_sent(ev.db_id)
                self._last_send = time.time()
                self.sent_count += 1
                if not self.online:
                    self.online = True
                    self.log.info("telegram connection restored")
            except TelegramError as e:
                delay = e.retry_after or min(10 * (attempts + 1), 300)
                if e.transient:
                    if self.online:
                        self.online = False
                        self.log.warning("telegram offline, keeping the queue: %s", e)
                    self.st.queue_fail(qid, str(e), max(delay, 15))
                    self._stop.wait(min(delay, 30))
                else:
                    self.log.error("telegram permanent error (event skipped): %s", e)
                    self.st.queue_fail(qid, str(e), delay)
                    if attempts >= 5:
                        self.st.queue_ack(qid)
            except Exception as e:
                self.log.exception("unexpected send error: %s", e)
                self.st.queue_fail(qid, str(e), 30)

    # ----------------------------------------------------------- sending
    def _silent(self, ev: Event) -> bool:
        if ev.silent is not None:
            return ev.silent
        return ev.priority >= self.quiet_priority_from

    def _muted(self, ev: Event) -> bool:
        """Muted category check: emergencies (priority 0) always pass."""
        if ev.priority <= PRIO_EMERGENCY or ev.category == Category.SISTEM:
            return False
        sch = self.scheduler
        try:
            return bool(sch and sch.is_muted(ev.category))
        except Exception:
            return False

    def _send_event(self, ev: Event, qid: int | None = None) -> None:
        silent = self._silent(ev)
        chat = ev.reply_to["chat_id"] if ev.reply_to else self.chat_id
        thread = (ev.reply_to.get("message_thread_id") if ev.reply_to else self.thread_id)
        reply_to = ev.reply_to.get("message_id") if ev.reply_to else None

        # Partial progress: if the text was already sent (an attachment upload failed
        # and we are retrying) do not send the text again — avoids duplicates.
        anchor = ev.extra.get("_anchor_msg_id") if ev.extra else None
        if not anchor:
            text = ev.to_html(self.tz, self.station_lat, self.station_lon)
            msg_ids = self.client.send_message(chat, text, thread_id=thread, reply_to=reply_to, silent=silent)
            anchor = msg_ids[0] if msg_ids else None
            if anchor and qid is not None and ev.attachments:
                ev.extra["_anchor_msg_id"] = anchor
                try:
                    self.st._exec("UPDATE queue SET event_json=? WHERE id=?", (ev.to_json(), qid))
                except Exception:
                    pass

        done = set(ev.extra.get("_sent_atts", [])) if ev.extra else set()
        for i, att in enumerate(ev.attachments):
            if i in done:
                continue
            if not att.path or not os.path.exists(att.path):
                self.log.warning("attachment file not found: %s", att.path)
                continue
            cap = att.caption
            if att.kind == "voice":
                self.client.send_voice(chat, att.path, caption=cap, thread_id=thread, reply_to=anchor, silent=True)
            elif att.kind == "audio":
                self.client.send_audio(chat, att.path, caption=cap, thread_id=thread, reply_to=anchor, silent=True)
            elif att.kind == "photo":
                try:
                    self.client.send_photo(chat, att.path, caption=cap, thread_id=thread, reply_to=anchor, silent=True)
                except TelegramError as e:
                    if e.transient:
                        raise
                    # if the photo is rejected (size/ratio) send it as a document
                    self.client.send_document(chat, att.path, caption=cap, thread_id=thread, reply_to=anchor, silent=True)
            else:
                self.client.send_document(chat, att.path, caption=cap, thread_id=thread, reply_to=anchor, silent=True)
            # success: record progress, delete the temp file only now
            done.add(i)
            if qid is not None and len(ev.attachments) > 1:
                ev.extra["_sent_atts"] = sorted(done)
                try:
                    self.st._exec("UPDATE queue SET event_json=? WHERE id=?", (ev.to_json(), qid))
                except Exception:
                    pass
            if att.delete_after:
                try:
                    os.unlink(att.path)
                except OSError:
                    pass

    # ---------------------------------------------------- direct text (command replies)
    def send_text(self, text: str, *, chat_id=None, thread_id=None, reply_to=None, silent=True) -> None:
        try:
            self.client.send_message(chat_id or self.chat_id,
                                     text,
                                     thread_id=thread_id if thread_id is not None else self.thread_id,
                                     reply_to=reply_to, silent=silent)
        except TelegramError as e:
            self.log.warning("direct text send failed: %s", e)
