# Hızlı Başlangıç

İlk çalıştırma için en kısa yol. Ayrıntılar `README.md` içinde.

## 1. Telegram hazırlığı (5 dk)
1. Telegram'da **@BotFather** ile yeni bot oluşturun → **token**'ı alın.
2. Botu hedef **gruba** ekleyin ve grupta **yönetici** yapın (mesaj gönderebilsin).
3. Grubu **topic'li** (konu) yapın ve mesajların gideceği topic'i açın.
4. Kimlikleri öğrenin (en kolay yol):
   ```bash
   python3 tools/telegram_ids.py <BOT_TOKEN>
   ```
   Betik çalışırken hedef topic'in içine `/start@<botadi>` yazın; chat_id,
   thread_id ve kendi kullanıcı kimliğiniz ekrana gelir. (Bot gizlilik kipi
   açıksa yalnız komutları görür; gerekirse BotFather → Bot Settings →
   Group Privacy → Turn off.)

## 2. Kurulum
```bash
# Linux / LXC:
sudo bash install/debian-linux.sh
# Raspberry Pi:
sudo bash install/raspberrypi.sh
```

## 3. Yapılandırma
```bash
sudo nano /opt/rtlsdr-telegram/config.yaml
```
En az şunları doldurun:
```yaml
telegram:
  token: "123456:ABC..."       # BotFather token
  chat_id: -1001234567890      # grup kimliği
  thread_id: 7                 # topic kimliği
  admins: [123456789]          # kendi kullanıcı kimliğiniz
station:
  lat: 41.0082                 # konumunuz (uydu geçişleri için)
  lon: 28.9784
```

## 4. Test ve başlat
```bash
VENV=/opt/rtlsdr-telegram/venv/bin/python
CFG=/opt/rtlsdr-telegram/config.yaml
$VENV /opt/rtlsdr-telegram/run.py --check -c $CFG          # araç + dongle kontrolü
$VENV /opt/rtlsdr-telegram/run.py --test-telegram -c $CFG  # Telegram testi
sudo systemctl enable --now rtlsdr-telegram                # servis olarak başlat
journalctl -u rtlsdr-telegram -f                           # canlı günlük
```

## 5. Telegram'dan dene
Grupta: `/durum` · `/liste` · `/gecisler` · `/tara 145.500` · `/yardim`

> Yoğun bölgedeyseniz ADS-B/AIS varsayılan olarak **özet** kipindedir (slot
> başına tek mesaj). Her hedefi ayrı istiyorsanız `report_mode: each`.

> Dongle takılı değilse sistem çalışır ama "Dongle bulunamadı" der; dongle'ı
> takınca otomatik devam eder.
