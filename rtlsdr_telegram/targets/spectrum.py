"""Hedef 16 — Spektrum taraması ve anomali tespiti (24–1766 MHz, FM/TV hariç).

Araç: rtl_power (SoapySDR gerekmez). "Normal" taban gürültü profili öğrenilir
(her frekans kutusu için üstel hareketli ortalama, DB'de saklanır). Yeni, güçlü
veya alışılmadık bir sinyal çıkınca frekans, süre, güç ve şelale (waterfall)
görüntüsü gönderilir.

Çalışma:
  1. Taranacak aralık kara liste (FM/TV dahil) boşluklarına bölünür.
  2. rtl_power pencere boyunca çalışır; (zaman × frekans) güç matrisi toplanır.
  3. Ortalama profil, saklanan taban + eşik ile karşılaştırılır; aşan bitişik
     kutular bir "sinyal" olarak gruplanır.
  4. Her anomali için şelale PNG üretilir (matplotlib) ve olay gönderilir.
  5. Taban, anomali olmayan bölgelerde EMA ile güncellenir.

İlk birkaç tarama "öğrenme" kipidir (profil olgunlaşana kadar alarm üretmez).
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..events import Category, Attachment, PRIO_NORMAL
from .base import TargetBase

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class SpectrumTarget(TargetBase):
    NAME = "Spektrum Anomali"
    CATEGORY = Category.TARAMA
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 5, "dwell_s": 120, "period_s": 600,
        "scan_start_mhz": 24.0, "scan_end_mhz": 1766.0, "bin_khz": 25,
        "gain": "auto", "integration_s": 1, "threshold_db": 10.0,
        "min_abs_floor_db": 6.0, "ema_alpha": 0.2, "learn_scans": 3,
        "max_anomalies_per_slot": 4, "min_bandwidth_khz": 25,
        "waterfall": True, "band_label": "24–1766 MHz spektrum (FM/TV hariç)",
        "sub_range_max_mhz": 200,
    }

    def tools_available(self):
        ok = self.sdr.bin_rtl_power is not None
        return ok, ("" if ok else "rtl_power yok")

    # taranacak alt aralıklar (kara liste boşlukları)
    def _subranges(self) -> list[tuple[float, float]]:
        lo = float(self.conf.get("scan_start_mhz", 24.0))
        hi = float(self.conf.get("scan_end_mhz", 1766.0))
        bl = sorted(self.cfg.blacklist_ranges())
        gaps = []
        cur = lo
        for b0, b1, _ in bl:
            if b1 < cur or b0 > hi:
                continue
            if b0 > cur:
                gaps.append((cur, min(b0, hi)))
            cur = max(cur, b1)
        if cur < hi:
            gaps.append((cur, hi))
        # büyük aralıkları böl (rtl_power tek seferde çok geniş istemesin)
        step = float(self.conf.get("sub_range_max_mhz", 200))
        out = []
        for a, b in gaps:
            x = a
            while x < b:
                out.append((x, min(x + step, b)))
                x += step
        return out

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        if not self.check_tools():
            return
        subs = self._subranges()
        if not subs:
            return
        per = duration_s / len(subs)
        anomalies_left = int(self.conf.get("max_anomalies_per_slot", 4))
        for (a, b) in subs:
            if stop_event.is_set() or anomalies_left <= 0:
                break
            anomalies_left -= self._scan_subrange(a, b, min(per, 60), stop_event, anomalies_left)

    def _scan_subrange(self, start_mhz, end_mhz, secs, stop_event, budget) -> int:
        binhz = int(self.conf.get("bin_khz", 25) * 1000)
        integ = str(self.conf.get("integration_s", 1))
        # (zaman, f_low, step, values[]) satırlarını topla
        series: list[tuple[float, float, list[float]]] = []

        def on_line(line):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                return
            try:
                f_low = float(parts[2]); step = float(parts[4])
                vals = [float(x) for x in parts[6:] if x not in ("", "-inf", "nan")]
            except ValueError:
                return
            series.append((f_low, step, vals))

        try:
            proc = self.sdr.power_scan(int(start_mhz * 1e6), int(end_mhz * 1e6), binhz,
                                       integration=integ, gain=self.conf.get("gain", "auto"),
                                       oneshot=False, log_path=self.cfg.log_dir / "spectrum.log")
        except Exception as e:
            self.log_error(f"rtl_power kurulamadı: {e}")
            return 0
        proc.on_line = on_line
        try:
            proc.start()
            deadline = time.time() + secs
            while time.time() < deadline and proc.running and not stop_event.is_set():
                stop_event.wait(0.5)
        finally:
            proc.stop()
        if not series:
            return 0
        return self._analyze(start_mhz, end_mhz, series, budget)

    def _analyze(self, start_mhz, end_mhz, series, budget) -> int:
        # frekans kutusu -> güç listesi (zaman ekseni)
        buckets: dict[float, list[float]] = defaultdict(list)
        for f_low, step, vals in series:
            for i, v in enumerate(vals):
                fc = round((f_low + i * step) / 1e6, 4)
                buckets[fc].append(v)
        if not buckets:
            return 0
        freqs = sorted(buckets)
        profile = {f: (sum(v) / len(v)) for f, v in buckets.items()}

        # taban profili yükle
        bl_key = f"spectrum_baseline_{start_mhz:.0f}_{end_mhz:.0f}"
        state = self.st.kv_get(bl_key, {}) or {}
        baseline = state.get("baseline", {})
        scans = int(state.get("scans", 0))
        alpha = float(self.conf.get("ema_alpha", 0.2))
        thr = float(self.conf.get("threshold_db", 10.0))
        floor_db = float(self.conf.get("min_abs_floor_db", 6.0))

        # genel gürültü tabanı (medyan)
        vals_sorted = sorted(profile.values())
        noise_floor = vals_sorted[len(vals_sorted) // 2]

        learning = scans < int(self.conf.get("learn_scans", 3))
        anomaly_bins = []
        if not learning:
            for f in freqs:
                base = baseline.get(f"{f:.4f}")
                cur = profile[f]
                over_base = (cur - base) if base is not None else 0
                over_floor = cur - noise_floor
                if base is not None and over_base >= thr and over_floor >= floor_db:
                    anomaly_bins.append((f, cur, over_base))

        # taban güncelle (anomali olmayan kutular daha güçlü güncellenir)
        anomaly_set = {f for f, _, _ in anomaly_bins}
        new_base = dict(baseline)
        for f in freqs:
            key = f"{f:.4f}"
            cur = profile[f]
            old = baseline.get(key)
            a = alpha * 0.2 if f in anomaly_set else alpha
            new_base[key] = cur if old is None else (a * cur + (1 - a) * old)
        self.st.kv_set(bl_key, {"baseline": new_base, "scans": scans + 1,
                                "updated": time.time(), "noise_floor": noise_floor})

        if learning:
            self.log.info("spektrum öğrenme %d/%s (%.0f–%.0f MHz)", scans + 1,
                          self.conf.get("learn_scans", 3), start_mhz, end_mhz)
            return 0
        if not anomaly_bins:
            return 0

        # bitişik kutuları grupla
        groups = self._group(anomaly_bins)
        groups.sort(key=lambda g: -g["peak_over"])
        min_bw = float(self.conf.get("min_bandwidth_khz", 25)) / 1000.0
        emitted = 0
        for g in groups[:budget]:
            if g["f_hi"] - g["f_lo"] + 0.001 < min_bw and g["peak_over"] < thr + 6:
                pass  # tek kutu da olsa güçlüyse bildir
            emitted += self._emit_anomaly(g, series, start_mhz, end_mhz, noise_floor)
        return emitted

    @staticmethod
    def _group(bins):
        bins = sorted(bins, key=lambda x: x[0])
        groups = []
        cur = None
        for f, p, over in bins:
            if cur and f - cur["f_hi"] <= 0.05:  # 50 kHz içinde bitişik
                cur["f_hi"] = f
                if over > cur["peak_over"]:
                    cur["peak_over"] = over
                    cur["peak_f"] = f
                    cur["peak_p"] = p
            else:
                if cur:
                    groups.append(cur)
                cur = {"f_lo": f, "f_hi": f, "peak_f": f, "peak_p": p, "peak_over": over}
        if cur:
            groups.append(cur)
        return groups

    def _emit_anomaly(self, g, series, start_mhz, end_mhz, noise_floor) -> int:
        peak_f = g["peak_f"]
        bw_khz = (g["f_hi"] - g["f_lo"]) * 1000 + float(self.conf.get("bin_khz", 25))
        key = f"{peak_f:.2f}"
        is_new, first_seen, count = self.registry_touch(
            "spectrum_anom", key, {"peak_db": round(g["peak_p"], 1), "bw_khz": round(bw_khz, 1)})
        duration = time.time() - first_seen if not is_new else 0

        atts = []
        if self.conf.get("waterfall", True) and HAVE_NUMPY:
            img = self._waterfall(series, peak_f, g["f_lo"], g["f_hi"])
            if img:
                atts.append(Attachment("photo", img, caption=f"Şelale: {peak_f:.3f} MHz", delete_after=False))

        label = "Yeni sinyal" if is_new else "Süregelen sinyal"
        body = [f"Tepe frekans: {peak_f:.3f} MHz",
                f"Bant genişliği: ~{bw_khz:.0f} kHz",
                f"Güç        : {g['peak_p']:.1f} dB (taban +{g['peak_over']:.0f} dB)",
                f"Gürültü tabanı: {noise_floor:.1f} dB"]
        if not is_new:
            body.append(f"İlk görülme : {datetime.fromtimestamp(first_seen, tz=timezone.utc).astimezone().strftime('%H:%M:%S')} ({count}. kez)")
        ev = self.make_event(
            "Spektrum Anomali", summary=f"{label} @ {peak_f:.3f} MHz (+{g['peak_over']:.0f} dB)",
            body="\n".join(body), freq_mhz=peak_f,
            band=f"{start_mhz:.0f}–{end_mhz:.0f} MHz tarama",
            signal=f"+{g['peak_over']:.0f} dB taban üstü", signal_value=g["peak_p"],
            duration_s=duration if duration > 0 else None, attachments=atts,
            dedup_key=f"spec-{key}" if is_new else None)
        self.emit(ev)
        return 1

    def _waterfall(self, series, peak_f, f_lo, f_hi) -> str | None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return None
        margin = max(0.2, (f_hi - f_lo) * 2)
        lo = (f_lo - margin)
        hi = (f_hi + margin)
        rows = []
        freq_axis = None
        for f_low, step, vals in series:
            f0 = f_low / 1e6
            fs = [f0 + i * step / 1e6 for i in range(len(vals))]
            sel = [(fr, v) for fr, v in zip(fs, vals) if lo <= fr <= hi]
            if sel:
                rows.append([v for _, v in sel])
                if freq_axis is None or len(sel) > len(freq_axis):
                    freq_axis = [fr for fr, _ in sel]
        if not rows or not freq_axis:
            return None
        width = min(len(r) for r in rows)
        mat = np.array([r[:width] for r in rows])
        try:
            fig, ax = plt.subplots(figsize=(7, 4), dpi=110)
            extent = [freq_axis[0], freq_axis[min(width - 1, len(freq_axis) - 1)], len(rows), 0]
            im = ax.imshow(mat, aspect="auto", extent=extent, cmap="viridis", interpolation="nearest")
            ax.axvline(peak_f, color="red", lw=0.8, alpha=0.7)
            ax.set_xlabel("Frekans (MHz)")
            ax.set_ylabel("Zaman (tarama)")
            ax.set_title(f"Spektrum şelalesi @ {peak_f:.3f} MHz")
            fig.colorbar(im, ax=ax, label="dB")
            fig.tight_layout()
            out = self.cfg.recordings_dir / "spectrum" / f"waterfall_{peak_f:.3f}_{int(time.time())}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out)
            plt.close(fig)
            return str(out)
        except Exception as e:
            self.log.warning("şelale üretilemedi: %s", e)
            return None
