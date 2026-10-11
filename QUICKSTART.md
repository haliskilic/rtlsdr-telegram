# Hızlı Başlangıç

İlk çalıştırma için en kısa yol. Ayrıntılar `README.md` içinde.

## 1. Telegram hazırlığı (5 dk)
1. Telegram'da **@BotFather** ile yeni bot oluşturun → **token**'ı alın.
2. Botu hedef **gruba** ekleyin ve grupta **yönetici** yapın (mesaj gönderebilsin).
3. Grubu **topic'li** (konu) yapın ve mesajların gideceği topic'i açın.
4. Kimlikleri öğrenin:
   - Grup/topic kimliği: Gruba bir mesaj atıp `https://api.telegram.org/bot<TOKEN>/getUpdates`
     adresini açın; `chat.id` (süpergrup `-100...`) ve `message_thread_id` değerlerini görün.
   - Kendi kullanıcı kimliğiniz: **@userinfobot**'a yazın.

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
Grupta: `/durum` · `/liste` · `/tara 145.500` · `/yardim`

> Dongle takılı değilse sistem çalışır ama "Dongle bulunamadı" der; dongle'ı
> takınca otomatik devam eder.
