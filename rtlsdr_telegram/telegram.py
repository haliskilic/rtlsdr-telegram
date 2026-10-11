"""Telegram Bot API client (plain HTTP via httpx; no extra dependency).

- send_message / send_voice / send_audio / send_photo / send_document
- Splits long text at the Telegram limit (4096) and truncates captions at 1024.
- Retries with backoff on 429 (flood) and transient network errors.
- get_updates receives commands (long polling); leave_chat leaves foreign chats.

When the network is down the sender raises; the Dispatcher keeps the message
queued and retries later.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

API = "https://api.telegram.org"
MSG_LIMIT = 4096
CAPTION_LIMIT = 1024


class TelegramError(Exception):
    def __init__(self, message: str, *, retry_after: float = 0, transient: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.transient = transient


class TelegramClient:
    def __init__(self, token: str, logger, *, proxy: str = "", timeout: float = 60.0):
        self.token = token
        self.log = logger
        self.base = f"{API}/bot{token}"
        self._tok_re = re.compile(re.escape(token)) if token else None
        kwargs: dict[str, Any] = {"timeout": httpx.Timeout(timeout, connect=15.0)}
        if proxy:
            kwargs["proxy"] = proxy
        self._client = httpx.Client(**kwargs)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _san(self, text: Any) -> str:
        """Strip the bot token from error texts (prevents log leakage)."""
        t = str(text)
        return self._tok_re.sub("<TOKEN>", t) if self._tok_re else t

    # ----------------------------------------------------------- low level
    def _call(self, method: str, *, data: dict | None = None, files: dict | None = None,
              timeout: float | None = None) -> dict:
        url = f"{self.base}/{method}"
        payload = {k: v for k, v in (data or {}).items() if v is not None}
        try:
            r = self._client.post(url, data=payload, files=files,
                                  timeout=timeout or self._client.timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError) as e:
            raise TelegramError(f"network error: {self._san(e)}", transient=True)
        except httpx.HTTPError as e:
            raise TelegramError(f"http error: {self._san(e)}", transient=True)
        try:
            js = r.json()
        except ValueError:
            if r.status_code >= 500:
                raise TelegramError(f"server {r.status_code}", transient=True)
            raise TelegramError(f"invalid response ({r.status_code})")
        if js.get("ok"):
            return js["result"]
        desc = js.get("description", "unknown error")
        params = js.get("parameters") or {}
        retry_after = float(params.get("retry_after", 0))
        code = js.get("error_code", 0)
        transient = code in (420, 429, 500, 502, 503, 504) or retry_after > 0
        raise TelegramError(f"{code}: {desc}", retry_after=retry_after, transient=transient)

    def _call_retry(self, method: str, *, data=None, files=None, attempts: int = 4, timeout=None) -> dict:
        last = None
        for i in range(attempts):
            try:
                return self._call(method, data=data, files=files, timeout=timeout)
            except TelegramError as e:
                last = e
                if not e.transient:
                    raise
                wait = e.retry_after or min(2 ** i, 15)
                self.log.debug("telegram %s will be retried (%.0fs): %s", method, wait, e)
                if files:  # rewind file streams
                    for f in files.values():
                        try:
                            f[1].seek(0)
                        except (AttributeError, OSError):
                            pass
                time.sleep(wait)
        raise last or TelegramError("unknown")

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _split(text: str, limit: int = MSG_LIMIT) -> list[str]:
        """Split text at line boundaries so every chunk is <= limit."""
        if len(text) <= limit:
            return [text]
        parts: list[str] = []
        cur = ""
        for line in text.split("\n"):
            # a single over-long line: flush what we have, then slice the line
            while len(line) > limit:
                if cur:
                    parts.append(cur)
                    cur = ""
                parts.append(line[:limit])
                line = line[limit:]
            candidate = line if not cur else cur + "\n" + line
            if len(candidate) > limit:
                parts.append(cur)
                cur = line
            else:
                cur = candidate
        if cur:
            parts.append(cur)
        return [p for p in parts if p != ""]

    @staticmethod
    def _strip_tags(text: str) -> str:
        return re.sub(r"</?(b|i|u|s|code|pre|a|tg-spoiler)[^>]*>", "", text)

    # --------------------------------------------------------------- API
    def get_me(self) -> dict:
        return self._call("getMe", timeout=20)

    def send_message(self, chat_id, text: str, *, thread_id: int | None = None,
                     reply_to: int | None = None, silent: bool = False,
                     parse_mode: str = "HTML", disable_preview: bool = True) -> list[int]:
        ids = []
        chunks = self._split(text)
        for i, chunk in enumerate(chunks):
            data = {
                "chat_id": chat_id, "text": chunk, "parse_mode": parse_mode,
                "disable_web_page_preview": disable_preview,
                "disable_notification": silent,
            }
            if thread_id:
                data["message_thread_id"] = thread_id
            if reply_to and i == 0:
                data["reply_to_message_id"] = reply_to
                data["allow_sending_without_reply"] = True
            try:
                res = self._call_retry("sendMessage", data=data)
            except TelegramError as e:
                # fall back to plain text on HTML parse errors
                if "can't parse" in str(e).lower() or "parse" in str(e).lower():
                    data.pop("parse_mode", None)
                    data["text"] = self._strip_tags(chunk)
                    res = self._call_retry("sendMessage", data=data)
                else:
                    raise
            ids.append(res.get("message_id"))
        return ids

    def _send_file(self, method: str, field: str, chat_id, path: str, *, caption: str | None = None,
                   thread_id: int | None = None, reply_to: int | None = None, silent: bool = False,
                   parse_mode: str = "HTML", extra: dict | None = None) -> int:
        data = {"chat_id": chat_id, "disable_notification": silent}
        if caption:
            data["caption"] = caption[:CAPTION_LIMIT]
            data["parse_mode"] = parse_mode
        if thread_id:
            data["message_thread_id"] = thread_id
        if reply_to:
            data["reply_to_message_id"] = reply_to
            data["allow_sending_without_reply"] = True
        if extra:
            data.update(extra)
        with open(path, "rb") as fh:
            files = {field: (os.path.basename(path), fh, "application/octet-stream")}
            try:
                res = self._call_retry(method, data=data, files=files, timeout=180)
            except TelegramError as e:
                if caption and "parse" in str(e).lower():
                    data.pop("parse_mode", None)
                    data["caption"] = self._strip_tags(caption)[:CAPTION_LIMIT]
                    fh.seek(0)
                    res = self._call_retry(method, data=data, files=files, timeout=180)
                else:
                    raise
        return res.get("message_id")

    def send_voice(self, chat_id, path, **kw) -> int:
        return self._send_file("sendVoice", "voice", chat_id, str(path), **kw)

    def send_audio(self, chat_id, path, **kw) -> int:
        return self._send_file("sendAudio", "audio", chat_id, str(path), **kw)

    def send_photo(self, chat_id, path, **kw) -> int:
        return self._send_file("sendPhoto", "photo", chat_id, str(path), **kw)

    def send_document(self, chat_id, path, **kw) -> int:
        return self._send_file("sendDocument", "document", chat_id, str(path), **kw)

    def leave_chat(self, chat_id) -> bool:
        """Leave a chat the bot was added to (used to refuse foreign groups)."""
        try:
            self._call("leaveChat", data={"chat_id": chat_id}, timeout=20)
            return True
        except TelegramError as e:
            self.log.debug("leaveChat failed: %s", e)
            return False

    def get_updates(self, offset: int | None = None, timeout: int = 30,
                    allowed: list[str] | None = None) -> list[dict]:
        data = {"timeout": timeout, "offset": offset,
                "allowed_updates": json.dumps(allowed or ["message", "channel_post", "my_chat_member"])}
        try:
            return self._call("getUpdates", data=data, timeout=timeout + 15)
        except TelegramError as e:
            if e.transient:
                return []
            raise
