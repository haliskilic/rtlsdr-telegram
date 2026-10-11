"""Hedef temel sınıfı ve ortak bağlam (context)."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..events import Event, Category, Attachment, PRIO_NORMAL, esc
from ..proc import ManagedProcess, looks_like_device_error


@dataclass
class TargetContext:
    """Hedeflere enjekte edilen paylaşımlı bağımlılıklar."""
    cfg: Any
    sdr: Any
    storage: Any
    dispatcher: Any
    transcriber: Any
    logger: Any
    audio: Any  # AudioRecorder
    transcription_worker: Any = None


class TargetBase:
    """Tüm izleme hedeflerinin ortak davranışı.

    Alt sınıflar en azından `run_slot()` uygular ve sınıf nitelikleriyle kimliğini
    bildirir. Zamanlayıcı, dongle gereken hedefler için dongle'ı kiralar ve
    `run_slot(stop_event, seconds)` çağırır.
    """

    #: config.targets içindeki anahtar (build sırasında atanır)
    KEY: str = ""
    #: insan-okur ad
    NAME: str = ""
    #: olay kategorisi
    CATEGORY: Category = Category.TARAMA
    #: dongle'ı özel olarak gerektirir mi (tüm RF hedefleri evet)
    NEEDS_DEVICE: bool = True
    #: "waiting" (frekansta süre ayırır; normal döngüde uzun dwell) |
    #: "opportunistic" (fırsatçı) | "pass" (yalnız TLE geçiş penceresinde — uydu/ISS)
    CLASS: str = "opportunistic"
    #: hedefe özel varsayılan yapılandırma (config DEFAULTS'a kaydedilir)
    DEFAULTS: dict = {}

    def __init__(self, key: str, ctx: TargetContext):
        self.KEY = key
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.sdr = ctx.sdr
        self.st = ctx.storage
        self.dispatcher = ctx.dispatcher
        self.transcriber = ctx.transcriber
        self.audio = ctx.audio
        self.log = ctx.logger.getChild(key) if hasattr(ctx.logger, "getChild") else ctx.logger
        self.conf = self.cfg.target(key)
        self.last_run = 0.0
        self.last_event = 0.0
        self.event_count = 0
        self.error_count = 0
        self._tools_ok: bool | None = None

    # -------------------------------------------------- yapılandırma kaydı
    @classmethod
    def register_defaults(cls, cfg, key: str) -> None:
        cfg.register_target_defaults(key, cls.full_defaults())

    @classmethod
    def full_defaults(cls) -> dict:
        base = {"enabled": True, "priority": 5, "dwell_s": 30, "period_s": 300}
        base.update(cls.DEFAULTS or {})
        return base

    # --------------------------------------------------------- özellikler
    @property
    def enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    @property
    def priority(self) -> int:
        return int(self.conf.get("priority", 5))

    @property
    def dwell_s(self) -> float:
        return float(self.conf.get("dwell_s", 30))

    @property
    def period_s(self) -> float:
        return float(self.conf.get("period_s", 300))

    @property
    def band_label(self) -> str:
        return self.conf.get("band_label", self.NAME)

    def display_name(self) -> str:
        return self.NAME or self.KEY

    def needs_device(self) -> bool:
        return self.NEEDS_DEVICE

    def tools_available(self) -> tuple[bool, str]:
        """Harici araç gereksinimini kontrol eder. (ok, mesaj)."""
        return True, ""

    def check_tools(self) -> bool:
        if self._tools_ok is None:
            ok, msg = self.tools_available()
            self._tools_ok = ok
            if not ok:
                self.log.warning("araç eksik: %s", msg)
        return self._tools_ok

    # --------------------------------------------------- zamanlama girdisi
    def due_in(self, now: float) -> float:
        """Bir sonraki çalışmaya kalan saniye (fırsatçı hedefler için)."""
        return max(0.0, (self.last_run + self.period_s) - now)

    def wants_slot(self, now: float) -> bool:
        return self.enabled and self.due_in(now) <= 0

    # --------------------------------------------------- olay üretimi
    def make_event(self, event_type: str, *, summary: str = "", body: str = "", freq_mhz=None,
                   band: str | None = None, signal: str | None = None, signal_value=None,
                   lat=None, lon=None, location_text=None, priority: int | None = None,
                   duration_s=None, attachments=None, extra=None, dedup_key=None,
                   time_utc: datetime | None = None) -> Event:
        return Event(
            event_type=event_type, category=self.CATEGORY,
            band=band or self.band_label, freq_mhz=freq_mhz, summary=summary, body=body,
            time_utc=time_utc or datetime.now(timezone.utc),
            duration_s=duration_s, signal=signal, signal_value=signal_value,
            lat=lat, lon=lon, location_text=location_text,
            priority=self.priority if priority is None else priority,
            target=self.KEY, attachments=attachments or [], extra=extra or {}, dedup_key=dedup_key,
        )

    def emit(self, ev: Event) -> None:
        self.event_count += 1
        self.last_event = time.time()
        worker = getattr(self.ctx, "transcription_worker", None)
        if worker is not None and ev.needs_transcription:
            worker.submit(ev)
        else:
            self.dispatcher.submit(ev)

    def log_error(self, message: str) -> None:
        self.error_count += 1
        self.log.warning("%s", message)
        try:
            self.st.log_error(self.KEY, message)
        except Exception:
            pass

    # --------------------------------------------- kayıt defteri (yeni cihaz)
    def registry_touch(self, kind: str, key: str, data: dict | None = None):
        return self.st.registry_touch(kind, key, data)

    # --------------------------------------------- araç çalıştırma yardımcısı
    def run_tool_lines(self, cmd: list[str], stop_event: threading.Event, duration_s: float,
                       on_line, *, name: str = "", log_name: str | None = None,
                       on_stderr=None) -> int:
        """Aracı başlatır, süre/iptal olana kadar satırları `on_line`'a iletir."""
        log_path = None
        if log_name:
            log_path = self.cfg.log_dir / f"{log_name}.log"
        deadline = time.time() + duration_s
        attempts = 0
        rc = 0
        while attempts < 2:
            attempts += 1
            proc = ManagedProcess(cmd, name=name or self.KEY, on_line=on_line, on_stderr=on_stderr,
                                  log_path=log_path)
            try:
                self.sdr.wait_ready()
            except Exception:
                pass
            started = time.time()
            try:
                proc.start()
            except Exception as e:
                self.log_error(f"araç başlatılamadı: {e}")
                return 0
            try:
                while time.time() < deadline and not stop_event.is_set():
                    if not proc.running:
                        break
                    time.sleep(0.3)
            finally:
                proc.stop()
                try:
                    self.sdr.mark_released()
                except Exception:
                    pass
            rc = proc.returncode or 0
            early_exit = (time.time() - started) < 4.0 and not stop_event.is_set() and time.time() < deadline
            if early_exit and looks_like_device_error(proc.stderr_tail):
                # dongle henüz bırakılmamış olabilir — kısa bekle, bir kez daha dene
                self.log.debug("%s: dongle meşgul görünüyor, yeniden deneniyor", name or self.KEY)
                time.sleep(1.5)
                continue
            if early_exit and rc not in (0, None):
                tail = " | ".join(list(proc.stderr_tail)[-3:])
                self.log_error(f"{name or self.KEY} erken çıktı (rc={rc}): {tail[:300]}")
            break
        return rc

    # ------------------------------------------------------- çalıştırma
    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        """Hedefi dongle ile `duration_s` saniye çalıştırır. Alt sınıf uygular."""
        raise NotImplementedError

    # ------------------------------------------------ bekleme-hedefi pencereleri
    def next_window(self, now: float):
        """'waiting' hedefleri için bir sonraki zamanlanmış pencere (başlangıç, bitiş) ya da None."""
        return None



