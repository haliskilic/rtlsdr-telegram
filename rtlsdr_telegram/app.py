"""Uygulama birleştirme ve yaşam döngüsü.

Tüm bileşenleri kurar, birbirine bağlar, başlatır ve sinyalle düzgün kapatır.
Bir hedef/bileşen çökerse diğerleri etkilenmez (madde 9); hatalar loglanır.
"""
from __future__ import annotations

import signal
import threading
import time
from datetime import datetime, timezone

from .config import Config, load_config
from .logging_setup import setup_logging
from .storage import Storage
from .sdr import SdrManager
from .audio import AudioRecorder
from .transcription import Transcriber, TranscriptionWorker
from .telegram import TelegramClient, TelegramError
from .dispatcher import Dispatcher
from .scheduler import Scheduler
from .commands import CommandHandler
from .summary import SummaryReporter
from .satellites import SatellitePredictor
from .targets import build_targets, TargetContext
from .events import Event, Category, PRIO_IMPORTANT


class Application:
    def __init__(self, config_path: str | None = None):
        self.cfg: Config = load_config(config_path)
        self.cfg.ensure_dirs()
        self.log = setup_logging(self.cfg.log_dir, self.cfg.get("paths.log_level", "INFO"))
        self.start_time = time.time()
        self._stop = threading.Event()
        self.components: list = []

    # --------------------------------------------------------------- kurulum
    def build(self):
        cfg = self.cfg
        self.log.info("=== rtlsdr-telegram başlatılıyor (platform: %s) ===", cfg.platform)
        problems = cfg.validate()
        if problems:
            for p in problems:
                self.log.error("YAPILANDIRMA: %s", p)
            if not cfg.get("telegram.token") or not cfg.get("telegram.chat_id"):
                raise SystemExit("Telegram token/chat_id eksik — config.yaml doldurulmalı.")

        self.storage = Storage(cfg.data_dir / "rtlsdr.db")
        self.client = TelegramClient(cfg.get("telegram.token"), self.log.getChild("tg"),
                                     proxy=cfg.get("telegram.proxy", ""))
        self.dispatcher = Dispatcher(cfg, self.storage, self.client, self.log.getChild("disp"))
        self.sdr = SdrManager(cfg, self.log.getChild("sdr"))
        self.audio = AudioRecorder(cfg, self.sdr, self.log.getChild("audio"))
        self.transcriber = Transcriber(cfg, self.log.getChild("asr"))
        self.tworker = TranscriptionWorker(self.transcriber, self.dispatcher, self.storage,
                                           self.log.getChild("asr"))
        self.dispatcher.transcriber = self.transcriber

        self.predictor = SatellitePredictor(cfg, self.log.getChild("sat"))

        ctx = TargetContext(cfg=cfg, sdr=self.sdr, storage=self.storage, dispatcher=self.dispatcher,
                            transcriber=self.transcriber, logger=self.log.getChild("tgt"),
                            audio=self.audio, transcription_worker=self.tworker)
        self.targets = build_targets(ctx)
        # uydu hedeflerine tahminciyi bağla
        for t in self.targets:
            if hasattr(t, "predictor"):
                t.predictor = self.predictor

        self.scheduler = Scheduler(cfg, self.sdr, self.targets, self.log.getChild("sched"),
                                   self.dispatcher, self.storage)
        self.scheduler._recorder = self.audio
        self.summary = SummaryReporter(cfg, self.storage, self.dispatcher, self.log.getChild("sum"),
                                       self.start_time)
        self.commands = CommandHandler(cfg, self.client, self.scheduler, self.storage, self.dispatcher,
                                       self.summary, self.log.getChild("cmd"), self.start_time)

        self.components = [self.dispatcher, self.tworker, self.scheduler, self.commands, self.summary]

    # --------------------------------------------------------------- çalıştır
    def run(self):
        self.build()
        self._verify_bot()
        # bileşenleri başlat
        self.dispatcher.start()
        self.tworker.start()
        self.scheduler.start()
        self.commands.start()
        self.summary.start()
        self._startup_message()
        self._install_signals()
        self._maintenance_loop()

    def _verify_bot(self):
        try:
            me = self.client.get_me()
            self.log.info("Telegram bot: @%s (%s)", me.get("username"), me.get("first_name"))
        except TelegramError as e:
            self.log.error("Telegram bot doğrulanamadı: %s — token'ı kontrol edin", e)

    def _startup_message(self):
        if not self.cfg.get("telegram.startup_message", True):
            return
        dev = self.sdr.probe()
        active = [t for t in self.targets if t.enabled]
        missing = []
        for t in active:
            ok, msg = t.tools_available()
            if not ok:
                missing.append(f"{t.KEY} ({msg})")
        lines = [
            f"🟢 <b>RTL-SDR İzleme sistemi başladı</b>",
            f"İstasyon: {self.cfg.get('station.name', '—')}",
            f"Platform: {self.cfg.platform}",
            f"Dongle  : {'✅ ' + dev.detail if dev.present else '❌ bulunamadı — takılı mı?'}",
            f"Aktif hedef: {len(active)}/{len(self.targets)}",
            f"Transkripsiyon: {self.transcriber.engine if self.transcriber.available else 'kapalı'}",
            f"Uydu tahmini: {'açık' if self.predictor.available else 'kapalı (skyfield yok)'}",
        ]
        if missing:
            lines.append("⚠️ Araç eksik: " + ", ".join(missing[:6]))
        lines.append("Komutlar için /yardim")
        ev = Event("Sistem Başladı", Category.SISTEM, summary="Sistem başlatıldı",
                   body="\n".join(lines), priority=PRIO_IMPORTANT, target="system")
        ev.silent = True
        self.dispatcher.submit(ev)

    def _install_signals(self):
        def handler(signum, frame):
            self.log.info("sinyal %s alındı, kapatılıyor…", signum)
            self._stop.set()
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(s, handler)
            except (ValueError, OSError):
                pass

    def _maintenance_loop(self):
        retention = int(self.cfg.get("paths.retention_days", 14))
        last_cleanup = 0.0
        last_tle = 0.0
        tle_refresh = float(self.cfg.get("satellites.refresh_min", 60)) * 60
        try:
            while not self._stop.is_set():
                now = time.time()
                if now - last_cleanup > 3600:
                    last_cleanup = now
                    self._cleanup(retention)
                if self.predictor.available and now - last_tle > tle_refresh:
                    last_tle = now
                self._stop.wait(30)
        finally:
            self.shutdown()

    def _cleanup(self, retention_days: int):
        try:
            import os
            n, paths = self.storage.cleanup(retention_days)
            removed = 0
            for p in paths:
                try:
                    if p and os.path.exists(p):
                        os.unlink(p)
                        removed += 1
                except OSError:
                    pass
            if removed:
                self.log.info("temizlik: %d eski kayıt dosyası silindi", removed)
        except Exception as e:
            self.log.warning("temizlik hatası: %s", e)

    def shutdown(self):
        self.log.info("bileşenler durduruluyor…")
        for comp in reversed(self.components):
            try:
                comp.stop()
            except Exception as e:
                self.log.warning("durdurma hatası (%s): %s", comp, e)
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self.storage.close()
        except Exception:
            pass
        self.log.info("=== kapatıldı ===")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="RTL-SDR çok bantlı izleme ve Telegram bildirim sistemi")
    ap.add_argument("-c", "--config", help="config.yaml yolu")
    ap.add_argument("--check", action="store_true", help="yapılandırma ve araçları kontrol et, çık")
    ap.add_argument("--test-telegram", action="store_true", help="Telegram'a test mesajı gönder, çık")
    args = ap.parse_args(argv)

    if args.check:
        return _run_check(args.config)
    if args.test_telegram:
        return _run_test_telegram(args.config)

    app = Application(args.config)
    app.run()
    return 0


