"""Hedef 1 — Uçak takibi (ADS-B, 1090 MHz).

Araç: readsb (dump1090 uyumlu). readsb'yi JSON yazma kipinde çalıştırıp
aircraft.json dosyasını periyodik okuruz. Çağrı kodu, konum, irtifa, hız;
alçak uçuş ve acil squawk (7500/7600/7700) tespiti yapılır.

Sel koruması: havalimanı yakınında onlarca uçak görünür. Varsayılan kip
"summary": slot sonunda tek özet mesajı (en yakın/alçak uçaklar listesiyle).
Yalnız acil squawk, alçak uçuş ve `report_nearby_km` içindeki uçaklar ayrı
mesaj üretir. "each" kipi her yeni uçağı ayrı bildirir.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from ..events import Category, PRIO_EMERGENCY, PRIO_IMPORTANT
from ..geo import haversine_km, bearing_deg, compass_tr
from .base import TargetBase, SlotCollector

SQUAWK_EMERGENCY = {
    "7500": "Uçak kaçırma (hijack)",
    "7600": "Telsiz arızası",
    "7700": "Genel acil durum",
}


class ADSBTarget(TargetBase):
    NAME = "ADS-B Uçak"
    CATEGORY = Category.HAVACILIK
    CLASS = "waiting"
    DEFAULTS = {
        "enabled": True, "priority": 3, "dwell_s": 90, "period_s": 300,
        "freq_mhz": 1090.0, "gain": "auto", "band_label": "1090 MHz ADS-B",
        "low_alt_ft": 3000, "min_messages": 3, "tool": "readsb",
        "report_mode": "summary",        # summary | each
        "report_nearby_km": 8.0,         # bu mesafe içindeki yeni uçak ayrı mesaj
        "summary_list_max": 12,
        "emergency_realert_min": 60,
    }

    def tools_available(self):
        b = self._binary()
        return (b is not None), ("" if b else "readsb/dump1090 bulunamadı")

    def _binary(self):
        return self.cfg.which(self.conf.get("tool", "readsb"), "readsb", "dump1090", "dump1090-fa")

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        binary = self._binary()
        jdir = Path(tempfile.mkdtemp(prefix="adsb_", dir=str(self.cfg.data_dir / "tmp")))
        gain = self.conf.get("gain", "auto")
        name = Path(binary).name
        if "readsb" in name:
            cmd = [binary, "--device-type", "rtlsdr", "--device", str(self.sdr.device_index),
                   "--write-json", str(jdir), "--write-json-every", "1", "--quiet"]
            if not self.sdr.is_auto_gain(gain):
                cmd += ["--gain", str(gain)]
            if self.sdr.ppm:
                cmd += ["--ppm", str(self.sdr.ppm)]
        else:  # dump1090 türevleri
            cmd = [binary, "--write-json", str(jdir), "--write-json-every", "1", "--quiet"]
            if not self.sdr.is_auto_gain(gain):
                cmd += ["--gain", str(gain)]

        from ..proc import ManagedProcess, looks_like_device_error
        proc = ManagedProcess(cmd, name="adsb", log_path=self.cfg.log_dir / "adsb.log")
        self.sdr.wait_ready()
        try:
            proc.start()
        except Exception as e:
            self.log_error(f"readsb başlatılamadı: {e}")
            return
        jfile = jdir / "aircraft.json"
        deadline = time.time() + duration_s
        slot: dict[str, dict] = {}   # hex -> en son görülen bilgiler (bu slot)
        collector = SlotCollector(self, "ADS-B Özet", individual_max=0,
                                  list_max=int(self.conf.get("summary_list_max", 12)))
        started = time.time()
        try:
            while time.time() < deadline and not stop_event.is_set():
                if not proc.running:
                    if time.time() - started < 5 and looks_like_device_error(proc.stderr_tail):
                        self.log.debug("adsb: dongle meşgul, kısa bekleme sonrası yeniden deneniyor")
                        proc.stop(); time.sleep(1.5)
                        proc = ManagedProcess(cmd, name="adsb", log_path=self.cfg.log_dir / "adsb.log")
                        proc.start(); started = time.time()
                        continue
                    break
                self._poll(jfile, slot)
                stop_event.wait(1.0)
        finally:
            proc.stop()
            try:
                self.sdr.mark_released()
            except Exception:
                pass
            self._cleanup(jdir)
        self._finish_slot(slot, collector, time.time() - started)

    # ------------------------------------------------------------- yoklama
    def _poll(self, jfile: Path, slot: dict) -> None:
        try:
            data = json.loads(jfile.read_text())
        except (OSError, ValueError):
            return
        slat = self.cfg.get("station.lat"); slon = self.cfg.get("station.lon")
        for ac in data.get("aircraft", []):
            hexid = (ac.get("hex") or "").strip().lower()
            if not hexid or ac.get("seen", 99) > 15:
                continue
            if ac.get("messages", 0) < int(self.conf.get("min_messages", 3)):
                continue
            rec = slot.get(hexid)
            first_in_slot = rec is None
            if first_in_slot:
                rec = {"first": time.time(), "nearby_sent": False, "new": False}
                slot[hexid] = rec
            flight = (ac.get("flight") or "").strip() or rec.get("flight") or ""
            squawk = str(ac.get("squawk") or "").strip()
            lat, lon = ac.get("lat"), ac.get("lon")
            alt = ac.get("alt_baro") if ac.get("alt_baro") not in (None, "ground") else ac.get("alt_geom")
            rec.update({"flight": flight, "squawk": squawk, "lat": lat, "lon": lon, "alt": alt,
                        "gs": ac.get("gs"), "track": ac.get("track"), "rssi": ac.get("rssi"),
                        "ground": ac.get("alt_baro") == "ground"})
            if lat is not None and lon is not None and slat is not None:
                rec["dist"] = haversine_km(slat, slon, lat, lon)
                rec["brg"] = bearing_deg(slat, slon, lat, lon)
            if first_in_slot:
                is_new, _, _ = self.registry_touch("aircraft", hexid, {"flight": flight or None})
                rec["new"] = is_new
            # acil squawk: her zaman ve hemen
            if squawk in SQUAWK_EMERGENCY:
                self._maybe_emergency(hexid, rec, squawk)
            # yakın/alçak uçak: hemen ayrı mesaj (slot başına bir kez)
            if not rec["nearby_sent"] and self._is_notable(rec):
                rec["nearby_sent"] = True
                self._emit_aircraft(hexid, rec, notable=True)
            elif self.conf.get("report_mode", "summary") == "each" and first_in_slot and rec["new"]:
                self._emit_aircraft(hexid, rec, notable=False)

    def _is_notable(self, rec: dict) -> bool:
        if rec.get("ground"):
            return False
        low = isinstance(rec.get("alt"), (int, float)) and rec["alt"] <= float(self.conf.get("low_alt_ft", 3000))
        near = rec.get("dist") is not None and rec["dist"] <= float(self.conf.get("report_nearby_km", 8.0))
        return bool(low and near) or (near and rec.get("new"))

    # ------------------------------------------------------------- olaylar
    def _loc(self, rec):
        if rec.get("lat") is None or rec.get("dist") is None:
            return None
        return f"{rec['lat']:.4f}, {rec['lon']:.4f} ({rec['dist']:.1f} km {compass_tr(rec['brg'])})"

    def _maybe_emergency(self, hexid, rec, squawk):
        key = f"{hexid}-{squawk}"
        prev = self.st.registry_get("adsb_emerg", key)
        cooldown = float(self.conf.get("emergency_realert_min", 60)) * 60
        if prev and time.time() - prev["last_seen"] < cooldown:
            self.registry_touch("adsb_emerg", key)
            return
        self.registry_touch("adsb_emerg", key, {"flight": rec.get("flight")})
        label = SQUAWK_EMERGENCY[squawk]
        body = [f"<b>Squawk {squawk}</b> — {label}", f"ICAO: <code>{hexid.upper()}</code>",
                f"Çağrı: {rec.get('flight') or '—'}"]
        if rec.get("alt") is not None:
            body.append(f"İrtifa: {rec['alt']} ft")
        if rec.get("gs") is not None:
            body.append(f"Yer hızı: {rec['gs']:.0f} kt")
        ev = self.make_event(
            f"ACİL {squawk} • Uçak", summary=f"{label}: {rec.get('flight') or hexid.upper()}",
            body="\n".join(body), freq_mhz=1090.0, lat=rec.get("lat"), lon=rec.get("lon"),
            location_text=self._loc(rec), signal=self._sig(rec), signal_value=rec.get("rssi"),
            priority=PRIO_EMERGENCY, dedup_key=f"adsb-emerg-{key}")
        ev.category = Category.ACIL
        self.emit(ev)

    @staticmethod
    def _sig(rec):
        r = rec.get("rssi")
        return f"{r:.1f} dBFS" if isinstance(r, (int, float)) else None

    def _emit_aircraft(self, hexid, rec, notable: bool):
        low = isinstance(rec.get("alt"), (int, float)) and rec["alt"] <= float(self.conf.get("low_alt_ft", 3000))
        body = [f"ICAO adresi: <code>{hexid.upper()}</code>", f"Çağrı kodu : {rec.get('flight') or '—'}"]
        if rec.get("alt") is not None:
            body.append(f"İrtifa     : {rec['alt']} ft" + ("  ⚠️ alçak uçuş" if low else ""))
        if rec.get("gs") is not None:
            body.append(f"Yer hızı   : {rec['gs']:.0f} kt")
        if rec.get("track") is not None:
            body.append(f"Yön        : {rec['track']:.0f}° ({compass_tr(rec['track'])})")
        if rec.get("squawk"):
            body.append(f"Squawk     : {rec['squawk']}")
        what = "Yakın uçak" if notable else "Yeni uçak"
        summary = f"{what} {rec.get('flight') or hexid.upper()}"
        if rec.get("dist") is not None:
            summary += f" — {rec['dist']:.1f} km"
        ev = self.make_event(
            self.NAME, summary=summary, body="\n".join(body), freq_mhz=1090.0,
            lat=rec.get("lat"), lon=rec.get("lon"), location_text=self._loc(rec),
            signal=self._sig(rec), signal_value=rec.get("rssi"),
            priority=(PRIO_IMPORTANT if (notable and low) else self.priority),
            dedup_key=f"adsb-{hexid}")
        self.emit(ev)

    def _finish_slot(self, slot: dict, collector: SlotCollector, elapsed: float):
        if not slot or self.conf.get("report_mode", "summary") != "summary":
            return
        new_n = sum(1 for r in slot.values() if r.get("new"))
        with_pos = [(h, r) for h, r in slot.items() if r.get("dist") is not None]
        with_pos.sort(key=lambda x: x[1]["dist"])
        rssi_vals = [r["rssi"] for r in slot.values() if isinstance(r.get("rssi"), (int, float))]
        best = max(rssi_vals) if rssi_vals else None
        lines = []
        for h, r in with_pos[: int(self.conf.get("summary_list_max", 12))]:
            alt = f"{r['alt']} ft" if r.get("alt") is not None else "—"
            lines.append(f"• {r.get('flight') or h.upper():<8} {alt:>9}  {r['dist']:5.1f} km {compass_tr(r['brg'])}"
                         + ("  🆕" if r.get("new") else ""))
        more = len(slot) - len(lines)
        body = [f"Toplam {len(slot)} uçak ({new_n} yeni), konumlu {len(with_pos)}",
                f"Dinleme süresi: {elapsed:.0f} sn", ""] + lines
        if more > 0:
            body.append(f"… ve {more} uçak daha")
        near_txt = f", en yakın {with_pos[0][1]['dist']:.1f} km" if with_pos else ""
        ev = self.make_event(
            "ADS-B Özet", summary=f"{len(slot)} uçak görüldü ({new_n} yeni){near_txt}",
            body="\n".join(body), freq_mhz=1090.0, duration_s=elapsed,
            signal=(f"{best:.1f} dBFS (en güçlü)" if best is not None else None), signal_value=best,
            extra={"aircraft": len(slot), "new": new_n})
        self.emit(ev)

    def _cleanup(self, jdir: Path):
        try:
            for f in jdir.glob("*"):
                f.unlink()
            jdir.rmdir()
        except OSError:
            pass
