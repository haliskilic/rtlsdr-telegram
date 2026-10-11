"""Target base class and shared context."""
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
from ..i18n import t
from ..proc import ManagedProcess, looks_like_device_error


@dataclass
class TargetContext:
    """Shared dependencies injected into every target."""
    cfg: Any
    sdr: Any
    storage: Any
    dispatcher: Any
    transcriber: Any
    logger: Any
    audio: Any  # AudioRecorder
    transcription_worker: Any = None


class TargetBase:
    """Common behaviour of all monitoring targets.

    Subclasses implement at least `run_slot()` and describe themselves with class
    attributes. The scheduler leases the dongle for targets that need it and
    calls `run_slot(stop_event, seconds)`.
    """

    #: key inside config.targets (assigned at build time)
    KEY: str = ""
    #: human-readable name (literal) or NAME_KEY (i18n key, preferred)
    NAME: str = ""
    NAME_KEY: str = ""
    BAND_KEY: str = ""
    #: olay kategorisi
    CATEGORY: Category = Category.TARAMA
    #: needs exclusive access to the dongle (all RF targets do)
    NEEDS_DEVICE: bool = True
    #: "waiting" (needs dwell time on its frequency; long dwell in the normal cycle) |
    #: "opportunistic" | "pass" (only inside a TLE pass window — satellites/ISS)
    CLASS: str = "opportunistic"
    #: target-specific default configuration (registered into config DEFAULTS)
    DEFAULTS: dict = {}
    #: 'pass' targets: the scheduler leaves the target alone until this timestamp
    #: (retry back-off after a failed start, or "done" until the window ends)
    pass_retry_after: float = 0.0

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

    # -------------------------------------------------- configuration registration
    @classmethod
    def register_defaults(cls, cfg, key: str) -> None:
        cfg.register_target_defaults(key, cls.full_defaults())

    @classmethod
    def full_defaults(cls) -> dict:
        base = {"enabled": True, "priority": 5, "dwell_s": 30, "period_s": 300}
        base.update(cls.DEFAULTS or {})
        return base

    # --------------------------------------------------------- properties
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
        if self.conf.get("band_label"):
            return self.conf["band_label"]
        return t(self.BAND_KEY) if self.BAND_KEY else self.display_name()

    def display_name(self) -> str:
        if self.NAME_KEY:
            return t(self.NAME_KEY)
        return self.NAME or self.KEY

    def needs_device(self) -> bool:
        return self.NEEDS_DEVICE

    def tools_available(self) -> tuple[bool, str]:
        """Check external tool requirements; returns (ok, message)."""
        return True, ""

    def check_tools(self) -> bool:
        if self._tools_ok is None:
            ok, msg = self.tools_available()
            self._tools_ok = ok
            if not ok:
                self.log.warning("tool missing: %s", msg)
        return self._tools_ok

    # --------------------------------------------------- zamanlama girdisi
    def due_in(self, now: float) -> float:
        """Seconds until the next run (for cycle targets)."""
        return max(0.0, (self.last_run + self.period_s) - now)

    def wants_slot(self, now: float) -> bool:
        return self.enabled and self.due_in(now) <= 0

    # --------------------------------------------------- event production
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

    # --------------------------------------------- registry (new device detection)
    def registry_touch(self, kind: str, key: str, data: dict | None = None):
        return self.st.registry_touch(kind, key, data)

    # --------------------------------------------- tool runner helper
    def run_tool_lines(self, cmd: list[str], stop_event: threading.Event, duration_s: float,
                       on_line, *, name: str = "", log_name: str | None = None,
                       on_stderr=None) -> int:
        """Start the tool and forward output lines to `on_line` until the deadline or a stop."""
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
                self.log_error(f"tool failed to start: {e}")
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
                # the dongle may not be released yet — wait briefly and retry once
                self.log.debug("%s: dongle looks busy, retrying", name or self.KEY)
                time.sleep(1.5)
                continue
            if early_exit and rc not in (0, None):
                tail = " | ".join(list(proc.stderr_tail)[-3:])
                self.log_error(f"{name or self.KEY} exited early (rc={rc}): {tail[:300]}")
            break
        return rc

    # ------------------------------------------------------- run
    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        """Run the target with the dongle for `duration_s` seconds (implemented by subclasses)."""
        raise NotImplementedError

    # ------------------------------------------------ pass windows
    def next_window(self, now: float):
        """Next scheduled window (start, end) for 'pass' targets, else None."""
        return None

    def pass_retry_in(self, seconds: float) -> None:
        """'pass' targets: give the dongle back to the cycle and try again after `seconds`."""
        self.pass_retry_after = time.time() + float(seconds)

    def pass_done_until(self, until_ts: float) -> None:
        """'pass' targets: nothing more to do in this window (success or final failure)."""
        self.pass_retry_after = float(until_ts) + 1.0



def audio_attachment(path: str, caption: str | None = None, delete_after: bool = False) -> Attachment:
    """Pick the right Telegram attachment kind from the file extension.

    Telegram sendVoice only accepts OGG/OPUS (or MP3/M4A); WAV must go through
    sendDocument or the upload is rejected."""
    p = str(path).lower()
    if p.endswith((".ogg", ".oga", ".opus")):
        kind = "voice"
    elif p.endswith((".mp3", ".m4a")):
        kind = "audio"
    else:
        kind = "document"
    return Attachment(kind, str(path), caption=caption, delete_after=delete_after)


class SlotCollector:
    """Collects items during a slot and flushes them as one summary (flood control).

    In dense environments (ADS-B near an airport, AIS in busy waters, urban ISM)
    one message per detection would flood the topic. Targets `add()` items during
    the slot; `flush()` emits individual events when the count is within
    `individual_max`, otherwise a single summary event."""

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
            body += "\n" + t("common.more_items", n=more)
        if extra_body:
            body = extra_body + "\n\n" + body
        ev = self.target.make_event(
            self.title, summary=f"{summary_prefix}{t('common.items', n=n)}",
            body=body, freq_mhz=freq_mhz, band=band,
            priority=self.target.priority if priority is None else priority)
        self.target.emit(ev)
        self.items.clear()
        return 1
