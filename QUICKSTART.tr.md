# Hızlı Başlangıç

> English: [QUICKSTART.md](QUICKSTART.md) · Platforma göre tam kılavuz: [docs/INSTALL.tr.md](docs/INSTALL.tr.md)

Linux'ta (Ubuntu/Debian, Raspberry Pi, Proxmox LXC) çalışan sisteme en kısa yol.

## 1. Telegram (5 dakika)
1. **@BotFather** → `/newbot` → **token**'ı kopyalayın.
2. BotFather → `/mybots` → botunuz → *Bot Settings* → *Group Privacy* → **Turn off**.
3. **Konular** açık bir grup oluşturun, botun yazacağı konuyu açın, botu ekleyip **yönetici** yapın.
4. Kimlikleri alın:
   ```bash
   python3 tools/telegram_ids.py <BOT_TOKEN>      # sonra konunun içine /start@<botadi> yazın
   ```
   `chat_id`, `thread_id` ve kendi `admin id`'nizi yazdırır.

## 2. Kurulum
```bash
git clone https://github.com/haliskilic/rtlsdr-telegram.git && cd rtlsdr-telegram
sudo bash install/debian-linux.sh        # Raspberry Pi: sudo bash install/raspberrypi.sh
```

## 3. Yapılandırma
```bash
sudo nano /opt/rtlsdr-telegram/config.yaml
```
```yaml
language: tr
telegram:
  token: "123456:ABC..."
  chat_id: -1001234567890
  thread_id: 7
  admins: [123456789]
station:
  lat: 41.0082               # konumunuz (uydu geçişleri, mesafeler)
  lon: 28.9784
```

## 4. Test ve başlat
```bash
VENV=/opt/rtlsdr-telegram/venv/bin/python
CFG=/opt/rtlsdr-telegram/config.yaml
$VENV /opt/rtlsdr-telegram/run.py --check -c $CFG          # araçlar + dongle
$VENV /opt/rtlsdr-telegram/run.py --test-telegram -c $CFG  # Telegram
sudo systemctl enable --now rtlsdr-telegram                # servis olarak çalıştır
journalctl -u rtlsdr-telegram -f                           # canlı log
```

## 5. Telegram'dan dene
Konuda: `/durum` · `/liste` · `/gecisler` · `/tara 145.500` · `/yardim`

> Dongle henüz yok mu? Sistem yine başlar, "dongle bulunamadı" der ve siz takınca
> otomatik devam eder. Yoğun bölgelerde ADS-B/AIS varsayılan olarak slot başına tek
> özet gönderir (her hedef için ayrı mesaj: `report_mode: each`).
