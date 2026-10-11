"""Günlük özet raporu (Özellik B, madde 6).

Her gün yapılandırılan saatte (örn. 09:00) otomatik özet gönderir. İçerik:
kategori bazında olay sayıları; en aktif bantlar; benzersiz uçak/gemi/sensör
sayısı; en güçlü/ilginç 5 olay; toplam ses kaydı süresi; uydu görüntü sayısı;
yeni cihaz/hücre/anomali listesi; çalışma süresi ve hata özeti. İsteğe bağlı
CSV eki üretir.
"""
from __future__ import annotations

import csv
import io
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .events import Event, Category, Attachment, fmt_duration, PRIO_LOW


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
            self.log.info("günlük özet kapalı")
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
        # son gönderim zamanını DB'den al; kaçırılan günü telafi etme, sıradaki saati bekle
        while not self._stop.is_set():
            fire = self._next_fire()
            wait = max(5, fire - time.time())
            self.log.info("sonraki günlük özet: %s", datetime.fromtimestamp(fire, self.tz).strftime("%Y-%m-%d %H:%M"))
            if self._stop.wait(wait):
                return
            try:
                self.generate_and_send()
            except Exception as e:
                self.log.exception("günlük özet hatası: %s", e)

    # --------------------------------------------------------------- üretim
    def generate_and_send(self, manual: bool = False, reply: dict | None = None):
        now = time.time()
        t0 = now - 86400
        last = self.st.kv_get("last_summary_ts")
        if not manual and last:
            t0 = max(t0, float(last) - 60)
        period_h = (now - t0) / 3600

        total = self.st.events_count(t0, now)
        by_cat = self.st.count_by("category", t0, now)
        by_band = self.st.count_by("event_type", t0, now)
        top = self.st.top_events(t0, now, self.top_n)
        audio_s = self.st.audio_total_s(t0, now)
        photos = self.st.photos_total(t0, now)
        err_n = self.st.error_count(t0, now)
        errs = self.st.errors_between(t0, now)

        uniq = {
            "uçak": self.st.registry_count("aircraft", t0, now),
            "gemi": self.st.registry_count("ship", t0, now),
            "ISM cihaz": self.st.registry_count("ism_device", t0, now),
            "APRS ist.": self.st.registry_count("aprs_station", t0, now),
            "GSM hücre": self.st.registry_count("gsm_cell", t0, now),
        }
        new_devices = self.st.registry_count("ism_device", t0, now, new_only=True)
        new_cells = self.st.registry_count("gsm_cell", t0, now, new_only=True)
        new_anom = self.st.registry_count("spectrum_anom", t0, now, new_only=True)

        lines = [f"📅 <b>Günlük Özet</b> — {datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')}",
                 f"<i>Kapsanan süre: son {period_h:.0f} saat</i>", ""]
        lines.append(f"📊 <b>Toplam olay:</b> {total}")
        if by_cat:
            lines.append("")
            lines.append("<b>Kategori bazında:</b>")
            for cat, n in by_cat:
                emoji = self._cat_emoji(cat)
                lines.append(f"  {emoji} {cat}: {n}")
        if by_band:
            lines.append("")
            lines.append("<b>En aktif olay türleri:</b>")
            for bt, n in by_band[:5]:
                lines.append(f"  • {bt}: {n}")
        lines.append("")
        lines.append("<b>Benzersiz tespitler:</b>")
        lines.append("  " + " · ".join(f"{k}: {v}" for k, v in uniq.items() if v))
        if new_devices or new_cells or new_anom:
            lines.append("")
            lines.append("<b>Yeni bu dönem:</b>")
            if new_devices:
                lines.append(f"  📡 {new_devices} yeni ISM cihaz")
            if new_cells:
                lines.append(f"  📶 {new_cells} yeni GSM hücre")
            if new_anom:
                lines.append(f"  🔭 {new_anom} yeni spektrum anomali")
        lines.append("")
        lines.append(f"🎙️ Toplam ses kaydı: {fmt_duration(audio_s)}")
        lines.append(f"🛰️ Uydu/görüntü: {photos}")
        if top:
            lines.append("")
            lines.append(f"<b>En dikkat çeken {len(top)} olay:</b>")
            for r in top:
                when = datetime.fromtimestamp(r["ts"], tz=timezone.utc).astimezone(self.tz).strftime("%H:%M")
                sig = f" ({r['signal']})" if r["signal"] else ""
                lines.append(f"  • {when} {r['event_type']}: {(r['summary'] or '')[:70]}{sig}")
        lines.append("")
        lines.append(f"⏱️ Çalışma süresi: {self._uptime()}")
        lines.append(f"⚠️ Hata: {err_n}" + (f" ({', '.join(f'{t}:{n}' for t, n in errs[:4])})" if errs else ""))

        ev = Event("Günlük Özet", Category.SISTEM, band="—",
                   summary=f"{total} olay, {fmt_duration(audio_s)} ses, {photos} görüntü",
                   body="\n".join(lines), priority=PRIO_LOW, target="summary")
        ev.silent = True
        if reply:
            ev.reply_to = reply
        if self.attach_csv:
            csv_path = self._write_csv(t0, now)
            if csv_path:
                ev.attachments.append(Attachment("document", csv_path, caption="Olay dökümü (CSV)", delete_after=True))
        self.dispatcher.submit(ev)
        self.st.kv_set("last_summary_ts", now)
        self.log.info("günlük özet gönderildi (%d olay)", total)

    def _write_csv(self, t0, t1) -> str | None:
        rows = self.st.events_between(t0, t1)
        if not rows:
            return None
        path = self.cfg.data_dir / "tmp" / f"ozet_{datetime.now(self.tz).strftime('%Y%m%d_%H%M')}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["zaman_utc", "zaman_yerel", "kategori", "olay_turu", "frekans_mhz",
                            "ozet", "sinyal", "enlem", "boylam", "oncelik"])
                for r in rows:
                    dt = datetime.fromtimestamp(r["ts"], tz=timezone.utc)
                    w.writerow([dt.strftime("%Y-%m-%d %H:%M:%S"),
                                dt.astimezone(self.tz).strftime("%Y-%m-%d %H:%M:%S"),
                                r["category"], r["event_type"], r["freq_mhz"] or "",
                                (r["summary"] or "").replace("\n", " "), r["signal"] or "",
                                r["lat"] or "", r["lon"] or "", r["priority"]])
            return str(path)
        except OSError as e:
            self.log.warning("CSV yazılamadı: %s", e)
            return None

    @staticmethod
    def _cat_emoji(cat: str) -> str:
        parsed = Category.parse(cat)
        from .events import CATEGORY_EMOJI
        return CATEGORY_EMOJI.get(parsed, "•") if parsed else "•"

    def _uptime(self) -> str:
        s = int(time.time() - self.start_time)
        d, r = divmod(s, 86400)
        h, r = divmod(r, 3600)
        m, _ = divmod(r, 60)
        return (f"{d}g " if d else "") + f"{h}s {m}dk"
