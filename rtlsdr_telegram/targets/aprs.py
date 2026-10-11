"""Target 6 — Amateur packet radio (APRS, 144.800 MHz).

Tool: rtl_fm -> multimon-ng (AFSK1200) pipeline. Decoded TNC2 frames are parsed
with aprslib: position, callsign, symbol, short message/status. A station is
reported when first seen; message packets are always reported.

multimon-ng was chosen because it is light, takes raw audio from a pipe and
decodes APRS/AFSK1200. direwolf can be used instead (config.tool).
"""
from __future__ import annotations

import threading

from ..events import Category
from ..geo import haversine_km, bearing_deg, compass
from ..i18n import t
from ..proc import shell_pipeline
from .base import TargetBase

try:
    import aprslib
    HAVE_APRSLIB = True
except ImportError:
    HAVE_APRSLIB = False


class APRSTarget(TargetBase):
    NAME_KEY = "aprs.name"
    BAND_KEY = "aprs.band"
    CATEGORY = Category.AMATOR
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 5, "dwell_s": 45, "period_s": 300,
        "freq_mhz": 144.800, "gain": "auto",
        "report_all_packets": False,
    }

    def tools_available(self):
        if not self.sdr.bin_rtl_fm:
            return False, "rtl_fm not found"
        if not self.cfg.which("multimon-ng", "direwolf"):
            return False, "multimon-ng/direwolf not found"
        return True, ""

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        freq_hz = int(self.conf.get("freq_mhz", 144.8) * 1e6)
        gain = self.conf.get("gain", "auto")
        rate = 22050
        rtl = self.sdr.rtl_fm_cmd(freq_hz, mode="fm", sample_rate=rate, resample=rate, gain=gain)
        mm = self.cfg.which("multimon-ng")
        if mm:
            pipeline = " ".join(self._q(rtl)) + f" | {self._q1(mm)} -t raw -a AFSK1200 -A -"
        else:
            # direwolf alternative
            dw = self.cfg.which("direwolf")
            pipeline = " ".join(self._q(rtl)) + f" | {self._q1(dw)} -r {rate} -D 1 -t 0 -q d -"
        self.run_tool_lines(shell_pipeline(pipeline), stop_event, duration_s, self._on_line,
                            name="aprs", log_name="aprs")

    @staticmethod
    def _q(parts):
        return [APRSTarget._q1(p) for p in parts]

    @staticmethod
    def _q1(p):
        p = str(p)
        return "'" + p.replace("'", "'\\''") + "'" if (" " in p or "'" in p) else p

    def _on_line(self, line: str):
        line = line.strip()
        frame = None
        if line.startswith("APRS:"):
            frame = line[5:].strip()
        elif ">" in line and ":" in line and HAVE_APRSLIB and not line.startswith(("Enabled", "multimon", "Using")):
            # may be a raw direwolf frame line
            frame = line.strip()
        if not frame:
            return
        self._handle_frame(frame)

    def _handle_frame(self, frame: str):
        src = frame.split(">")[0].strip() if ">" in frame else "?"
        lat = lon = None
        comment = ""
        info = ""
        if HAVE_APRSLIB:
            try:
                p = aprslib.parse(frame)
                src = p.get("from", src)
                lat = p.get("latitude")
                lon = p.get("longitude")
                comment = p.get("comment", "") or ""
                if p.get("message_text"):
                    info = f"{t('aprs.message')}: {p['message_text']}"
                elif p.get("status"):
                    info = f"{t('aprs.status')}: {p['status']}"
                elif p.get("weather"):
                    info = t("aprs.weather")
            except Exception:
                info = frame.split(":", 1)[-1][:120] if ":" in frame else ""
        else:
            info = frame.split(":", 1)[-1][:120] if ":" in frame else ""

        is_new, _, count = self.registry_touch("aprs_station", src, {"last": comment[:60] or None})
        has_msg = bool(info)
        if not is_new and not has_msg and not self.conf.get("report_all_packets", False):
            return

        slat = self.cfg.get("station.lat"); slon = self.cfg.get("station.lon")
        loc_txt = None
        dist = None
        if lat is not None and lon is not None and slat is not None:
            dist = haversine_km(slat, slon, lat, lon)
            loc_txt = f"{lat:.4f}, {lon:.4f} ({dist:.1f} km {compass(bearing_deg(slat, slon, lat, lon))})"

        body = [f"{t('aprs.callsign')}: {src}"]
        if comment:
            body.append(f"{t('aprs.comment')}: {self._trim(comment)}")
        if info:
            body.append(info)
        body.append(f"\n<code>{self._trim(frame, 200)}</code>")
        summary = (f"{t('aprs.new')} {src}" if is_new else f"{src}") + (f" — {dist:.0f} km" if dist is not None else "")
        ev = self.make_event(
            self.display_name(), summary=summary, body="\n".join(body),
            freq_mhz=self.conf.get("freq_mhz", 144.8), lat=lat, lon=lon, location_text=loc_txt,
            dedup_key=f"aprs-{src}" if is_new else None)
        self.emit(ev)

    @staticmethod
    def _trim(text: str, limit: int = 120) -> str:
        text = " ".join(text.split())
        return text if len(text) <= limit else text[:limit] + "…"
