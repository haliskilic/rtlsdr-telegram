"""Ortak olay (Event) veri modeli ve Telegram mesaj biçimlendirme.

Tüm hedefler bu modeli üretir; Dispatcher aynı modeli HTML mesajına çevirir.
Başlık şablonu (madde 5):

  [EMOJİ] [OLAY TÜRÜ] • [KATEGORİ]
  ├ Frekans aralığı : ...
  ├ Yakalanan frekans: ...
  ├ Zaman           : ...
  ├ Süre            : ...
  ├ Sinyal gücü     : ...
  ├ Konum           : ...
  └ Özet            : ...
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from .geo import format_location


class Category(str, Enum):
    HAVACILIK = "Havacılık"
    DENIZCILIK = "Denizcilik"
    UYDU = "Uydu"
    METEOROLOJI = "Meteoroloji"
    AMATOR = "Amatör Telsiz"
    ISM = "ISM/Sensör"
    ACIL = "Acil Durum"
    HUCRESEL = "Hücresel"
    TARAMA = "Genel Tarama"
    SISTEM = "Sistem"

    @classmethod
    def parse(cls, text: str) -> "Category | None":
        t = (text or "").strip().lower().replace("_", " ").replace("-", " ")
        aliases = {
            "havacilik": cls.HAVACILIK, "havacılık": cls.HAVACILIK, "ucak": cls.HAVACILIK, "uçak": cls.HAVACILIK,
            "denizcilik": cls.DENIZCILIK, "deniz": cls.DENIZCILIK, "gemi": cls.DENIZCILIK,
            "uydu": cls.UYDU, "meteoroloji": cls.METEOROLOJI, "balon": cls.METEOROLOJI,
            "amator": cls.AMATOR, "amatör": cls.AMATOR, "amator telsiz": cls.AMATOR, "amatör telsiz": cls.AMATOR,
            "ism": cls.ISM, "sensor": cls.ISM, "sensör": cls.ISM, "ism/sensor": cls.ISM, "ism/sensör": cls.ISM,
            "acil": cls.ACIL, "acil durum": cls.ACIL, "hucresel": cls.HUCRESEL, "hücresel": cls.HUCRESEL, "gsm": cls.HUCRESEL,
            "tarama": cls.TARAMA, "genel tarama": cls.TARAMA, "spektrum": cls.TARAMA, "sistem": cls.SISTEM,
        }
        return aliases.get(t)


CATEGORY_EMOJI = {
    Category.HAVACILIK: "✈️",
    Category.DENIZCILIK: "🚢",
    Category.UYDU: "🛰️",
    Category.METEOROLOJI: "🎈",
    Category.AMATOR: "📻",
    Category.ISM: "📡",
    Category.ACIL: "🚨",
    Category.HUCRESEL: "📶",
    Category.TARAMA: "🔭",
    Category.SISTEM: "⚙️",
}

# Öncelik sabitleri (küçük = önce gönderilir)
PRIO_EMERGENCY = 0
PRIO_HIGH = 1
PRIO_IMPORTANT = 2
PRIO_NORMAL = 5
PRIO_LOW = 7


def esc(text: Any) -> str:
    """Telegram HTML için kaçış."""
    return html.escape("" if text is None else str(text), quote=False)


def fmt_freq(freq_mhz: float | None) -> str:
    """Frekansı MHz olarak biçimler (uygulama boyunca MHz tutarlı). En az 3 ondalık."""
    if freq_mhz is None:
        return "—"
    s = f"{freq_mhz:.4f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    whole, _, frac = s.partition(".")
    frac = (frac + "000")[:max(3, len(frac))]
    return f"{whole}.{frac} MHz"


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.0f} sn" if seconds >= 10 else f"{seconds:.1f} sn"
    m, s = divmod(int(round(seconds)), 60)
    if m < 60:
        return f"{m} dk {s:02d} sn"
    h, m = divmod(m, 60)
    return f"{h} sa {m:02d} dk"


def fmt_time(dt: datetime, tz: ZoneInfo) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(tz)
    off = local.strftime("%z")
    off = f"{off[:3]}:{off[3:]}" if off else ""
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} ({off}) / {dt.astimezone(timezone.utc).strftime('%H:%M:%S')} UTC"


@dataclass
class Attachment:
    kind: str                 # voice | audio | photo | document
    path: str
    caption: str | None = None
    delete_after: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event:
    event_type: str
    category: Category
    band: str = "—"
    freq_mhz: float | None = None
    summary: str = ""
    body: str = ""                     # HTML (dinamik alanlar esc() ile kaçışlanmış olmalı)
    time_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_s: float | None = None
    signal: str | None = None          # biçimlenmiş metin ("-32.1 dBFS (SNR 18 dB)")
    signal_value: float | None = None  # sıralama için sayısal değer (dB)
    lat: float | None = None
    lon: float | None = None
    location_text: str | None = None
    priority: int = PRIO_NORMAL
    target: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    transcript: str | None = None
    transcript_lang: str | None = None
    transcript_status: str = "none"   # none | pending | done | failed | empty
    transcription_language: str | None = None   # hedefe özel dil zorlaması (tr/en)
    transcription_prompt: str | None = None
    reply_to: dict | None = None       # {"chat_id":..,"message_thread_id":..,"message_id":..}
    extra: dict = field(default_factory=dict)
    dedup_key: str | None = None
    db_id: int | None = None
    silent: bool | None = None

    # ----- biçimlendirme -----
    @property
    def emoji(self) -> str:
        return CATEGORY_EMOJI.get(self.category, "•")

    def first_line_summary(self, limit: int = 160) -> str:
        text = self.summary or ""
        if self.transcript and self.transcript_status == "done":
            text = self.transcript.strip().splitlines()[0] if self.transcript.strip() else text
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def header_html(self, tz: ZoneInfo, station_lat: float | None, station_lon: float | None) -> str:
        loc = self.location_text or format_location(self.lat, self.lon, station_lat, station_lon)
        lines = [
            f"{self.emoji} <b>{esc(self.event_type)}</b> • <b>{esc(self.category.value)}</b>",
            f"├ Frekans aralığı : {esc(self.band or '—')}",
            f"├ Yakalanan frekans: {esc(fmt_freq(self.freq_mhz))}",
            f"├ Zaman           : {esc(fmt_time(self.time_utc, tz))}",
            f"├ Süre            : {esc(fmt_duration(self.duration_s))}",
            f"├ Sinyal gücü     : {esc(self.signal or '—')}",
            f"├ Konum           : {esc(loc)}",
            f"└ Özet            : {esc(self.first_line_summary() or '—')}",
        ]
        return "\n".join(lines)

    def body_html(self) -> str:
        parts = []
        if self.body:
            parts.append(self.body)
        if self.transcript_status == "done" and self.transcript:
            lang = f" ({esc(self.transcript_lang)})" if self.transcript_lang else ""
            parts.append(f"📝 <b>Transkripsiyon</b>{lang}:\n<i>{esc(self.transcript.strip())}</i>")
        elif self.transcript_status in ("failed", "empty"):
            parts.append("📝 <i>Ses alındı, metin çıkarılamadı.</i>")
        return "\n\n".join(parts)

    def to_html(self, tz: ZoneInfo, station_lat: float | None, station_lon: float | None) -> str:
        header = self.header_html(tz, station_lat, station_lon)
        body = self.body_html()
        return header + ("\n\n" + body if body else "")

    # ----- serileştirme -----
    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        d["time_utc"] = self.time_utc.isoformat()
        d["attachments"] = [a.to_dict() for a in self.attachments]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        d = dict(d)
        d["category"] = Category(d["category"])
        d["time_utc"] = datetime.fromisoformat(d["time_utc"])
        d["attachments"] = [Attachment(**a) for a in d.get("attachments", [])]
        return cls(**d)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "Event":
        return cls.from_dict(json.loads(s))

    @property
    def has_photos(self) -> int:
        return sum(1 for a in self.attachments if a.kind == "photo")

    @property
    def needs_transcription(self) -> bool:
        return self.transcript_status == "pending" and any(a.kind in ("voice", "audio") for a in self.attachments)
