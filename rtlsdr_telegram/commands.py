"""Telegram command handling (feature C, spec section 7).

Commands are received with getUpdates. Only administrators listed in the
configuration may run them. Turkish and English command names both work,
regardless of the selected UI language:

  /status   /durum       active targets, current band, CPU/temperature, uptime
  /scan     /tara        listen to a frequency temporarily (MHz) [+ seconds] [am|fm]
  /mute     /sustur      mute a category temporarily
  /unmute   /ac          unmute a category
  /priority /oncelik     move a target to the front of the scan cycle
  /summary  /ozet        generate the daily summary now
  /recordings /kayitlar  resend the last n audio recordings
  /list     /liste       list all targets and their state
  /passes   /gecisler    upcoming satellite/ISS passes
  /help     /yardim      command list
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .events import Category
from .i18n import t
from .telegram import TelegramError


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    out = []
    if d:
        out.append(f"{d}d")
    if h or d:
        out.append(f"{h}h")
    out.append(f"{m}m")
    return " ".join(out)


def _category_list() -> str:
    return ", ".join(c.label for c in Category if c != Category.SISTEM)


class CommandHandler:
    def __init__(self, cfg, client, scheduler, storage, dispatcher, summary, logger, start_time):
        self.cfg = cfg
        self.client = client
        self.sched = scheduler
        self.st = storage
        self.dispatcher = dispatcher
        self.summary = summary
        self.log = logger
        self.start_time = start_time
        tg = cfg.section("telegram")
        self.admins = set(int(a) for a in (tg.get("admins") or []) if str(a).strip())
        self.chat_id = tg.get("chat_id")
        self.thread_id = tg.get("thread_id") or None
        self.allow_private = tg.get("allow_private_admin_commands", True)
        self.any_topic = tg.get("commands_from_any_topic", True)
        self.unauthorized_reply = tg.get("unauthorized_reply", True)
        self.poll_timeout = int(tg.get("poll_timeout_s", 30))
        try:
            self.tz = ZoneInfo(cfg.get("timezone", "Europe/Istanbul"))
        except Exception:
            self.tz = timezone.utc
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = self.st.kv_get("tg_update_offset", 0)
        self.handlers = {
            "durum": self.cmd_status, "status": self.cmd_status,
            "tara": self.cmd_scan, "scan": self.cmd_scan,
            "sustur": self.cmd_mute, "mute": self.cmd_mute,
            "ac": self.cmd_unmute, "aç": self.cmd_unmute, "unmute": self.cmd_unmute,
            "oncelik": self.cmd_priority, "öncelik": self.cmd_priority, "priority": self.cmd_priority,
            "ozet": self.cmd_summary, "özet": self.cmd_summary, "summary": self.cmd_summary,
            "kayitlar": self.cmd_recordings, "kayıtlar": self.cmd_recordings, "recordings": self.cmd_recordings,
            "liste": self.cmd_list, "list": self.cmd_list,
            "yardim": self.cmd_help, "yardım": self.cmd_help, "help": self.cmd_help, "start": self.cmd_help,
            "gecisler": self.cmd_passes, "geçişler": self.cmd_passes, "passes": self.cmd_passes,
        }

    # --------------------------------------------------------------- lifecycle
    def start(self):
        self._thread = threading.Thread(target=self._loop, name="commands", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        self.log.info("command listener started (admins: %s)", self.admins or "NONE")
        while not self._stop.is_set():
            try:
                updates = self.client.get_updates(offset=self._offset or None, timeout=self.poll_timeout)
            except TelegramError as e:
                self.log.debug("getUpdates error: %s", e)
                self._stop.wait(5)
                continue
            except Exception as e:
                self.log.warning("getUpdates unexpected error: %s", e)
                self._stop.wait(5)
                continue
            for up in updates:
                self._offset = up["update_id"] + 1
                try:
                    self._handle_update(up)
                except Exception as e:
                    self.log.exception("command handling error: %s", e)
            if updates:
                self.st.kv_set("tg_update_offset", self._offset)

    # ------------------------------------------------------- auth / dispatch
    def _handle_membership(self, upd: dict) -> None:
        """The bot was added to / removed from a chat. Leave every chat that is not
        the configured group so strangers cannot use the bot in their own groups."""
        chat = upd.get("chat", {})
        chat_id = chat.get("id")
        status = (upd.get("new_chat_member") or {}).get("status")
        if chat.get("type") == "private" or status in (None, "left", "kicked"):
            return
        if self.chat_id and str(chat_id) != str(self.chat_id):
            self.log.warning("added to a foreign chat %s (%r) by %s — leaving",
                             chat_id, chat.get("title"), (upd.get("from") or {}).get("id"))
            try:
                self.client.leave_chat(chat_id)
            except Exception as e:
                self.log.debug("leave_chat error: %s", e)

    def _handle_update(self, up: dict):
        if up.get("my_chat_member"):
            self._handle_membership(up["my_chat_member"])
            return
        msg = up.get("message") or up.get("channel_post")
        if not msg:
            return
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        user = msg.get("from", {})
        user_id = user.get("id")
        thread_id = msg.get("message_thread_id")
        is_private = chat.get("type") == "private"

        parts = text.split()
        cmd = parts[0][1:].split("@")[0].lower()
        args = parts[1:]
        handler = self.handlers.get(cmd)
        if not handler:
            return

        reply = {"chat_id": chat_id, "message_thread_id": thread_id, "message_id": msg.get("message_id")}

        # scope: only the configured group, or a private chat from an admin.
        # Commands from any other group/channel are ignored silently.
        if not is_private and self.chat_id and str(chat_id) != str(self.chat_id):
            self.log.info("command from foreign chat %s ignored (user %s)", chat_id, user_id)
            return
        if is_private and not self.allow_private:
            return

        # authorization: an empty admin list means nobody may run commands (secure default).
        # Strangers in a private chat get NO reply at all (the bot stays invisible);
        # non-admin members of the configured group get a short hint with their id so
        # the owner can add them to telegram.admins.
        if user_id not in self.admins:
            if is_private:
                self.log.info("private command from non-admin %s ignored (/%s)", user_id, cmd)
                return
            if self.unauthorized_reply:
                hint = "" if self.admins else t("cmd.unauthorized_hint")
                self._reply(reply, t("cmd.unauthorized", uid=user_id) + hint)
            self.log.info("unauthorized command attempt: %s (/%s)", user_id, cmd)
            return

        self.log.info("command: /%s %s (user %s)", cmd, " ".join(args), user_id)
        handler(args, reply, user_id)

    def _reply(self, reply: dict, text: str, silent: bool = True):
        try:
            self.client.send_message(reply["chat_id"], text,
                                     thread_id=reply.get("message_thread_id"),
                                     reply_to=reply.get("message_id"), silent=silent)
        except TelegramError as e:
            self.log.warning("command reply failed: %s", e)

    # --------------------------------------------------------------- commands
    def cmd_status(self, args, reply, user_id):
        s = self.sched.status_dict()
        sysinfo = self._system_info()
        active = [x for x in self.sched.targets if x.enabled]
        lines = [t("cmd.status_title"), ""]
        if s["device_present"]:
            dev = self.sched.sdr.info
            lines.append(t("cmd.dongle_ok", d=(dev.detail if dev else "ok")))
        else:
            lines.append(t("cmd.dongle_missing"))
        cur = s["current_name"] or t("status.idle")
        lines.append(t("cmd.now", cur=cur))
        if s["current_freq"] and s["current_freq"] != "—":
            lines.append(t("cmd.listening", f=s["current_freq"], s=int(s["current_since_s"])))
        if s["next_info"]:
            lines.append(t("cmd.next", n=s["next_info"]))
        if s.get("next_pass_info"):
            lines.append(t("cmd.next_pass", p=s["next_pass_info"]))
        lines.append(t("cmd.queue", n=s["queue_len"]))
        lines.append("")
        lines.append(t("cmd.active", a=len(active), t=len(self.sched.targets)))
        if s["muted"]:
            labels = [Category(m).label if m in Category._value2member_map_ else m for m in s["muted"]]
            lines.append(t("cmd.muted", m=", ".join(labels)))
        if s["boosts"]:
            lines.append(t("cmd.boosted", b=", ".join(f"{k} ({v}s)" for k, v in s["boosts"].items())))
        lines.append("")
        lines.append(t("cmd.cpu", cpu=sysinfo["cpu"], mem=sysinfo["mem"]))
        if sysinfo["temp"]:
            lines.append(t("cmd.temp", t=sysinfo["temp"]))
        if sysinfo["load"]:
            lines.append(t("cmd.load", l=sysinfo["load"]))
        lines.append(t("cmd.uptime", u=_fmt_uptime(time.time() - self.start_time)))
        self._reply(reply, "\n".join(lines))

    def cmd_scan(self, args, reply, user_id):
        if not args:
            self._reply(reply, t("cmd.scan_usage"))
            return
        try:
            freq = float(args[0].replace(",", "."))
        except ValueError:
            self._reply(reply, t("cmd.scan_badfreq"))
            return
        if freq < 24 or freq > 1766:
            self._reply(reply, t("cmd.scan_range"))
            return
        seconds = None
        mode = "fm"
        for a in args[1:]:
            if a.lower() in ("am", "fm"):
                mode = a.lower()
            else:
                try:
                    seconds = float(a)
                except ValueError:
                    pass
        if self.cfg.is_blacklisted(freq):
            self._reply(reply, t("cmd.scan_blacklist", f=f"{freq:.3f}"))
        self.sched.add_adhoc(freq, seconds, mode, user_id, reply)
        self._reply(reply, t("cmd.scan_ack", f=f"{freq:.4f}", m=mode.upper(),
                             s=int(seconds or self.sched.adhoc_default_s)))

    def cmd_mute(self, args, reply, user_id):
        if not args:
            self._reply(reply, t("cmd.mute_usage", cats=_category_list()))
            return
        raw = " ".join(args)
        cat = Category.parse(raw)
        if cat and self.sched.mute(cat.value):
            self._reply(reply, t("cmd.muted_ok", c=cat.label, raw=raw))
        else:
            self._reply(reply, t("cmd.unknown_cat", c=raw))

    def cmd_unmute(self, args, reply, user_id):
        if not args:
            self._reply(reply, t("cmd.unmute_usage"))
            return
        raw = " ".join(args)
        cat = Category.parse(raw)
        if cat and self.sched.unmute(cat.value):
            self._reply(reply, t("cmd.unmuted_ok", c=cat.label))
        else:
            self._reply(reply, t("cmd.unknown_cat", c=raw))

    def cmd_priority(self, args, reply, user_id):
        if not args:
            keys = ", ".join(x.KEY for x in self.sched.targets)
            self._reply(reply, t("cmd.prio_usage", keys=keys))
            return
        key = args[0].lower()
        if self.sched.boost(key):
            self._reply(reply, t("cmd.prio_ok", k=key, m=int(self.sched.boost_minutes)))
            self.sched.interrupt_slot()
        else:
            self._reply(reply, t("cmd.unknown_target", k=key))

    def cmd_summary(self, args, reply, user_id):
        self._reply(reply, t("sum.generating"))
        try:
            self.summary.generate_and_send(manual=True, reply=reply)
        except Exception as e:
            self.log.exception("summary error: %s", e)
            self._reply(reply, t("sum.failed", e=e))

    def cmd_recordings(self, args, reply, user_id):
        n = 3
        if args:
            try:
                n = max(1, min(10, int(args[0])))
            except ValueError:
                pass
        rows = self.st.recent_recordings(n)
        if not rows:
            self._reply(reply, t("cmd.no_recordings"))
            return
        self._reply(reply, t("cmd.resending", n=len(rows)))
        for r in rows:
            path = r["path"]
            if not path or not os.path.exists(path):
                continue
            when = datetime.fromtimestamp(r["ts"], tz=timezone.utc).astimezone(self.tz).strftime("%Y-%m-%d %H:%M:%S")
            cap = t("rec.caption", ch=(r["channel"] or r["target"]), f=f"{r['freq_mhz']:.3f}", when=when,
                    s=f"{r['duration_s']:.0f}", sig=(r["signal"] or ""))
            if r["transcript"]:
                cap += f"\n📝 {r['transcript'][:300]}"
            try:
                low = path.lower()
                kw = dict(caption=cap[:1024], thread_id=reply.get("message_thread_id"), silent=True)
                if low.endswith((".ogg", ".oga", ".opus")):
                    self.client.send_voice(reply["chat_id"], path, **kw)
                elif low.endswith((".mp3", ".m4a")):
                    self.client.send_audio(reply["chat_id"], path, **kw)
                else:
                    self.client.send_document(reply["chat_id"], path, **kw)
            except TelegramError as e:
                self.log.warning("recording resend failed: %s", e)

    def cmd_list(self, args, reply, user_id):
        lines = [t("cmd.list_title"), ""]
        now = time.time()
        for x in self.sched.targets:
            icon = "🟢" if x.enabled else "⚪"
            if self.sched.is_muted(x.CATEGORY):
                icon = "🔇"
            ok, _ = x.tools_available()
            tool = "" if ok else t("cmd.list_notool")
            cls = "⏰" if x.CLASS == "pass" else "🔄"
            extra = ""
            if x.enabled and x.CLASS != "pass":
                due = x.due_in(now)
                extra = t("cmd.list_due") if due <= 0 else t("cmd.list_in", s=int(due))
            lines.append(f"{icon} {cls} <b>{x.KEY}</b> — {x.display_name()}{extra}{tool}")
        lines.append("")
        lines.append(t("cmd.list_legend"))
        self._reply(reply, "\n".join(lines))

    def cmd_passes(self, args, reply, user_id):
        hours = 24
        if args:
            try:
                hours = max(1, min(72, int(args[0])))
            except ValueError:
                pass
        try:
            passes = self.sched.upcoming_passes(hours=hours, limit=10)
        except Exception as e:
            self._reply(reply, t("cmd.passes_failed", e=e))
            return
        if not passes:
            self._reply(reply, t("cmd.passes_none", h=hours))
            return
        lines = [t("cmd.passes_title", h=hours), ""]
        for p in passes:
            lines.append(t("cmd.pass_line", sat=p.satellite, r=p.rise.astimezone(self.tz).strftime("%d.%m %H:%M"),
                           s=p.set.astimezone(self.tz).strftime("%H:%M"), el=f"{p.max_elevation:.0f}",
                           m=f"{p.duration_s / 60:.0f}"))
        self._reply(reply, "\n".join(lines))

    def cmd_help(self, args, reply, user_id):
        self._reply(reply, t("cmd.help", cats=_category_list()))

    # ----------------------------------------------------------- system info
    def _system_info(self) -> dict:
        info = {"cpu": "—", "mem": "—", "temp": "", "load": ""}
        try:
            import psutil
            info["cpu"] = f"{psutil.cpu_percent(interval=0.3):.0f}%"
            vm = psutil.virtual_memory()
            info["mem"] = f"{vm.percent:.0f}% ({vm.used // (1024**2)}/{vm.total // (1024**2)} MB)"
            temps = getattr(psutil, "sensors_temperatures", lambda: {})()
            for name, entries in (temps or {}).items():
                for e in entries:
                    if e.current:
                        info["temp"] = f"{e.current:.1f}°C ({name})"
                        break
                if info["temp"]:
                    break
        except Exception:
            pass
        try:
            la = os.getloadavg()
            info["load"] = f"{la[0]:.2f} {la[1]:.2f} {la[2]:.2f}"
        except (OSError, AttributeError):
            pass
        if not info["temp"]:
            try:
                with open("/sys/class/thermal/thermal_zone0/temp") as fh:
                    info["temp"] = f"{int(fh.read()) / 1000:.1f}°C"
            except (OSError, ValueError):
                pass
        return info
