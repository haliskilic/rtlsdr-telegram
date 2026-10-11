"""Hedef 15 — Inmarsat denizcilik emniyet yayınları (~1.5 GHz STD-C / AERO).

Araç: JAERO / scytale-C (harici çözücü). Bu hedef EK DONANIM gerektirir:
L-bant anten + LNA (ve çoğu zaman bias-tee). Yapılandırmada "active/passive"
seçeneği vardır; pasifse veya çözücü tanımlı değilse hedef otomatik atlanır
(madde 2/15).

Dongle 1766 MHz'e kadar çıkabildiğinden 1537–1545 MHz teknik olarak erişilebilir,
ancak uygun anten/LNA olmadan sinyal alınamaz. `auto_skip_if_no_signal` açıkken
kısa bir enerji kontrolü yapılır; taşıyıcı yoksa hedef sessizce atlanır.

Çözücü komutu config.decoder_cmd ile verilir; stdout satırları mesaj olarak
ayrıştırılır. Komut yoksa, donanımın nasıl kurulacağını anlatan tek seferlik
bir bilgi notu üretilir.
"""
from __future__ import annotations

import threading
import time

from ..events import Category
from .base import TargetBase


class InmarsatTarget(TargetBase):
    NAME = "Inmarsat STD-C"
    CATEGORY = Category.DENIZCILIK
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": False, "active": False, "priority": 4, "dwell_s": 120, "period_s": 1800,
        "freq_mhz": 1541.45, "gain": 49, "bias_tee": True,
        "decoder_cmd": "", "auto_skip_if_no_signal": True, "energy_threshold_db": 8.0,
        "band_label": "~1.5 GHz Inmarsat (L-bant)", "info_notified": False,
    }

    def tools_available(self):
        if not self.conf.get("active", False):
            return False, "pasif (active:false)"
        return True, ""

    def needs_device(self) -> bool:
        return self.conf.get("active", False)

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.conf.get("active", False):
            return  # pasif — atla
        decoder = self.conf.get("decoder_cmd", "")
        if not decoder:
            self._notify_setup_once()
            return
        # isteğe bağlı enerji kontrolü (anten yoksa atla)
        if self.conf.get("auto_skip_if_no_signal", True) and not self._has_signal(stop_event):
            self.log.debug("Inmarsat: taşıyıcı yok, atlanıyor (anten/LNA?)")
            return
        self._run_decoder(decoder, stop_event, duration_s)

    def _has_signal(self, stop_event) -> bool:
        if not self.sdr.bin_rtl_power:
            return True  # kontrol edemiyoruz, dene
        f = int(self.conf.get("freq_mhz", 1541.45) * 1e6)
        thr = float(self.conf.get("energy_threshold_db", 8.0))
        rows = []

        def on_line(line):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                return
            try:
                vals = [float(x) for x in parts[6:] if x]
            except ValueError:
                return
            rows.extend(vals)
        try:
            proc = self.sdr.power_scan(f - 100000, f + 100000, 2000, gain=self.conf.get("gain", 49),
                                       oneshot=True, log_path=self.cfg.log_dir / "inmarsat_scan.log")
        except Exception:
            return True
        proc.on_line = on_line
        try:
            proc.start()
            t0 = time.time()
            while time.time() - t0 < 4 and proc.running and not stop_event.is_set():
                stop_event.wait(0.3)
        finally:
            proc.stop()
        if len(rows) < 4:
            return False
        rows.sort()
        med = rows[len(rows) // 2]
        return (rows[-1] - med) >= thr

    def _run_decoder(self, decoder: str, stop_event, duration_s):
        freq_hz = int(self.conf.get("freq_mhz", 1541.45) * 1e6)
        cmd = decoder.format(freq_hz=freq_hz, freq_mhz=self.conf.get("freq_mhz"),
                             device=self.sdr.device_index, gain=self.conf.get("gain", 49))

        def on_line(line):
            line = line.strip()
            if len(line) < 4:
                return
            ev = self.make_event("Inmarsat Mesaj", summary=line[:120],
                                 body=f"<code>{line[:900]}</code>", freq_mhz=self.conf.get("freq_mhz"),
                                 priority=self.priority)
            self.emit(ev)
        self.run_tool_lines(["bash", "-c", cmd], stop_event, duration_s, on_line,
                            name="inmarsat", log_name="inmarsat")

    def _notify_setup_once(self):
        if self.st.kv_get("inmarsat_setup_notified"):
            return
        self.st.kv_set("inmarsat_setup_notified", True)
        ev = self.make_event(
            "Inmarsat Kurulum", summary="Inmarsat aktif ama çözücü komutu tanımlı değil",
            body=("Inmarsat STD-C/AERO için ek donanım gerekir: L-bant anten + LNA (ve bias-tee). "
                  "Çözücü olarak JAERO veya scytale-C kullanılır. Kurulum sonrası "
                  "<code>targets.inmarsat.decoder_cmd</code> alanına çözücü komutunuzu yazın "
                  "(örn. rtl_sdr borusu → JAERO). Donanım yoksa <code>active: false</code> bırakın."),
            freq_mhz=self.conf.get("freq_mhz"), priority=7)
        self.emit(ev)