def audio_attachment(path: str, caption: str | None = None, delete_after: bool = False) -> Attachment:
    """Dosya uzantısına göre doğru Telegram ek türünü seçer.

    Telegram sendVoice yalnızca OGG/OPUS (veya MP3/M4A) kabul eder; WAV için
    sendDocument kullanılmalıdır, aksi halde gönderim reddedilir."""
    p = str(path).lower()
    if p.endswith((".ogg", ".oga", ".opus")):
        kind = "voice"
    elif p.endswith((".mp3", ".m4a")):
        kind = "audio"
    else:
        kind = "document"
    return Attachment(kind, str(path), caption=caption, delete_after=delete_after)


class SlotCollector:
    """Bir slot boyunca biriken ögeleri tek özet mesajında (sel koruması) toplar.

    Yoğun ortamlarda (havalimanı yakını ADS-B, Marmara AIS, şehir içi ISM) her
    tespit için ayrı mesaj göndermek topic'i boğar. Bunun yerine hedef, slot
    boyunca `add()` ile öge biriktirir; `flush()` öge sayısı `individual_max`
    altındaysa ayrı olaylar, üstündeyse tek özet olay üretir."""

    def __init__(self, target: "TargetBase", title: str, *, individual_max: int = 3, list_max: int = 15):
        self.target = target
        self.title = title
        self.individual_max = individual_max
        self.list_max = list_max
        self.items: list[dict] = []   # {"line": str, "event": Event|None, "sort": float}

    def add(self, line: str, event: Event | None = None, sort_key: float = 0.0) -> None:
        self.items.append({"line": line, "event": event, "sort": sort_key})

    def __len__(self) -> int:
        return len(self.items)

    def flush(self, *, freq_mhz=None, band: str | None = None, summary_prefix: str = "",
              extra_body: str = "", priority: int | None = None, always_summary: bool = False) -> int:
        if not self.items:
            return 0
        n = len(self.items)
        if n <= self.individual_max and not always_summary:
            sent = 0
            for it in self.items:
                if it["event"] is not None:
                    self.target.emit(it["event"])
                    sent += 1
            if sent:
                self.items.clear()
                return sent
        items = sorted(self.items, key=lambda x: -x["sort"])
        lines = [it["line"] for it in items[: self.list_max]]
        more = n - len(lines)
        body = "\n".join(lines)
        if more > 0:
            body += f"\n… ve {more} öge daha"
        if extra_body:
            body = extra_body + "\n\n" + body
        ev = self.target.make_event(
            self.title, summary=f"{summary_prefix}{n} öge",
            body=body, freq_mhz=freq_mhz, band=band,
            priority=self.target.priority if priority is None else priority)
        self.target.emit(ev)
        self.items.clear()
        return 1
