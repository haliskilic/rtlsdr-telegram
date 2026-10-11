"""Daily summary report (feature B, spec section 6).

Sends an automatic summary every day at the configured local time. Content:
event counts per category; most active event types; unique aircraft/vessel/
sensor counts; the most notable events; total recorded audio; satellite image
count; new devices/cells/anomalies; uptime and error summary. Optional CSV.
"""
from __future__ import annotations

import csv
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .events import Event, Category, Attachment, fmt_duration, PRIO_LOW, CATEGORY_EMOJI, LEGACY_TR_TO_KEY
from .i18n import t


class SummaryReporter:
    def __init__(self, cfg, storage, dispatcher, logger, start_time):
        self.cfg = cfg
        self.st = storage
        self.dispatcher = dispatcher
        self.log = logger
        self.start_time = start_time
        sm = cfg.section("summary")
        self.enabled = bool(sm.get("enabled", True))
        self.time_str = sm.get("time", "09:00")
        self.attach_csv = bool(sm.get("attach_csv", True))
        self.top_n = int(sm.get("top_n", 5))
        try:
            self.tz = ZoneInfo(cfg.get("timezone", "Europe/Istanbul"))
        except Exception:
            self.tz = ZoneInfo("UTC")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if not self.enabled:
            self.log.info("daily summary disabled")
            return
        self._thread = threading.Thread(target=self._loop, name="summary", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _next_fire(self) -> float:
        try:
            hh, mm = [int(x) for x in self.time_str.split(":")]
        except ValueError:
            hh, mm = 9, 0
        now = datetime.now(self.tz)
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.timestamp()

    def _loop(self):
        while not self._stop.is_set():
            fire = self._next_fire()
            wait = max(5, fire - time.time())
            self.log.info("next daily summary: %s", datetime.fromtimestamp(fire, self.tz).strftime("%Y-%m-%d %H:%M"))
            if self._stop.wait(wait):
                return
            try:
                self.generate_and_send()
            except Exception as e:
                self.log.exception("daily summary error: %s", e)

    # ------------------------------------------------------------ generation
    @staticmethod
    def _cat_label(raw: str) -> tuple[str, str]:
        key = LEGACY_TR_TO_KEY.get(raw, raw)
        try:
            c = Category(key)
            return CATEGORY_EMOJI.get(c, "•"), c.label
        except ValueError:
            return "•", raw

    def generate_and_send(self, manual: bool = False, reply: dict | None = None):
        now = time.time()
        t0 = now - 86400
        last = self.st.kv_get("last_summary_ts")
        if not manual and last:
            t0 = max(t0, float(last) - 60)
        period_h = (now - t0) / 3600

        total = self.st.events_count(t0, now)
        by_cat = self.st.count_by("category", t0, now)
        by_type = self.st.count_by("event_type", t0, now)
        top = self.st.top_events(t0, now, self.top_n)
        audio_s = self.st.audio_total_s(t0, now)
        photos = self.st.photos_total(t0, now)
        err_n = self.st.error_count(t0, now)
        errs = self.st.errors_between(t0, now)

        uniq = {
            t("sum.u.aircraft"): self.st.registry_count("aircraft", t0, now),
            t("sum.u.vessels"): self.st.registry_count("ship", t0, now),
            t("sum.u.ism"): self.st.registry_count("ism_device", t0, now),
            t("sum.u.aprs"): self.st.registry_count("aprs_station", t0, now),
            t("sum.u.cells"): self.st.registry_count("gsm_cell", t0, now),
        }
        new_devices = self.st.registry_count("ism_device", t0, now, new_only=True)
        new_cells = self.st.registry_count("gsm_cell", t0, now, new_only=True)
        new_anom = self.st.registry_count("spectrum_anom", t0, now, new_only=True)

        lines = [f"📅 <b>{t('sum.title')}</b> — {datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')}",
                 f"<i>{t('sum.period', h=f'{period_h:.0f}')}</i>", ""]
        lines.append(f"📊 <b>{t('sum.total')}:</b> {total}")
        if by_cat:
            lines.append("")
            lines.append(f"<b>{t('sum.by_cat')}:</b>")
            for cat, n in by_cat:
                emoji, label = self._cat_label(cat)
                lines.append(f"  {emoji} {label}: {n}")
        if by_type:
            lines.append("")
            lines.append(f"<b>{t('sum.top_types')}:</b>")
            for bt, n in by_type[:5]:
                lines.append(f"  • {bt}: {n}")
        lines.append("")
        lines.append(f"<b>{t('sum.unique')}:</b>")
        lines.append("  " + " · ".join(f"{k}: {v}" for k, v in uniq.items() if v))
        if new_devices or new_cells or new_anom:
            lines.append("")
            lines.append(f"<b>{t('sum.new_period')}:</b>")
            if new_devices:
                lines.append("  📡 " + t("sum.new_devices", n=new_devices))
            if new_cells:
                lines.append("  📶 " + t("sum.new_cells", n=new_cells))
            if new_anom:
                lines.append("  🔭 " + t("sum.new_anom", n=new_anom))
        lines.append("")
        lines.append(f"🎙️ {t('sum.audio')}: {fmt_duration(audio_s)}")
        lines.append(f"🛰️ {t('sum.images')}: {photos}")
        if top:
            lines.append("")
            lines.append(f"<b>{t('sum.top_events', n=len(top))}:</b>")
            for r in top:
                when = datetime.fromtimestamp(r["ts"], tz=timezone.utc).astimezone(self.tz).strftime("%H:%M")
                sig = f" ({r['signal']})" if r["signal"] else ""
                lines.append(f"  • {when} {r['event_type']}: {(r['summary'] or '')[:70]}{sig}")
        lines.append("")
        lines.append(f"⏱️ {t('sum.uptime')}: {self._uptime()}")
        lines.append(f"⚠️ {t('sum.errors')}: {err_n}" + (f" ({', '.join(f'{x}:{n}' for x, n in errs[:4])})" if errs else ""))

        ev = Event(t("evt.summary"), Category.SISTEM, band="—",
                   summary=t("sum.summary_line", n=total, audio=fmt_duration(audio_s), img=photos),
                   body="\n".join(lines), priority=PRIO_LOW, target="summary")
        ev.silent = True
        if reply:
            ev.reply_to = reply
        if self.attach_csv:
            csv_path = self._write_csv(t0, now)
            if csv_path:
                ev.attachments.append(Attachment("document", csv_path, caption=t("sum.csv_caption"), delete_after=True))
        self.dispatcher.submit(ev)
        self.st.kv_set("last_summary_ts", now)
        self.log.info("daily summary sent (%d events)", total)

    def _write_csv(self, t0, t1) -> str | None:
        rows = self.st.events_between(t0, t1)
        if not rows:
            return None
        path = self.cfg.data_dir / "tmp" / f"summary_{datetime.now(self.tz).strftime('%Y%m%d_%H%M')}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["time_utc", "time_local", "category", "event_type", "freq_mhz",
                            "summary", "signal", "lat", "lon", "priority"])
                for r in rows:
                    dt = datetime.fromtimestamp(r["ts"], tz=timezone.utc)
                    w.writerow([dt.strftime("%Y-%m-%d %H:%M:%S"),
                                dt.astimezone(self.tz).strftime("%Y-%m-%d %H:%M:%S"),
                                self._cat_label(r["category"])[1], r["event_type"], r["freq_mhz"] or "",
                                (r["summary"] or "").replace("\n", " "), r["signal"] or "",
                                r["lat"] or "", r["lon"] or "", r["priority"]])
            return str(path)
        except OSError as e:
            self.log.warning("CSV write failed: %s", e)
            return None

    def _uptime(self) -> str:
        s = int(time.time() - self.start_time)
        d, r = divmod(s, 86400)
        h, r = divmod(r, 3600)
        m, _ = divmod(r, 60)
        return (f"{d}d " if d else "") + f"{h}h {m}m"
