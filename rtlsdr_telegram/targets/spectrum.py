"""Target 16 — Spectrum sweep and anomaly detection (24–1766 MHz, FM/TV excluded).

Tool: rtl_power (no SoapySDR needed). A "normal" noise-floor profile is learned
(exponential moving average per frequency bin, stored as .npz). When a new,
strong or unusual signal appears, frequency, duration, power and a waterfall
image are sent.

Operation:
  1. The sweep range is split at blacklist gaps (FM/TV ...) into sub-ranges.
  2. ONE sub-range per slot is swept for the whole dwell (rotation); ~7 slots
     cover the entire spectrum.
  3. The averaged profile is compared with the stored baseline + threshold;
     adjacent bins above it are grouped into one "signal".
  4. For each anomaly a focused narrow-band capture produces a waterfall PNG.
  5. The baseline is updated with EMA (anomaly bins adapt slowly).

The first few sweeps are "learning" sweeps (no alarms until the profile matures).
Repeated reports of the same ongoing signal are suppressed for `repeat_min`.
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
from ..i18n import t
from .base import TargetBase

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class SpectrumTarget(TargetBase):
    NAME_KEY = "spec.name"
    BAND_KEY = "spec.band"
    CATEGORY = Category.TARAMA
    CLASS = "opportunistic"
    DEFAULTS = {
        "enabled": True, "priority": 5, "dwell_s": 120, "period_s": 600,
        "scan_start_mhz": 24.0, "scan_end_mhz": 1766.0, "bin_khz": 25,
        "gain": "auto", "integration_s": 1, "threshold_db": 10.0,
        "min_abs_floor_db": 6.0, "ema_alpha": 0.2, "learn_scans": 3,
        "max_anomalies_per_slot": 4, "min_bandwidth_khz": 25,
        "waterfall": True,
        "sub_range_max_mhz": 200,
        "repeat_min": 60,              # the same anomaly is reported again at most every N minutes
        "focus_capture_s": 12,         # focused waterfall capture duration per anomaly
    }

    def tools_available(self):
        ok = self.sdr.bin_rtl_power is not None
        return ok, ("" if ok else "rtl_power not found")

    # sub-ranges to sweep (gaps between blacklist entries)
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
        # split large ranges so one rtl_power run is not too wide
        step = float(self.conf.get("sub_range_max_mhz", 200))
        out = []
        for a, b in gaps:
            x = a
            while x < b:
                out.append((x, min(x + step, b)))
                x += step
        return out

    def run_slot(self, stop_event: threading.Event, duration_s: float) -> None:
        """Sweep ONE sub-range per slot for the whole dwell (rotation).

        Sweeping every sub-range in every slot left rtl_power ~17 s per range,
        covering only ~15% of a 200 MHz range and learning the baseline unevenly.
        With rotation the whole spectrum is covered in ~7 slots."""
        if not self.check_tools():
            return
        subs = self._subranges()
        if not subs:
            return
        idx = int(self.st.kv_get("spectrum_rotation_idx", 0) or 0) % len(subs)
        a, b = subs[idx]
        self.st.kv_set("spectrum_rotation_idx", (idx + 1) % len(subs))
        self.log.info("spectrum: sweeping %.0f–%.0f MHz (%d/%d)", a, b, idx + 1, len(subs))
        budget = int(self.conf.get("max_anomalies_per_slot", 4))
        self._scan_subrange(a, b, duration_s, stop_event, budget)

    def _scan_subrange(self, start_mhz, end_mhz, secs, stop_event, budget) -> int:
        binhz = int(self.conf.get("bin_khz", 25) * 1000)
        integ = str(self.conf.get("integration_s", 1))
        # collect (f_low, step, values[]) rows
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
            self.log_error(f"rtl_power could not be started: {e}")
            return 0
        proc.on_line = on_line
        try:
            proc.start()
            deadline = time.time() + secs
            while time.time() < deadline and proc.running and not stop_event.is_set():
                stop_event.wait(0.5)
        finally:
            proc.stop()
            try:
                self.sdr.mark_released()
            except Exception:
                pass
        if not series:
            return 0
        self._stop_event = stop_event
        return self._analyze(start_mhz, end_mhz, series, budget)

    def _analyze(self, start_mhz, end_mhz, series, budget) -> int:
        # frequency bin -> list of power values (time axis)
        buckets: dict[float, list[float]] = defaultdict(list)
        for f_low, step, vals in series:
            for i, v in enumerate(vals):
                fc = round((f_low + i * step) / 1e6, 4)
                buckets[fc].append(v)
        if not buckets:
            return 0
        freqs = sorted(buckets)
        profile = {f: (sum(v) / len(v)) for f, v in buckets.items()}

        # load the baseline profile (npz: ~10x smaller/faster than kv JSON)
        bl_key = f"spectrum_baseline_{start_mhz:.0f}_{end_mhz:.0f}"
        baseline, scans = self._load_baseline(bl_key)
        alpha = float(self.conf.get("ema_alpha", 0.2))
        thr = float(self.conf.get("threshold_db", 10.0))
        floor_db = float(self.conf.get("min_abs_floor_db", 6.0))

        # overall noise floor (median)
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

        # update the baseline (non-anomaly bins adapt faster)
        anomaly_set = {f for f, _, _ in anomaly_bins}
        new_base = dict(baseline)
        for f in freqs:
            key = f"{f:.4f}"
            cur = profile[f]
            old = baseline.get(key)
            a = alpha * 0.2 if f in anomaly_set else alpha
            new_base[key] = cur if old is None else (a * cur + (1 - a) * old)
        self._save_baseline(bl_key, new_base, scans + 1, noise_floor)

        if learning:
            self.log.info("spectrum learning %d/%s (%.0f–%.0f MHz)", scans + 1,
                          self.conf.get("learn_scans", 3), start_mhz, end_mhz)
            return 0
        if not anomaly_bins:
            return 0

        # group adjacent bins
        groups = self._group(anomaly_bins)
        groups.sort(key=lambda g: -g["peak_over"])
        min_bw = float(self.conf.get("min_bandwidth_khz", 25)) / 1000.0
        emitted = 0
        for g in groups[:budget]:
            if g["f_hi"] - g["f_lo"] + 0.001 < min_bw and g["peak_over"] < thr + 6:
                pass  # a single strong bin is still worth reporting
            emitted += self._emit_anomaly(g, series, start_mhz, end_mhz, noise_floor)
        return emitted

    # ------------------------------------------------------- baseline file
    def _baseline_path(self, key: str):
        d = self.cfg.data_dir / "spectrum"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.npz"

    def _load_baseline(self, key: str) -> tuple[dict, int]:
        if not HAVE_NUMPY:
            st = self.st.kv_get(key, {}) or {}
            return st.get("baseline", {}), int(st.get("scans", 0))
        path = self._baseline_path(key)
        if not path.exists():
            return {}, 0
        try:
            z = np.load(path)
            freqs = z["freqs"]; vals = z["vals"]; scans = int(z["scans"])
            return {float(f): float(v) for f, v in zip(freqs, vals)}, scans
        except Exception as e:
            self.log.warning("baseline load failed (%s): %s", key, e)
            return {}, 0

    def _save_baseline(self, key: str, base: dict, scans: int, noise_floor: float) -> None:
        if not HAVE_NUMPY:
            self.st.kv_set(key, {"baseline": base, "scans": scans, "noise_floor": noise_floor})
            return
        try:
            items = sorted((float(k), float(v)) for k, v in base.items())
            np.savez(self._baseline_path(key), freqs=np.array([f for f, _ in items], dtype=np.float64),
                     vals=np.array([v for _, v in items], dtype=np.float32), scans=scans,
                     noise_floor=noise_floor, updated=time.time())
        except Exception as e:
            self.log.warning("baseline save failed (%s): %s", key, e)

    def _focused_waterfall(self, peak_f: float, f_lo: float, f_hi: float) -> str | None:
        """Short narrow-band rtl_power capture around the anomaly -> real time axis."""
        if not self.sdr.bin_rtl_power:
            return None
        stop_event = getattr(self, "_stop_event", None)
        secs = float(self.conf.get("focus_capture_s", 12))
        span = max(0.4, (f_hi - f_lo) * 3)
        lo, hi = max(24.0, peak_f - span / 2), min(1766.0, peak_f + span / 2)
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
            proc = self.sdr.power_scan(int(lo * 1e6), int(hi * 1e6), 5000, integration="1",
                                       gain=self.conf.get("gain", "auto"), oneshot=False,
                                       log_path=self.cfg.log_dir / "spectrum_focus.log")
        except Exception:
            return None
        proc.on_line = on_line
        try:
            proc.start()
            t0 = time.time()
            while time.time() - t0 < secs and proc.running and not (stop_event and stop_event.is_set()):
                time.sleep(0.3)
        finally:
            proc.stop()
            try:
                self.sdr.mark_released()
            except Exception:
                pass
        if len(series) < 3:
            return None
        return self._waterfall(series, peak_f, f_lo, f_hi)

    @staticmethod
    def _group(bins):
        bins = sorted(bins, key=lambda x: x[0])
        groups = []
        cur = None
        for f, p, over in bins:
            if cur and f - cur["f_hi"] <= 0.05:  # adjacent within 50 kHz
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
        prev = self.st.registry_get("spectrum_anom", key)
        is_new, first_seen, count = self.registry_touch(
            "spectrum_anom", key, {"peak_db": round(g["peak_p"], 1), "bw_khz": round(bw_khz, 1)})
        duration = time.time() - first_seen if not is_new else 0
        # do not re-report the same ongoing signal every slot (repeat_min)
        repeat_s = float(self.conf.get("repeat_min", 60)) * 60
        if not is_new and prev:
            last_rep = float(prev["data"].get("reported", 0) or 0)
            if time.time() - last_rep < repeat_s:
                return 0
        data = (prev["data"] if prev else {})
        data.update({"reported": time.time(), "peak_db": round(g["peak_p"], 1)})
        self.st.registry_set_data("spectrum_anom", key, data)

        atts = []
        if self.conf.get("waterfall", True) and HAVE_NUMPY:
            # focused waterfall: narrow band around the anomaly, short time series
            img = self._focused_waterfall(peak_f, g["f_lo"], g["f_hi"]) or \
                self._waterfall(series, peak_f, g["f_lo"], g["f_hi"])
            if img:
                atts.append(Attachment("photo", img, caption=t("spec.caption", f=f"{peak_f:.3f}"), delete_after=False))

        label = t("spec.new") if is_new else t("spec.ongoing")
        body = [f"{t('spec.peak')}: {peak_f:.3f} MHz",
                f"{t('spec.bw')}: ~{bw_khz:.0f} kHz",
                f"{t('spec.power')}: {g['peak_p']:.1f} dB (+{g['peak_over']:.0f} dB)",
                f"{t('spec.floor')}: {noise_floor:.1f} dB"]
        if not is_new:
            body.append(f"{t('spec.first_seen')}: {datetime.fromtimestamp(first_seen, tz=timezone.utc).astimezone().strftime('%H:%M:%S')} {t('spec.seen_n', n=count)}")
        ev = self.make_event(
            self.display_name(), summary=t("spec.summary", label=label, f=f"{peak_f:.3f}", db=f"{g['peak_over']:.0f}"),
            body="\n".join(body), freq_mhz=peak_f,
            band=t("spec.sweep", a=f"{start_mhz:.0f}", b=f"{end_mhz:.0f}"),
            signal=t("common.above_floor", db=f"{g['peak_over']:.0f}"), signal_value=g["peak_p"],
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
            ax.set_xlabel(t("spec.plot_x"))
            ax.set_ylabel(t("spec.plot_y"))
            ax.set_title(t("spec.plot_title", f=f"{peak_f:.3f}"))
            fig.colorbar(im, ax=ax, label="dB")
            fig.tight_layout()
            out = self.cfg.recordings_dir / "spectrum" / f"waterfall_{peak_f:.3f}_{int(time.time())}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out)
            plt.close(fig)
            return str(out)
        except Exception as e:
            self.log.warning("waterfall rendering failed: %s", e)
            return None
