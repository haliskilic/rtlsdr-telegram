"""Application wiring and lifecycle.

Builds all components, connects them, starts them and shuts down cleanly on a
signal. A crashing target/component does not affect the others (spec section 9);
errors are logged.
"""
from __future__ import annotations

import os
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
from .events import Event, Category, PRIO_IMPORTANT, LEGACY_TR_TO_KEY
from .i18n import t, set_language


def _ensure_home() -> None:
    """systemd does not export $HOME for root services; SatDump aborts without it."""
    if not os.environ.get("HOME"):
        try:
            os.environ["HOME"] = os.path.expanduser("~")
        except Exception:
            pass


class Application:
    def __init__(self, config_path: str | None = None):
        _ensure_home()
        self.cfg: Config = load_config(config_path)
        self.cfg.ensure_dirs()
        self.log = setup_logging(self.cfg.log_dir, self.cfg.get("paths.log_level", "INFO"))
        self.language = set_language(self.cfg.get("language", "en"))
        self.start_time = time.time()
        self._stop = threading.Event()
        self.components: list = []

    # --------------------------------------------------------------- kurulum
    def build(self):
        cfg = self.cfg
        self.log.info("=== rtlsdr-telegram starting (platform: %s, language: %s) ===", cfg.platform, self.language)
        problems = cfg.validate()
        if problems:
            for p in problems:
                self.log.error("CONFIG: %s", p)
            if not cfg.get("telegram.token") or not cfg.get("telegram.chat_id"):
                raise SystemExit("Telegram token/chat_id missing — fill in config.yaml.")

        self.storage = Storage(cfg.data_dir / "rtlsdr.db")
        migrated = self.storage.migrate_categories(LEGACY_TR_TO_KEY)
        if migrated:
            self.log.info("migrated %d legacy category values", migrated)
        # per-tool log rotation limits from config
        from . import proc as _proc
        _proc.LOG_MAX_BYTES = int(float(cfg.get("paths.tool_log_max_mb", 5)) * 1024 * 1024)
        _proc.LOG_BACKUPS = int(cfg.get("paths.tool_log_backups", 2))
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
        # attach the pass predictor to the satellite targets
        for x in self.targets:
            if hasattr(x, "predictor"):
                x.predictor = self.predictor

        self.scheduler = Scheduler(cfg, self.sdr, self.targets, self.log.getChild("sched"),
                                   self.dispatcher, self.storage)
        self.scheduler._recorder = self.audio
        self.scheduler.tworker = self.tworker          # /scan recordings are transcribed too
        self.dispatcher.scheduler = self.scheduler     # mute checks
        self.summary = SummaryReporter(cfg, self.storage, self.dispatcher, self.log.getChild("sum"),
                                       self.start_time)
        self.commands = CommandHandler(cfg, self.client, self.scheduler, self.storage, self.dispatcher,
                                       self.summary, self.log.getChild("cmd"), self.start_time)

        self.components = [self.dispatcher, self.tworker, self.scheduler, self.commands, self.summary]

    # --------------------------------------------------------------- run
    def run(self):
        self.build()
        self._verify_bot()
        # start components
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
            self.log.error("Telegram bot verification failed: %s — check the token", e)

    def _startup_message(self):
        if not self.cfg.get("telegram.startup_message", True):
            return
        dev = self.sdr.probe()
        active = [x for x in self.targets if x.enabled]
        missing = []
        for x in active:
            ok, msg = x.tools_available()
            if not ok:
                missing.append(f"{x.KEY} ({msg})")
        lines = [
            f"🟢 <b>{t('sys.started_title')}</b>",
            f"{t('sys.station')}: {self.cfg.get('station.name', '—')}",
            f"{t('sys.platform')}: {self.cfg.platform}",
            f"{t('sys.dongle')}: {'✅ ' + dev.detail if dev.present else '❌ ' + t('sys.dongle_missing')}",
            f"{t('sys.active_targets')}: {len(active)}/{len(self.targets)}",
            f"{t('sys.transcription')}: {self.transcriber.engine if self.transcriber.available else t('sys.off')}",
            f"{t('sys.sat_pred')}: {'on' if self.predictor.available else t('sys.sat_pred_off')}",
        ]
        if missing:
            lines.append(f"{t('sys.missing_tools')}: " + ", ".join(missing[:6]))
        lines.append(t("sys.help_hint"))
        ev = Event(t("evt.system_started"), Category.SISTEM, summary=t("sys.started_summary"),
                   body="\n".join(lines), priority=PRIO_IMPORTANT, target="system")
        ev.silent = True
        self.dispatcher.submit(ev)

    def _install_signals(self):
        def handler(signum, frame):
            self.log.info("signal %s received, shutting down…", signum)
            self._stop.set()
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(s, handler)
            except (ValueError, OSError):
                pass

    def _maintenance_loop(self):
        retention = self.cfg.retention_days()
        self.log.info("retention: %d days (recordings/events/logs), registry x%s",
                      retention, self.cfg.get("paths.registry_retention_multiplier", 3))
        heartbeat_h = float(self.cfg.get("telegram.heartbeat_hours", 0) or 0)
        last_cleanup = 0.0
        last_heartbeat = time.time()
        try:
            while not self._stop.is_set():
                now = time.time()
                if now - last_cleanup > 3600:
                    last_cleanup = now
                    self._cleanup(retention)
                if heartbeat_h > 0 and now - last_heartbeat > heartbeat_h * 3600:
                    last_heartbeat = now
                    self._heartbeat()
                self._stop.wait(30)
        finally:
            self.shutdown()

    def _heartbeat(self):
        try:
            st = self.scheduler.status_dict()
            t0 = time.time() - 3600
            n = self.storage.events_count(t0, time.time())
            body = t("sys.heartbeat_body", d=('✅' if st['device_present'] else '❌'),
                     cur=(st['current_name'] or t('status.idle')), n=n, q=st['queue_len'])
            ev = Event(t("evt.heartbeat"), Category.SISTEM, summary=body, body=body, priority=8, target="system")
            ev.silent = True
            self.dispatcher.submit(ev)
        except Exception as e:
            self.log.debug("heartbeat failed: %s", e)

    def _cleanup(self, retention_days: int):
        try:
            import os
            n, paths = self.storage.cleanup(retention_days,
                                            int(self.cfg.get("paths.registry_retention_multiplier", 3)))
            removed = 0
            for p in paths:
                try:
                    if p and os.path.exists(p):
                        os.unlink(p)
                        removed += 1
                except OSError:
                    pass
            # files not tracked in the DB (waterfall/satellite PNG, temp WAV) — by mtime
            cutoff = time.time() - retention_days * 86400
            for base in (self.cfg.recordings_dir, self.cfg.data_dir / "tmp"):
                try:
                    for f in base.rglob("*"):
                        if f.is_file() and f.stat().st_mtime < cutoff:
                            f.unlink()
                            removed += 1
                except OSError:
                    pass
            if removed:
                self.log.info("cleanup: %d old files deleted", removed)
            self._disk_guard()
            self._maybe_vacuum()
        except Exception as e:
            self.log.warning("cleanup error: %s", e)

    def _disk_guard(self):
        """Below min_free_disk_pct: prune the oldest recordings until above threshold; warn once a day."""
        import shutil
        min_pct = float(self.cfg.get("paths.min_free_disk_pct", 10) or 0)
        if min_pct <= 0:
            return
        base = self.cfg.recordings_dir
        try:
            u = shutil.disk_usage(str(base))
        except OSError:
            return
        free_pct = 100.0 * u.free / max(1, u.total)
        if free_pct >= min_pct:
            return
        files = sorted((f for f in base.rglob("*") if f.is_file()), key=lambda f: f.stat().st_mtime)
        removed = 0
        for f in files:
            try:
                f.unlink()
                removed += 1
            except OSError:
                continue
            if removed % 10 == 0:
                u = shutil.disk_usage(str(base))
                if 100.0 * u.free / max(1, u.total) >= min_pct + 2:
                    break
        self.log.warning("disk guard: %.1f%% free, pruned %d oldest recording files", free_pct, removed)
        last = float(self.storage.kv_get("disk_warned_ts", 0) or 0)
        if time.time() - last > 86400:
            self.storage.kv_set("disk_warned_ts", time.time())
            from .i18n import t
            ev = Event(t("evt.disk_warning"), Category.SISTEM, priority=PRIO_IMPORTANT, target="system",
                       summary=t("sys.disk_warning_summary", pct=f"{free_pct:.1f}", n=removed),
                       body=t("sys.disk_warning_body", pct=f"{free_pct:.1f}", n=removed, min=int(min_pct)))
            self.dispatcher.submit(ev)

    def _maybe_vacuum(self):
        days = float(self.cfg.get("paths.db_vacuum_days", 30) or 0)
        if days <= 0:
            return
        last = float(self.storage.kv_get("last_vacuum_ts", 0) or 0)
        if time.time() - last < days * 86400:
            return
        before = self.storage.db_size_bytes()
        self.storage.vacuum()
        self.storage.kv_set("last_vacuum_ts", time.time())
        self.log.info("database VACUUM: %.1f MB -> %.1f MB", before / 1e6, self.storage.db_size_bytes() / 1e6)

    def shutdown(self):
        self.log.info("stopping components…")
        try:
            if self.cfg.get("telegram.startup_message", True):
                self.client.send_message(self.cfg.get("telegram.chat_id"),
                                         f"🔴 <b>{t('sys.stopping')}</b>",
                                         thread_id=self.cfg.get("telegram.thread_id") or None, silent=True)
        except Exception:
            pass
        for comp in reversed(self.components):
            try:
                comp.stop()
            except Exception as e:
                self.log.warning("stop error (%s): %s", comp, e)
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self.storage.close()
        except Exception:
            pass
        self.log.info("=== stopped ===")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="RTL-SDR multi-band monitoring and Telegram notification system")
    ap.add_argument("-c", "--config", help="path to config.yaml")
    ap.add_argument("--check", action="store_true", help="check configuration, tools and dongle, then exit")
    ap.add_argument("--test-telegram", action="store_true", help="send a test message to Telegram, then exit")
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
    set_language(cfg.get("language", "en"))
    print(f"Platform: {cfg.platform}  Language: {cfg.get('language', 'en')}")
    print("Configuration problems:", cfg.validate() or "none")
    sdr = SdrManager(cfg, log)
    info = sdr.probe()
    print(f"Dongle: {'PRESENT' if info.present else 'MISSING'} — {info.detail}")
    ctx = TargetContext(cfg, sdr, None, None, None, log, None)
    targets = build_targets(ctx)
    print(f"\nTargets ({len(targets)}):")
    for x in targets:
        ok, msg = x.tools_available()
        state = "on" if x.enabled else "off"
        print(f"  {'✓' if ok else '✗'} {x.KEY:16s} [{state:3s}] {x.display_name()}" + (f"  — {msg}" if msg else ""))
    pred = SatellitePredictor(cfg, log)
    print(f"\nSatellite prediction (skyfield): {'on' if pred.available else 'OFF'}")
    tr = Transcriber(cfg, log)
    print(f"Transcription: {tr.engine} ({'available' if tr.available else 'off'})")
    return 0


def _run_test_telegram(config_path):
    cfg = load_config(config_path)
    cfg.ensure_dirs()
    log = setup_logging(cfg.log_dir, "INFO")
    set_language(cfg.get("language", "en"))
    client = TelegramClient(cfg.get("telegram.token"), log)
    try:
        me = client.get_me()
        print(f"Bot: @{me.get('username')}")
        ids = client.send_message(cfg.get("telegram.chat_id"),
                                  f"✅ <b>rtlsdr-telegram — {t('evt.test')}</b>\n{t('sys.test_body')}",
                                  thread_id=cfg.get("telegram.thread_id") or None)
        print(f"Message sent: {ids}")
    except TelegramError as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        client.close()
    return 0