def _run_check(config_path):
    from .sdr import SdrManager
    cfg = load_config(config_path)
    cfg.ensure_dirs()
    log = setup_logging(cfg.log_dir, "INFO")
    print(f"Platform: {cfg.platform}")
    print("Yapılandırma sorunları:", cfg.validate() or "yok")
    sdr = SdrManager(cfg, log)
    info = sdr.probe()
    print(f"Dongle: {'VAR' if info.present else 'YOK'} — {info.detail}")
    ctx = TargetContext(cfg, sdr, None, None, None, log, None)
    targets = build_targets(ctx)
    print(f"\nHedefler ({len(targets)}):")
    for t in targets:
        ok, msg = t.tools_available()
        state = "aktif" if t.enabled else "kapalı"
        print(f"  {'✓' if ok else '✗'} {t.KEY:16s} [{state:6s}] {t.display_name()}" + (f"  — {msg}" if msg else ""))
    pred = SatellitePredictor(cfg, log)
    print(f"\nUydu tahmini (skyfield): {'açık' if pred.available else 'KAPALI'}")
    tr = Transcriber(cfg, log)
    print(f"Transkripsiyon: {tr.engine} ({'kullanılabilir' if tr.available else 'kapalı'})")
    return 0


def _run_test_telegram(config_path):
    cfg = load_config(config_path)
    cfg.ensure_dirs()
    log = setup_logging(cfg.log_dir, "INFO")
    client = TelegramClient(cfg.get("telegram.token"), log)
    try:
        me = client.get_me()
        print(f"Bot: @{me.get('username')}")
        ids = client.send_message(cfg.get("telegram.chat_id"),
                                  "✅ <b>rtlsdr-telegram test mesajı</b>\nBağlantı çalışıyor.",
                                  thread_id=cfg.get("telegram.thread_id") or None)
        print(f"Mesaj gönderildi: {ids}")
    except TelegramError as e:
        print(f"HATA: {e}")
        return 1
    finally:
        client.close()
    return 0
