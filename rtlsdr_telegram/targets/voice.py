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
from .base import TargetBase, audio_attachment


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
        end = time.time() + duration_s
        # 1) Bant taraması (şartname: 144–146 / 430–440 / 118–137 / 156–162 MHz).
        #    rtl_power ile hızlı süpürme; taban gürültüsünün üstündeki aktif kanallar
        #    öne alınır. Sabit kanal listesi (channels) her zaman korunur.
        active = []
        ranges = self.conf.get("scan_ranges") or []
        if ranges and self.sdr.bin_rtl_power and not stop_event.is_set():
            active = self._scan_active(ranges, stop_event, budget_s=min(20.0, duration_s * 0.25))
        fixed = [c for c in self.channels() if not self.cfg.is_blacklisted(c["freq_mhz"])]
        seen = set()
        chans = []
        for c in active + fixed:
            k = round(c["freq_mhz"], 4)
            if k in seen:
                continue
            seen.add(k)
            chans.append(c)
        if not chans:
            self.log.debug("%s: dinlenecek kanal yok", self.KEY)
            return
        remain_total = max(1.0, end - time.time())
        per = max(float(self.conf.get("min_channel_s", 8)), remain_total / len(chans))
        idx = 0
        while time.time() < end and not stop_event.is_set():
            c = chans[idx % len(chans)]
            idx += 1
            remain = end - time.time()
            if remain <= 1:
                break
            self._listen_channel(c, min(per, remain), stop_event)

    def _scan_active(self, ranges, stop_event, budget_s: float) -> list[dict]:
        """rtl_power ile verilen aralıkları süpürüp aktif kanalları döndürür."""
        thr = float(self.conf.get("scan_threshold_db", 10.0))
        max_ch = int(self.conf.get("scan_max_channels", 3))
        found: list[tuple[float, float]] = []
        per_range = budget_s / max(1, len(ranges))
        for r in ranges:
            if stop_event.is_set():
                break
            try:
                a, b = float(r["start_mhz"]), float(r["end_mhz"])
                step = int(float(r.get("step_khz", 12.5)) * 1000)
            except (KeyError, TypeError, ValueError):
                continue
            rows: list[tuple[float, float]] = []

            def on_line(line, rows=rows):
                parts = [x.strip() for x in line.split(",")]
                if len(parts) < 7:
                    return
                try:
                    f0 = float(parts[2]); st = float(parts[4])
                    vals = [float(x) for x in parts[6:] if x not in ("", "nan", "-inf")]
                except ValueError:
                    return
                rows.extend((f0 + i * st, v) for i, v in enumerate(vals))
            try:
                proc = self.sdr.power_scan(int(a * 1e6), int(b * 1e6), step, integration="1",
                                           gain=self.conf.get("gain", "auto"), oneshot=True,
                                           log_path=self.cfg.log_dir / f"{self.KEY}_scan.log")
            except Exception as e:
                self.log.debug("bant taraması kurulamadı: %s", e)
                continue
            proc.on_line = on_line
            t0 = time.time()
            try:
                proc.start()
                while proc.running and time.time() - t0 < per_range and not stop_event.is_set():
                    stop_event.wait(0.3)
            finally:
                proc.stop()
                try:
                    self.sdr.mark_released()
                except Exception:
                    pass
            if not rows:
                continue
            vals = sorted(v for _, v in rows)
            floor = vals[len(vals) // 2]
            for f_hz, v in rows:
                f_mhz = f_hz / 1e6
                if v - floor >= thr and not self.cfg.is_blacklisted(f_mhz):
                    found.append((f_mhz, v - floor))
        if not found:
            return []
        found.sort(key=lambda x: -x[1])
        out: list[dict] = []
        used: list[float] = []
        for f_mhz, snr in found:
            key = round(f_mhz, 3)
            if any(abs(key - u) < 0.02 for u in used):
                continue
            used.append(key)
            out.append({"freq_mhz": key,
                        "name": channel_name(key, self.MAP_HINT) or f"taramada aktif (+{snr:.0f} dB)"})
            if len(out) >= max_ch:
                break
        if out:
            self.log.info("%s bant taraması: aktif %s", self.KEY,
                          ", ".join(f"{c['freq_mhz']:.3f}" for c in out))
        return out

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
        att = audio_attachment(seg.final_path, caption=band)
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
        "scan_ranges": [
            {"start_mhz": 144.0, "end_mhz": 146.0, "step_khz": 12.5},
            {"start_mhz": 430.0, "end_mhz": 440.0, "step_khz": 12.5},
        ],
        "scan_threshold_db": 10.0, "scan_max_channels": 3,
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
        "scan_ranges": [{"start_mhz": 118.0, "end_mhz": 137.0, "step_khz": 25}],
        "scan_threshold_db": 10.0, "scan_max_channels": 3,
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
        "scan_ranges": [{"start_mhz": 156.0, "end_mhz": 162.05, "step_khz": 25}],
        "scan_threshold_db": 10.0, "scan_max_channels": 3,
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
        "scan_ranges": [
            {"start_mhz": 26.96, "end_mhz": 27.41, "step_khz": 10},
            {"start_mhz": 446.0, "end_mhz": 446.2, "step_khz": 12.5},
        ],
        "scan_threshold_db": 10.0, "scan_max_channels": 2,
        "threshold_dbfs": -42.0, "hangover_s": 1.5, "gain": "auto",
        "band_label": "26–28 MHz CB / 446 MHz PMR", "transcribe_language": "tr",
    }

    def _listen_channel(self, chan, secs, stop_event):
        # CB/PMR karışık; kanal adını her iki tablodan çöz
        hint = "cb" if chan["freq_mhz"] < 30 else "pmr"
        self.MAP_HINT = hint
        super()._listen_channel(chan, secs, stop_event)
