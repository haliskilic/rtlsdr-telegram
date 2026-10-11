"""Telegram Bot API istemcisi (httpx ile doğrudan HTTP; ek bağımlılık gerektirmez).

- send_message / send_voice / send_audio / send_photo / send_document
- Uzun metni Telegram sınırında (4096) böler, medya başlığını (caption) 1024'te keser.
- 429 (flood) ve geçici ağ hatalarında geri çekilme (backoff) ile yeniden dener.
- get_updates ile komutları alır (uzun yoklama / long polling).

Ağ kesilince gönderici hata döndürür; Dispatcher mesajı kuyrukta tutup sonra dener.
"""
from __future__ import annotations

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
        kwargs: dict[str, Any] = {"timeout": httpx.Timeout(timeout, connect=15.0)}
        if proxy:
            kwargs["proxy"] = proxy
        self._client = httpx.Client(**kwargs)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    # ----------------------------------------------------------- düşük seviye
    def _call(self, method: str, *, data: dict | None = None, files: dict | None = None,
              timeout: float | None = None) -> dict:
        url = f"{self.base}/{method}"
        payload = {k: v for k, v in (data or {}).items() if v is not None}
        try:
            r = self._client.post(url, data=payload, files=files,
                                  timeout=timeout or self._client.timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError) as e:
            raise TelegramError(f"ağ hatası: {e}", transient=True)
        except httpx.HTTPError as e:
            raise TelegramError(f"http hatası: {e}", transient=True)
        try:
            js = r.json()
        except ValueError:
            if r.status_code >= 500:
                raise TelegramError(f"sunucu {r.status_code}", transient=True)
            raise TelegramError(f"geçersiz yanıt ({r.status_code})")
        if js.get("ok"):
            return js["result"]
        desc = js.get("description", "bilinmeyen hata")
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
                self.log.debug("telegram %s yeniden denenecek (%.0fs): %s", method, wait, e)
                if files:  # dosya akışını başa sar
                    for f in files.values():
                        try:
                            f[1].seek(0)
                        except (AttributeError, OSError):
                            pass
                time.sleep(wait)
        raise last or TelegramError("bilinmeyen")

    # --------------------------------------------------------------- yardımcı
    @staticmethod
    def _split(text: str, limit: int = MSG_LIMIT) -> list[str]:
        if len(text) <= limit:
            return [text]
        parts, cur = [], ""
        for line in text.split("\n"):
            while len(line) > limit:
                parts.append((cur + "\n" + line[:limit]).strip() if cur else line[:limit])
                line = line[limit:]
                cur = ""
            if len(cur) + len(line) + 1 > limit:
                parts.append(cur)
                cur = line
            else:
                cur = (cur + "\n" + line) if cur else line
        if cur:
            parts.append(cur)
        return parts

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
                # HTML ayrıştırma hatasında düz metne düş
                if "can't parse" in str(e).lower() or "parse" in str(e).lower():
                    data.pop("parse_mode", None)
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
            files = {field: (path.split("/")[-1], fh, "application/octet-stream")}
            res = self._call_retry(method, data=data, files=files, timeout=180)
        return res.get("message_id")

    def send_voice(self, chat_id, path, **kw) -> int:
        return self._send_file("sendVoice", "voice", chat_id, str(path), **kw)

    def send_audio(self, chat_id, path, **kw) -> int:
        return self._send_file("sendAudio", "audio", chat_id, str(path), **kw)

    def send_photo(self, chat_id, path, **kw) -> int:
        return self._send_file("sendPhoto", "photo", chat_id, str(path), **kw)

    def send_document(self, chat_id, path, **kw) -> int:
        return self._send_file("sendDocument", "document", chat_id, str(path), **kw)

    def get_updates(self, offset: int | None = None, timeout: int = 30,
                    allowed: list[str] | None = None) -> list[dict]:
        data = {"timeout": timeout, "offset": offset,
                "allowed_updates": allowed or ["message", "channel_post"]}
        try:
            return self._call("getUpdates", data=data, timeout=timeout + 15)
        except TelegramError as e:
            if e.transient:
                return []
            raise
