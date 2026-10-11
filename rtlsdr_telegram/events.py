"""Common event (Event) data model and Telegram message formatting.

Every target produces this model; the Dispatcher turns it into an HTML message.
Header template (spec section 5), labels localized through i18n:

  [EMOJI] [EVENT TYPE] • [CATEGORY]
  ├ Band      : ...
  ├ Frequency : ...
  ├ Time      : ...
  ├ Duration  : ...
  ├ Signal    : ...
  ├ Location  : ...
  └ Summary   : ...

Category values are language-neutral keys (stored in the database); their
display names come from i18n so the language can be switched at any time.
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
from .i18n import t


class Category(str, Enum):
    HAVACILIK = "aviation"
    DENIZCILIK = "maritime"
    UYDU = "satellite"
    METEOROLOJI = "weather"
    AMATOR = "amateur"
    ISM = "ism"
    ACIL = "emergency"
    HUCRESEL = "cellular"
    TARAMA = "scan"
    SISTEM = "system"

    @property
    def label(self) -> str:
        """Localized display name."""
        return t(f"cat.{self.value}")

    @classmethod
    def parse(cls, text: str) -> "Category | None":
        """Accept keys, English and Turkish names and common aliases."""
        raw = (text or "").strip().lower().replace("_", " ").replace("-", " ")
        if not raw:
            return None
        for c in cls:
            if raw == c.value or raw == c.label.lower() or raw == t_en(f"cat.{c.value}").lower() \
                    or raw == LEGACY_TR_NAMES.get(c, "").lower():
                return c
        aliases = {
            "havacilik": cls.HAVACILIK, "ucak": cls.HAVACILIK, "uçak": cls.HAVACILIK, "aircraft": cls.HAVACILIK,
            "air": cls.HAVACILIK, "deniz": cls.DENIZCILIK, "gemi": cls.DENIZCILIK, "marine": cls.DENIZCILIK,
            "ship": cls.DENIZCILIK, "sat": cls.UYDU, "space": cls.UYDU, "balon": cls.METEOROLOJI,
            "meteo": cls.METEOROLOJI, "weather": cls.METEOROLOJI, "amator": cls.AMATOR, "amatör": cls.AMATOR,
            "amator telsiz": cls.AMATOR, "amatör telsiz": cls.AMATOR, "ham": cls.AMATOR, "sensor": cls.ISM,
            "sensör": cls.ISM, "sensors": cls.ISM, "ism/sensor": cls.ISM, "ism/sensör": cls.ISM,
            "ism/sensors": cls.ISM, "acil": cls.ACIL, "acil durum": cls.ACIL, "hucresel": cls.HUCRESEL,
            "hücresel": cls.HUCRESEL, "gsm": cls.HUCRESEL, "cell": cls.HUCRESEL, "tarama": cls.TARAMA,
            "genel tarama": cls.TARAMA, "spektrum": cls.TARAMA, "spectrum": cls.TARAMA, "general scan": cls.TARAMA,
            "sistem": cls.SISTEM,
        }
        return aliases.get(raw)


def t_en(key: str) -> str:
    from .i18n import EN
    return EN.get(key, key)


# Legacy Turkish category names written to the database by early versions.
LEGACY_TR_NAMES = {
    Category.HAVACILIK: "Havacılık", Category.DENIZCILIK: "Denizcilik", Category.UYDU: "Uydu",
    Category.METEOROLOJI: "Meteoroloji", Category.AMATOR: "Amatör Telsiz", Category.ISM: "ISM/Sensör",
    Category.ACIL: "Acil Durum", Category.HUCRESEL: "Hücresel", Category.TARAMA: "Genel Tarama",
    Category.SISTEM: "Sistem",
}
LEGACY_TR_TO_KEY = {v: k.value for k, v in LEGACY_TR_NAMES.items()}

CATEGORY_EMOJI = {
    Category.HAVACILIK: "✈️", Category.DENIZCILIK: "🚢", Category.UYDU: "🛰️", Category.METEOROLOJI: "🎈",
    Category.AMATOR: "📻", Category.ISM: "📡", Category.ACIL: "🚨", Category.HUCRESEL: "📶",
    Category.TARAMA: "🔭", Category.SISTEM: "⚙️",
}

# Priority constants (lower = sent first)
PRIO_EMERGENCY = 0
PRIO_HIGH = 1
PRIO_IMPORTANT = 2
PRIO_NORMAL = 5
PRIO_LOW = 7


def esc(text: Any) -> str:
    """Escape for Telegram HTML."""
    return html.escape("" if text is None else str(text), quote=False)


def fmt_freq(freq_mhz: float | None) -> str:
    """Format a frequency in MHz with at least 3 decimals (131.725 MHz)."""
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
    u_s, u_m, u_h = t("unit.s"), t("unit.min"), t("unit.h")
    if seconds < 60:
        return f"{seconds:.0f} {u_s}" if seconds >= 10 else f"{seconds:.1f} {u_s}"
    m, s = divmod(int(round(seconds)), 60)
    if m < 60:
        return f"{m} {u_m} {s:02d} {u_s}"
    h, m = divmod(m, 60)
    return f"{h} {u_h} {m:02d} {u_m}"


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
    body: str = ""                     # HTML (dynamic values must be escaped with esc())
    time_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_s: float | None = None
    signal: str | None = None          # formatted text ("-32.1 dBFS (SNR 18 dB)")
    signal_value: float | None = None  # numeric value for ranking (dB)
    lat: float | None = None
    lon: float | None = None
    location_text: str | None = None
    priority: int = PRIO_NORMAL
    target: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    transcript: str | None = None
    transcript_lang: str | None = None
    transcript_status: str = "none"   # none | pending | done | failed | empty
    transcription_language: str | None = None   # per-target forced language (tr/en)
    transcription_prompt: str | None = None
    reply_to: dict | None = None       # {"chat_id":..,"message_thread_id":..,"message_id":..}
    extra: dict = field(default_factory=dict)
    dedup_key: str | None = None
    db_id: int | None = None
    silent: bool | None = None

    # ----- formatting -----
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
        rows = [
            (t("hdr.band"), self.band or "—"),
            (t("hdr.freq"), fmt_freq(self.freq_mhz)),
            (t("hdr.time"), fmt_time(self.time_utc, tz)),
            (t("hdr.duration"), fmt_duration(self.duration_s)),
            (t("hdr.signal"), self.signal or "—"),
            (t("hdr.location"), loc),
            (t("hdr.summary"), self.first_line_summary() or "—"),
        ]
        width = max(len(label) for label, _ in rows)
        lines = [f"{self.emoji} <b>{esc(self.event_type)}</b> • <b>{esc(self.category.label)}</b>"]
        for i, (label, value) in enumerate(rows):
            branch = "└" if i == len(rows) - 1 else "├"
            lines.append(f"{branch} {esc(label.ljust(width))} : {esc(value)}")
        return "\n".join(lines)

    def body_html(self) -> str:
        parts = []
        if self.body:
            parts.append(self.body)
        if self.transcript_status == "done" and self.transcript:
            lang = f" ({esc(self.transcript_lang)})" if self.transcript_lang else ""
            parts.append(f"📝 <b>{esc(t('body.transcript'))}</b>{lang}:\n<i>{esc(self.transcript.strip())}</i>")
        elif self.transcript_status in ("failed", "empty"):
            parts.append(f"📝 <i>{esc(t('body.transcript_failed'))}</i>")
        return "\n\n".join(parts)

    def to_html(self, tz: ZoneInfo, station_lat: float | None, station_lon: float | None) -> str:
        header = self.header_html(tz, station_lat, station_lon)
        body = self.body_html()
        return header + ("\n\n" + body if body else "")

    # ----- serialization -----
    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        d["time_utc"] = self.time_utc.isoformat()
        d["attachments"] = [a.to_dict() for a in self.attachments]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        d = dict(d)
        cat = d["category"]
        d["category"] = Category(LEGACY_TR_TO_KEY.get(cat, cat))
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
