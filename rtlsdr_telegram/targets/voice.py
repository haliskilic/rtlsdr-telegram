"""Hedef 9–12 — Ses kaydı üreten bantlar (eşik tetiklemeli).

Ortak taban (VoiceTargetBase): yapılandırılmış kanal listesini dwell süresi
boyunca dönüşümlü dinler; her kanalda AudioRecorder ile VOX (ses varlığı)
tetiklemeli kayıt yapar. Yayın bitince (sessizlik) segment kapanır, ogg/opus'a
çevrilir, olay olarak gönderilir ve otomatik yazıya dökülür (madde 4).

  9. AmateurVoiceTarget — 144–146 ve 430–440 MHz (röle/simpleks), FM, squelch.
 10. AirbandTarget       — 118–137 MHz, AM (kule/yaklaşma/ATIS).
 11. MarineVoiceTarget    — 156–162 MHz, FM (özellikle Kanal 16 156.800).
 12. CBPMRTarget          — 26–28 MHz ve 446 MHz, FM.

rtl_fm'i doğrudan kullanır (hafif, güvenilir); demodülasyon + squelch bizim
AudioRecorder VOX mantığımızla yapılır, böylece kayıt sınırları net olur.
"""
from __future__ import annotations

import threading
import time
from datetime import timezone

from ..events import Category, Attachment, PRIO_IMPORTANT, PRIO_NORMAL
from ..channel_maps import channel_name, describe
from .base import TargetBase


class VoiceTargetBase(TargetBase):
    MODE = "fm"
    MAP_HINT: str | None = None  # channel_maps ipucu

    def tools_available(self):
        if not self.sdr.bin_rtl_fm:
            return False, "rtl_fm yok"
        if not self.cfg.which(self.cfg.get("audio.ffmpeg", "ffmpeg")):
            return True, "(ffmpeg yok — WAV olarak gönderilecek)"
        return True, ""

    def channels(self) -> list[dict]:
        """[{freq_mhz, name?}] listesi döndürür (config.channels)."""
        chans = self.conf.get("channels", [])
        out = []
        for c in chans:
            if isinstance(c, (int, float)):
                out.append({"freq_mhz": float(c)})
            elif isinstance(c, dict) and "freq_mhz" in c:
                out.append(c)
        return out

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        chans = self.channels()
        if not chans:
            self.log.debug("%s: kanal tanımlı değil", self.KEY)
            return
        # skip kara liste
        chans = [c for c in chans if not self.cfg.is_blacklisted(c["freq_mhz"])]
        if not chans:
            return
        per = max(self.conf.get("min_channel_s", 8), duration_s / len(chans))
        end = time.time() + duration_s
        idx = 0
        while time.time() < end and not stop_event.is_set():
            c = chans[idx % len(chans)]
            idx += 1
            remain = end - time.time()
            if remain <= 1:
                break
            self._listen_channel(c, min(per, remain), stop_event)
            if len(chans) == 1:
                # tek kanal: dwell boyunca sürekli dinle (zaten record_window pencere kadar sürer)
                continue

    def _listen_channel(self, chan: dict, secs: float, stop_event):
        freq_mhz = chan["freq_mhz"]
        freq_hz = int(round(freq_mhz * 1e6))
        cname = chan.get("name") or channel_name(freq_mhz, self.MAP_HINT)
        thr = float(self.conf.get("threshold_dbfs", -42.0))
        segs = self.audio.record_window(
            freq_hz, secs, stop_event, mode=self.MODE,
            audio_rate=int(self.conf.get("audio_rate", 16000)),
            threshold_dbfs=thr, hangover_s=float(self.conf.get("hangover_s", 1.5)),
            min_segment_s=float(self.conf.get("min_segment_s", 0.8)),
            max_segment_s=float(self.conf.get("max_segment_s", 120)),
            gain=self.conf.get("gain", "auto"), squelch=int(self.conf.get("squelch", 0)),
            channel=cname, prefix=self.KEY,
            require_dynamics=bool(self.conf.get("require_dynamics", True)),
            min_dynamics_db=float(self.conf.get("min_dynamics_db", 2.5)))
        for seg in segs:
            self._emit_segment(seg, freq_mhz, cname)

    def _emit_segment(self, seg, freq_mhz, cname):
        band = describe(freq_mhz, self.MAP_HINT)
        rec_id = self.st.add_recording(seg.start_utc.timestamp(), self.KEY, freq_mhz, cname,
                                       seg.duration_s, seg.final_path,
                                       f"{seg.peak_dbfs:.1f} dBFS", None)
        is_priority = self._is_priority(freq_mhz, cname)
        kind = "voice"
        caption = f"{band}"
        att = Attachment(kind, seg.final_path, caption=caption)
        body = [f"Kanal      : {cname or '—'}",
                f"Tepe seviye: {seg.peak_dbfs:.1f} dBFS  (ort. {seg.mean_dbfs:.1f})"]
        ev = self.make_event(
            self.EVENT_TYPE, summary=f"{band} — {seg.duration_s:.0f} sn yayın",
            body="\n".join(body), freq_mhz=freq_mhz, band=band,
            signal=f"{seg.peak_dbfs:.1f} dBFS (tepe)", signal_value=seg.peak_dbfs,
            duration_s=seg.duration_s, attachments=[att],
            priority=PRIO_IMPORTANT if is_priority else self.priority,
            time_utc=seg.start_utc)
        # transkripsiyon iste
        ev.transcript_status = "pending"
        ev.transcription_language = self.conf.get("transcribe_language")
        ev.extra["recording_id"] = rec_id
        self.emit(ev)

    def _is_priority(self, freq_mhz, cname) -> bool:
        return False

    EVENT_TYPE = "Ses Yayını"


