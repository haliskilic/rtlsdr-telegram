#!/usr/bin/env python3
"""Telegram grup/topic/kullanıcı kimliklerini bulma yardımcısı.

Kullanım:
  python3 tools/telegram_ids.py <BOT_TOKEN>

Çalıştırdıktan sonra botun ekli olduğu grupta, hedef topic'in İÇİNDE şu mesajı
gönderin:  /start@<botadi>   (bot gizlilik kipi açıksa yalnız komutları görür).
Betik 5 dakika boyunca dinler; ilk yakaladığı mesajın chat_id, thread_id ve
gönderen kullanıcı kimliğini yazdırır. Bu değerleri config.yaml'a girin.
"""
import json
import sys
import time
import urllib.parse
import urllib.request


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    token = sys.argv[1].strip()
    base = f"https://api.telegram.org/bot{token}"
    try:
        with urllib.request.urlopen(f"{base}/getMe", timeout=20) as r:
            me = json.load(r)["result"]
        print(f"Bot: @{me.get('username')}  — şimdi hedef topic'e  /start@{me.get('username')}  yazın.")
    except Exception as e:
        print("Token doğrulanamadı:", e)
        return 1
    offset = None
    deadline = time.time() + 300
    while time.time() < deadline:
        q = {"timeout": 20}
        if offset:
            q["offset"] = offset
        try:
            with urllib.request.urlopen(f"{base}/getUpdates?{urllib.parse.urlencode(q)}", timeout=40) as r:
                ups = json.load(r).get("result", [])
        except Exception as e:
            print("getUpdates hata:", e)
            time.sleep(3)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            m = u.get("message") or u.get("channel_post") or {}
            ch = m.get("chat", {})
            if not ch.get("id"):
                continue
            frm = m.get("from") or {}
            print("\n--- Yakalandı ---")
            print(f"chat_id   : {ch.get('id')}   ({ch.get('type')}, '{ch.get('title')}', forum={ch.get('is_forum')})")
            print(f"thread_id : {m.get('message_thread_id') or 0}   (topic kimliği; genel topic için 0)")
            print(f"admin id  : {frm.get('id')}   (@{frm.get('username')} {frm.get('first_name') or ''})")
            print(f"metin     : {(m.get('text') or '')[:60]!r}")
            print("\nconfig.yaml:")
            print(f"telegram:\n  chat_id: {ch.get('id')}\n  thread_id: {m.get('message_thread_id') or 0}\n  admins: [{frm.get('id')}]")
            return 0
    print("5 dakikada mesaj gelmedi. Botun grupta olduğundan ve /start@bot yazdığınızdan emin olun; "
          "gerekirse BotFather → Bot Settings → Group Privacy → Turn off.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
