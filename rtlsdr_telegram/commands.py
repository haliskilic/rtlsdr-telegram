"""Telegram komut yönetimi (Özellik C, madde 7).

getUpdates ile grup içinden komutları alır. Yalnızca yapılandırmada tanımlı
yönetici kullanıcılar komut çalıştırabilir. Komutlar:

  /durum            aktif hedefler, dinlenen bant, CPU/sıcaklık, uptime
  /tara <frekans>   belirtilen frekansı geçici dinle (MHz) [+ süre sn] [am|fm]
  /sustur <kategori> bir kategoriyi geçici sustur
  /ac <kategori>    kategoriyi geri aç
  /oncelik <hedef>  hedefi tarama döngüsünde öne al
  /ozet             günlük özeti hemen üret
  /kayitlar <n>     son n ses kaydını yeniden gönder
  /liste            tüm hedeflerin ve durumlarının listesi
  /yardim           komut listesi
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from .events import Category, Attachment
from .telegram import TelegramError


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    out = []
    if d:
        out.append(f"{d}g")
    if h or d:
        out.append(f"{h}s")
    out.append(f"{m}dk")
    return " ".join(out)


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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = self.st.kv_get("tg_update_offset", 0)
        self.handlers = {
            "durum": self.cmd_durum, "status": self.cmd_durum,
            "tara": self.cmd_tara, "scan": self.cmd_tara,
            "sustur": self.cmd_sustur, "mute": self.cmd_sustur,
            "ac": self.cmd_ac, "unmute": self.cmd_ac,
            "oncelik": self.cmd_oncelik, "öncelik": self.cmd_oncelik, "priority": self.cmd_oncelik,
            "ozet": self.cmd_ozet, "özet": self.cmd_ozet, "summary": self.cmd_ozet,
            "kayitlar": self.cmd_kayitlar, "kayıtlar": self.cmd_kayitlar, "recordings": self.cmd_kayitlar,
            "liste": self.cmd_liste, "list": self.cmd_liste,
            "yardim": self.cmd_yardim, "yardım": self.cmd_yardim, "help": self.cmd_yardim,
            "start": self.cmd_yardim,
        }

    # --------------------------------------------------------------- yaşam
    def start(self):
        self._thread = threading.Thread(target=self._loop, name="commands", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        self.log.info("komut dinleyici başladı (yöneticiler: %s)", self.admins or "YOK")
        while not self._stop.is_set():
            try:
                updates = self.client.get_updates(offset=self._offset or None, timeout=self.poll_timeout)
            except TelegramError as e:
                self.log.debug("getUpdates hata: %s", e)
                self._stop.wait(5)
                continue
            except Exception as e:
                self.log.warning("getUpdates beklenmeyen: %s", e)
                self._stop.wait(5)
                continue
            for up in updates:
                self._offset = up["update_id"] + 1
                try:
                    self._handle_update(up)
                except Exception as e:
                    self.log.exception("komut işleme hatası: %s", e)
            if updates:
                self.st.kv_set("tg_update_offset", self._offset)

    # ------------------------------------------------------- yetki/çözümleme
    def _handle_update(self, up: dict):
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

        # komut + bot adı ayıkla (/durum@botadi)
        parts = text.split()
        cmd = parts[0][1:].split("@")[0].lower()
        args = parts[1:]
        handler = self.handlers.get(cmd)
        if not handler:
            return

        reply = {"chat_id": chat_id, "message_thread_id": thread_id, "message_id": msg.get("message_id")}

        # kapsam kontrolü: yapılandırılan grup ya da yöneticiden özel
        if not is_private and self.chat_id and str(chat_id) != str(self.chat_id):
            return  # başka grup — yok say
        if is_private and not self.allow_private:
            return

        # yetki
        if self.admins and user_id not in self.admins:
            if self.unauthorized_reply:
                self._reply(reply, f"⛔ Yetkiniz yok. (kullanıcı kimliğiniz: <code>{user_id}</code>)")
            self.log.info("yetkisiz komut denemesi: %s (%s)", user_id, cmd)
            return
        if not self.admins:
            self.log.warning("yönetici tanımlı değil; komut yine de işleniyor (kullanıcı %s)", user_id)

        self.log.info("komut: /%s %s (kullanıcı %s)", cmd, " ".join(args), user_id)
        handler(args, reply, user_id)

    def _reply(self, reply: dict, text: str, silent: bool = True):
        try:
            self.client.send_message(reply["chat_id"], text,
                                     thread_id=reply.get("message_thread_id"),
                                     reply_to=reply.get("message_id"), silent=silent)
        except TelegramError as e:
            self.log.warning("komut yanıtı gönderilemedi: %s", e)

    # ------------------------------------------------------------- komutlar
    def cmd_durum(self, args, reply, user_id):
        s = self.sched.status_dict()
        sysinfo = self._system_info()
        active = [t for t in self.sched.targets if t.enabled]
        lines = ["📊 <b>Sistem Durumu</b>", ""]
        if s["device_present"]:
            dev = self.sched.sdr.info
            lines.append(f"📡 Dongle: ✅ {dev.detail if dev else 'hazır'}")
        else:
            lines.append("📡 Dongle: ❌ bulunamadı (takılı mı?)")
        cur = s["current_name"] or "boşta"
        lines.append(f"🎯 Şu an: <b>{cur}</b>")
        if s["current_freq"] and s["current_freq"] != "—":
            lines.append(f"   └ dinlenen: {s['current_freq']} ({int(s['current_since_s'])} sn)")
        if s["next_info"]:
            lines.append(f"⏭️ Sıradaki: {s['next_info']}")
        lines.append(f"📨 Kuyruk: {s['queue_len']} mesaj bekliyor")
        lines.append("")
        lines.append(f"✅ Aktif hedef: {len(active)}/{len(self.sched.targets)}")
        if s["muted"]:
            lines.append(f"🔇 Susturulan: {', '.join(s['muted'])}")
        if s["boosts"]:
            b = ", ".join(f"{k} ({v}sn)" for k, v in s["boosts"].items())
            lines.append(f"⚡ Öncelikli: {b}")
        lines.append("")
        lines.append(f"🖥️ CPU: {sysinfo['cpu']}  ·  RAM: {sysinfo['mem']}")
        if sysinfo["temp"]:
            lines.append(f"🌡️ Sıcaklık: {sysinfo['temp']}")
        if sysinfo["load"]:
            lines.append(f"📈 Yük: {sysinfo['load']}")
        lines.append(f"⏱️ Çalışma süresi: {_fmt_uptime(time.time() - self.start_time)}")
        self._reply(reply, "\n".join(lines))

    def cmd_tara(self, args, reply, user_id):
        if not args:
            self._reply(reply, "Kullanım: <code>/tara 145.500 [süre_sn] [am|fm]</code>")
            return
        try:
            freq = float(args[0].replace(",", "."))
        except ValueError:
            self._reply(reply, "Geçersiz frekans. Örnek: <code>/tara 145.500</code>")
            return
        if freq < 24 or freq > 1766:
            self._reply(reply, "Frekans 24–1766 MHz aralığında olmalı.")
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
            self._reply(reply, f"⚠️ {freq:.3f} MHz kara listede (FM/TV). Yine de deneniyor…")
        self.sched.add_adhoc(freq, seconds, mode, user_id, reply)
        self._reply(reply, f"🎧 {freq:.4f} MHz ({mode.upper()}) ~{int(seconds or self.sched.adhoc_default_s)} sn "
                           f"dinlenecek; etkinlik olursa kaydı buraya göndereceğim.")

    def cmd_sustur(self, args, reply, user_id):
        if not args:
            self._reply(reply, "Kullanım: <code>/sustur Havacılık</code>\nKategoriler: "
                               + ", ".join(c.value for c in Category if c != Category.SISTEM))
            return
        cat = " ".join(args)
        if self.sched.mute(cat):
            self._reply(reply, f"🔇 '{Category.parse(cat).value}' kategorisi susturuldu. "
                               f"Geri açmak: <code>/ac {cat}</code>")
        else:
            self._reply(reply, f"Bilinmeyen kategori: {cat}")

    def cmd_ac(self, args, reply, user_id):
        if not args:
            self._reply(reply, "Kullanım: <code>/ac Havacılık</code>")
            return
        cat = " ".join(args)
        if self.sched.unmute(cat):
            self._reply(reply, f"🔊 '{Category.parse(cat).value}' kategorisi tekrar aktif.")
        else:
            self._reply(reply, f"Bilinmeyen kategori: {cat}")

    def cmd_oncelik(self, args, reply, user_id):
        if not args:
            keys = ", ".join(t.KEY for t in self.sched.targets)
            self._reply(reply, f"Kullanım: <code>/oncelik adsb</code>\nHedefler: {keys}")
            return
        key = args[0].lower()
        if self.sched.boost(key):
            self._reply(reply, f"⚡ '{key}' tarama döngüsünde öne alındı "
                               f"({int(self.sched.boost_minutes)} dk).")
            self.sched.interrupt_slot()
        else:
            self._reply(reply, f"Bilinmeyen hedef: {key}")

    def cmd_ozet(self, args, reply, user_id):
        self._reply(reply, "📅 Günlük özet üretiliyor…")
        try:
            self.summary.generate_and_send(manual=True, reply=reply)
        except Exception as e:
            self.log.exception("özet hatası: %s", e)
            self._reply(reply, f"Özet üretilemedi: {e}")

    def cmd_kayitlar(self, args, reply, user_id):
        n = 3
        if args:
            try:
                n = max(1, min(10, int(args[0])))
            except ValueError:
                pass
        rows = self.st.recent_recordings(n)
        if not rows:
            self._reply(reply, "Henüz ses kaydı yok.")
            return
        self._reply(reply, f"🔁 Son {len(rows)} kayıt gönderiliyor…")
        import os
        for r in rows:
            path = r["path"]
            if not path or not os.path.exists(path):
                continue
            when = datetime.fromtimestamp(r["ts"], tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            cap = (f"{r['channel'] or r['target']} · {r['freq_mhz']:.3f} MHz\n{when} · "
                   f"{r['duration_s']:.0f} sn · {r['signal'] or ''}")
            tr = r["transcript"]
            if tr:
                cap += f"\n📝 {tr[:300]}"
            try:
                kind = "voice" if path.endswith((".ogg", ".oga")) else "audio"
                self.client.send_voice(reply["chat_id"], path, caption=cap[:1024],
                                       thread_id=reply.get("message_thread_id"), silent=True)
            except TelegramError as e:
                self.log.warning("kayıt gönderilemedi: %s", e)

    def cmd_liste(self, args, reply, user_id):
        lines = ["📋 <b>Hedef Listesi</b>", ""]
        now = time.time()
        for t in self.sched.targets:
            icon = "🟢" if t.enabled else "⚪"
            if self.sched.is_muted(t.CATEGORY):
                icon = "🔇"
            ok, msg = t.tools_available()
            tool = "" if ok else " ⚠️araç yok"
            cls = "⏰" if t.CLASS == "waiting" else "🔄"
            extra = ""
            if t.enabled and t.CLASS != "waiting":
                due = t.due_in(now)
                extra = " (sırada)" if due <= 0 else f" ({int(due)}sn)"
            lines.append(f"{icon} {cls} <b>{t.KEY}</b> — {t.display_name()}{extra}{tool}")
        lines.append("")
        lines.append("🟢 aktif · ⚪ kapalı · 🔇 susturulmuş · ⏰ zamanlanmış · 🔄 fırsatçı")
        self._reply(reply, "\n".join(lines))

    def cmd_yardim(self, args, reply, user_id):
        txt = (
            "🤖 <b>RTL-SDR İzleme Botu — Komutlar</b>\n\n"
            "/durum — sistem durumu, dinlenen bant, CPU/sıcaklık, uptime\n"
            "/liste — tüm hedefler ve durumları\n"
            "/tara <code>145.5 [sn] [am|fm]</code> — frekansı geçici dinle\n"
            "/sustur <code>&lt;kategori&gt;</code> — kategoriyi sustur\n"
            "/ac <code>&lt;kategori&gt;</code> — kategoriyi geri aç\n"
            "/oncelik <code>&lt;hedef&gt;</code> — hedefi öne al\n"
            "/ozet — günlük özeti hemen üret\n"
            "/kayitlar <code>[n]</code> — son n kaydı yeniden gönder\n"
            "/yardim — bu liste\n\n"
            f"Kategoriler: {', '.join(c.value for c in Category if c != Category.SISTEM)}"
        )
        self._reply(reply, txt)

    # ----------------------------------------------------------- sistem bilgisi
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
            import os
            la = os.getloadavg()
            info["load"] = f"{la[0]:.2f} {la[1]:.2f} {la[2]:.2f}"
        except (OSError, AttributeError):
            pass
        if not info["temp"]:
            # Raspberry Pi / Linux termal
            for p in ("/sys/class/thermal/thermal_zone0/temp",):
                try:
                    with open(p) as fh:
                        info["temp"] = f"{int(fh.read()) / 1000:.1f}°C"
                        break
                except (OSError, ValueError):
                    pass
        return info