class AmateurVoiceTarget(VoiceTargetBase):
    NAME = "Amatör Telsiz Ses"
    EVENT_TYPE = "Amatör Telsiz Ses"
    CATEGORY = Category.AMATOR
    MODE = "fm"
    MAP_HINT = "amateur"
    DEFAULTS = {
        "enabled": True, "priority": 5, "dwell_s": 90, "period_s": 300,
        "channels": [
            {"freq_mhz": 145.500, "name": "2m çağrı simpleks"},
            {"freq_mhz": 145.675, "name": "Röle çıkışı"},
            {"freq_mhz": 433.500, "name": "70cm çağrı simpleks"},
            {"freq_mhz": 439.000, "name": "Röle çıkışı"},
        ],
        "threshold_dbfs": -42.0, "hangover_s": 1.5, "gain": "auto",
        "band_label": "144–146 / 430–440 MHz amatör", "transcribe_language": "tr",
    }


class AirbandTarget(VoiceTargetBase):
    NAME = "Hava Bandı Ses"
    EVENT_TYPE = "Hava Bandı Ses"
    CATEGORY = Category.HAVACILIK
    MODE = "am"
    MAP_HINT = "air"
    DEFAULTS = {
        "enabled": True, "priority": 4, "dwell_s": 90, "period_s": 240,
        "channels": [
            {"freq_mhz": 118.100, "name": "Kule (örnek)"},
            {"freq_mhz": 121.500, "name": "Acil (Guard)"},
        ],
        "threshold_dbfs": -38.0, "hangover_s": 1.2, "gain": 40,
        "band_label": "118–137 MHz hava bandı (AM)", "transcribe_language": "en",
    }

    def _is_priority(self, freq_mhz, cname) -> bool:
        return abs(freq_mhz - 121.5) < 0.01


class MarineVoiceTarget(VoiceTargetBase):
    NAME = "Deniz VHF Ses"
    EVENT_TYPE = "Deniz VHF Ses"
    CATEGORY = Category.DENIZCILIK
    MODE = "fm"
    MAP_HINT = "marine"
    DEFAULTS = {
        "enabled": True, "priority": 4, "dwell_s": 90, "period_s": 240,
        "channels": [
            {"freq_mhz": 156.800, "name": "Kanal 16 (Acil/Çağrı)"},
            {"freq_mhz": 156.650, "name": "Kanal 13 (Köprü-köprü)"},
            {"freq_mhz": 156.600, "name": "Kanal 12 (Liman/VTS)"},
        ],
        "threshold_dbfs": -40.0, "hangover_s": 1.5, "gain": "auto",
        "band_label": "156–162 MHz deniz VHF", "transcribe_language": "tr",
    }

    def _is_priority(self, freq_mhz, cname) -> bool:
        return abs(freq_mhz - 156.8) < 0.01


class CBPMRTarget(VoiceTargetBase):
    NAME = "CB / PMR446 Ses"
    EVENT_TYPE = "CB/PMR446 Ses"
    CATEGORY = Category.AMATOR
    MODE = "fm"
    MAP_HINT = None
    DEFAULTS = {
        "enabled": True, "priority": 6, "dwell_s": 60, "period_s": 360,
        "channels": [
            {"freq_mhz": 27.185, "name": "CB Kanal 19 (Karayolu)"},
            {"freq_mhz": 27.065, "name": "CB Kanal 9 (Acil)"},
            {"freq_mhz": 446.00625, "name": "PMR Kanal 1"},
            {"freq_mhz": 446.09375, "name": "PMR Kanal 8"},
        ],
        "threshold_dbfs": -42.0, "hangover_s": 1.5, "gain": "auto",
        "band_label": "26–28 MHz CB / 446 MHz PMR", "transcribe_language": "tr",
    }

    def _listen_channel(self, chan, secs, stop_event):
        # CB/PMR karışık; kanal adını her iki tablodan çöz
        hint = "cb" if chan["freq_mhz"] < 30 else "pmr"
        self.MAP_HINT = hint
        super()._listen_channel(chan, secs, stop_event)
