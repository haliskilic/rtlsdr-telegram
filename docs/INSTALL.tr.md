# Kurulum Kılavuzu — adım adım

> English version: [INSTALL.md](INSTALL.md)

Bu kılavuz **hiç deneyimi olmayan** biri için yazıldı. Her adımda tam olarak ne
yazacağınız ve ne görmeniz gerektiği yazıyor. Platformunuzu seçin:

- [0. Neler gerekli](#0-neler-gerekli)
- [1. Telegram botunu oluşturma (tüm platformlar)](#1-telegram-botunu-oluşturma-tüm-platformlar)
- [2A. Ubuntu / Debian PC](#2a-ubuntu--debian-pc)
- [2B. Raspberry Pi](#2b-raspberry-pi)
- [2C. Proxmox (LXC konteyner)](#2c-proxmox-lxc-konteyner)
- [2D. Windows 10/11](#2d-windows-1011)
- [3. config.yaml ayarları](#3-configyaml-ayarları)
- [4. İlk çalıştırma ve testler](#4-i̇lk-çalıştırma-ve-testler)
- [5. Servis olarak çalıştırma](#5-servis-olarak-çalıştırma)
- [6. Telegram'dan kontrol](#6-telegramdan-kontrol)
- [7. Güncelleme](#7-güncelleme)
- [8. Sorun giderme](#8-sorun-giderme)

---

## 0. Neler gerekli

**Donanım**
| Parça | Not |
|-------|-----|
| RTL-SDR dongle | RTL2832U + R820T/R860 (ör. RTL-SDR Blog V3/V4, NESDR). Makinenin kendi USB 2.0 portuna takın (ucuz hub kullanmayın). |
| Anten | Başlangıç için teleskopik/discone anten yeter. Daha iyi sonuç: ADS-B için 1090 MHz anten, hava/deniz/amatör için dikey VHF anten, 137 MHz uydular için QFH/turnike. Dongle'ın MCX/SMA girişine takın. |
| Bilgisayar | Ubuntu/Debian PC, Raspberry Pi 4/5 (64-bit), Proxmox sunucu veya Windows 10/11. 2 GB RAM yeterli; transkripsiyon açıksa 4 çekirdek önerilir. |
| İnternet | Telegram, TLE indirme ve ilk Whisper modeli için. |

**Hesaplar**
- Bir Telegram hesabı ve mesajların düşeceği, **Konular (Topics)** açık bir grup.

**Yazılım gereksinimleri (aşağıdaki betikler kurar)**
| Bileşen | Amaç | Linux paketi / kaynak |
|---------|------|-----------------------|
| rtl-sdr (rtl_fm, rtl_power, rtl_test) | dongle erişimi | apt `rtl-sdr librtlsdr-dev` |
| readsb | ADS-B | kaynaktan (Debian paketinde RTL desteği yok) |
| acarsdec, dumpvdl2, libacars | ACARS / VDL2 | kaynaktan |
| AIS-catcher, rtl-ais | AIS | kaynaktan |
| rtl_433 | ISM sensörler | apt `rtl-433` |
| multimon-ng, direwolf | APRS | apt |
| gr-gsm | GSM hücre kimlikleri | apt `gr-gsm` |
| satdump | Meteor-M, Inmarsat | apt `satdump` |
| ffmpeg, sox | ses kodlama | apt |
| Python 3.11+ ve venv | uygulama | apt `python3 python3-venv` |
| Python kütüphaneleri | bkz. `requirements.txt` | pip (veya apt: python3-numpy/scipy/matplotlib/httpx/yaml/skyfield/psutil/aprslib) |
| faster-whisper (isteğe bağlı) | yerel transkripsiyon | pip |

---

## 1. Telegram botunu oluşturma (tüm platformlar)

1. Telegram'da **@BotFather**'ı açın, `/newbot` yazın. Bir ad (ör. *SDR İzleme*) ve `bot` ile biten bir kullanıcı adı (ör. `sdrizleme_bot`) verin.
2. BotFather `123456789:AAF...` gibi bir **token** verir. Gizli tutun; botun şifresidir.
3. BotFather'da: `/mybots` → botunuz → **Bot Settings** → **Group Privacy** → **Turn off**. (Bot grubunuzdaki komutları görebilsin.)
4. Mesajların düşeceği **grubu** açın/oluşturun. Grup ayarlarından **Konular**'ı açın ve bir konu oluşturun, ör. *RTL-SDR*.
5. Botu gruba ekleyin ve **yönetici** yapın (konuya yazabilmesi için gerekli).
6. Kimlikleri bulun. Kurulum yapacağınız makinede (2x adımından sonra):
   ```bash
   python3 tools/telegram_ids.py <BOT_TOKEN>
   ```
   Betik beklerken **konunun içine** `/start@<botadi>` yazın. Betik şunları yazdırır:
   ```
   chat_id   : -1001234567890
   thread_id : 123
   admin id  : 987654321
   ```
   Bunları not edin; `config.yaml`'a girilecek (adım 3).

> Güvenlik: Bot yalnızca `config.yaml`'daki yönetici kimliklerinden ve yalnızca sizin
> grubunuzdan (ya da bir yöneticinin özel mesajından) komut kabul eder. Biri botu başka
> bir gruba eklerse bot otomatik ayrılır. Yabancılar özelden yazarsa yanıt almaz.

---

## 2A. Ubuntu / Debian PC

Ubuntu 22.04/24.04 ve Debian 12/13 ile denendi.

**Adım 1 — dongle'ı takın, bir terminal açın.**

**Adım 2 — projeyi indirin**
```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/haliskilic/rtlsdr-telegram.git
cd rtlsdr-telegram
```

**Adım 3 — kurulum betiğini çalıştırın (5–15 dk; birkaç aracı derler)**
```bash
sudo bash install/debian-linux.sh
```
Ne yapar: apt paketlerini kurar; readsb/acarsdec/dumpvdl2/AIS-catcher/rtl-ais'i kaynaktan
`/usr/local/bin`'e derler; dongle'ı kapan kernel DVB sürücüsünü kara listeye alır; udev
kuralı yazar; uygulamayı `/opt/rtlsdr-telegram`'a kopyalar; Python venv oluşturur ve
systemd servisini kurar. Sonunda `>>> DONE` görmelisiniz.

**Adım 4 — dongle'ı doğrulayın**
```bash
rtl_test -t
```
`Found 1 device(s)` ve tuner adını görmelisiniz. Ctrl+C ile çıkın. `No supported
devices found` görürseniz dongle'ı çıkarıp takın, başka bir USB portu deneyin.

**Adım 5 — isteğe bağlı: yerel transkripsiyon**
```bash
sudo /opt/rtlsdr-telegram/venv/bin/pip install faster-whisper
```
(`base` modeli ilk kullanımda otomatik iner, ~150 MB.)

[3. config.yaml ayarları](#3-configyaml-ayarları) ile devam edin.

---

## 2B. Raspberry Pi

Pi 4 veya Pi 5'te **Raspberry Pi OS (64-bit, Bookworm)** ve iyi bir güç kaynağı kullanın.

**Adım 1 — Pi'yi hazırlayın**
- Raspberry Pi Imager ile 64-bit OS yazın, imager ayarlarından SSH'ı açın, başlatın.
- Bağlanın (`ssh pi@raspberrypi.local`) ve güncelleyin:
  ```bash
  sudo apt update && sudo apt full-upgrade -y && sudo reboot
  ```

**Adım 2 — dongle'ı bir USB porta takın** (mavi USB 3.0 portlar olur). Kısa ve kaliteli anten kablosu tercih edin.

**Adım 3 — indirin ve kurun**
```bash
sudo apt install -y git
git clone https://github.com/haliskilic/rtlsdr-telegram.git
cd rtlsdr-telegram
sudo bash install/raspberrypi.sh
```
Pi birkaç aracı derler; **15–30 dakika** sürebilir.

**Adım 4 — dongle'ı doğrulayın**: `rtl_test -t` → `Found 1 device(s)`.

**Adım 5 — Pi'ye özel ayarlar** (sonra `config.yaml`'da):
- `transcription.model: tiny` (Pi 3'te `engine: none`) — Whisper CPU yorar.
- `targets.spectrum.period_s: 1200` — taramalar CPU yoğun.
- Soğutma: soğutucu/fan önerilir; `satdump` ve Whisper CPU'yu zorlar.
- Güç: dongle resetleniyorsa `/boot/firmware/config.txt`'e `max_usb_current=1` ekleyin.

[3. config.yaml ayarları](#3-configyaml-ayarları) ile devam edin.

---

## 2C. Proxmox (LXC konteyner)

Dongle **Proxmox host'una** takılır ve ayrıcalıksız bir Debian konteynerine geçirilir.
1–3. adımları **host** kabuğunda (root ile SSH), 4–6. adımları konteyner içinde yapın.

**Adım 1 — host: kernel dongle'ı kapmasın**
```bash
cat > /etc/modprobe.d/blacklist-rtlsdr.conf <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
blacklist rtl2832_sdr
blacklist dvb_usb_v2
EOF
for m in rtl2832_sdr dvb_usb_rtl28xxu rtl2832 dvb_usb_v2; do rmmod $m 2>/dev/null; done
cat > /etc/udev/rules.d/20-rtlsdr.rules <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
EOF
udevadm control --reload-rules && udevadm trigger
lsusb | grep -i 0bda      # "Realtek ... RTL2838" görünmeli
```
`lsusb` hiçbir şey göstermiyorsa dongle elektriksel olarak algılanmıyor demektir: başka
bir USB port (arka portlar), hub/uzatma olmadan, dongle'ı çıkarıp takın.

**Adım 2 — host: konteyneri oluşturun** (depolama/şablon adlarını kendinize göre düzenleyin;
şablonları `pveam available --section system` ile listeleyip `pveam download local <ad>` ile indirin)
```bash
pct create 102 local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst \
  --hostname rtlsdr-telegram --cores 4 --memory 2048 --swap 1024 \
  --rootfs local-lvm:16 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --onboot 1 --password 'Degistir123'
```

**Adım 3 — host: USB geçişi**
```bash
cat >> /etc/pve/lxc/102.conf <<'EOF'
lxc.cgroup2.devices.allow: c 189:* rwm
lxc.mount.entry: /dev/bus/usb dev/bus/usb none bind,optional,create=dir
EOF
pct start 102
pct exec 102 -- bash -c "apt update && apt install -y git usbutils rtl-sdr && rtl_test -t"
```
Son komut `Found 1 device(s)` yazmalı. (`onboot: 1` konteyneri host ile başlatır; içindeki
servis konteynerle başlar.)

**Adım 4 — konteyner: projeyi kurun**
```bash
pct exec 102 -- bash
# artık konteyner içindesiniz:
git clone https://github.com/haliskilic/rtlsdr-telegram.git /opt/rtlsdr-telegram-src
cd /opt/rtlsdr-telegram-src
bash install/debian-linux.sh
```

**Adım 5 — konteyner: isteğe bağlı transkripsiyon**
```bash
/opt/rtlsdr-telegram/venv/bin/pip install faster-whisper
```

**Adım 6 — konteyner: loglar sınırlı kalsın** (kurulum betiği zaten yapar; bilgi için)
```bash
cat /etc/systemd/journald.conf.d/rtlsdr-telegram.conf
# SystemMaxUse=200M, MaxRetentionSec=1month
```

[3. config.yaml ayarları](#3-configyaml-ayarları) ile devam edin (dosya konteyner içinde
`/opt/rtlsdr-telegram/config.yaml`).

---

## 2D. Windows 10/11

Çoğu hedef Windows'ta çalışır. ACARS/VDL2, gr-gsm ve radiosonde_auto_rx Windows'ta zor
derlenir; bu hedefleri kapatın veya Linux sürümünü WSL2'de çalıştırın.

**Adım 1 — Python**: https://www.python.org/downloads/ adresinden Python 3.11+ kurun;
**"Add Python to PATH"** kutusunu işaretleyin.

**Adım 2 — dongle sürücüsü (Zadig)**
1. Dongle'ı takın. https://zadig.akeo.ie/ adresinden **Zadig**'i indirip çalıştırın.
2. *Options → List All Devices*. **"Bulk-In, Interface (Interface 0)"** (veya "RTL2838UHIDIR") seçin.
3. Sürücü olarak **WinUSB** seçip **Replace Driver**'a basın.

**Adım 3 — SDR araçları**: indirip açın, her birinin `bin` klasörünü PATH'e ekleyin
(*Ayarlar → Sistem → Hakkında → Gelişmiş sistem ayarları → Ortam Değişkenleri*):
- rtl-sdr (rtl_fm, rtl_power, rtl_test): https://github.com/osmocom/rtl-sdr/releases veya https://www.rtl-sdr.com/ (Windows derlemesi)
- rtl_433: https://github.com/merbanan/rtl_433/releases
- AIS-catcher: https://github.com/jvde-github/AIS-catcher/releases
- readsb/dump1090 Windows: https://github.com/MalcolmRobb/dump1090 (`targets.adsb.tool: dump1090` yapın)
- multimon-ng: https://github.com/EliasOenal/multimon-ng/releases
- SatDump: https://www.satdump.org/download/
- ffmpeg: https://www.gyan.dev/ffmpeg/builds/ (`bin` klasörü)

Yeni bir *Komut İstemi* açıp kontrol edin: `rtl_test -t` → `Found 1 device(s)`.

**Adım 4 — proje**
```powershell
git clone https://github.com/haliskilic/rtlsdr-telegram.git
cd rtlsdr-telegram
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\pip install faster-whisper      # isteğe bağlı
copy config.example.tr.yaml config.yaml
notepad config.yaml                          # adım 3; platform: windows yazın
venv\Scripts\python run.py --check -c config.yaml
venv\Scripts\python run.py -c config.yaml
```

**Adım 5 — açılışta çalışsın (isteğe bağlı)** NSSM ile (https://nssm.cc/):
```powershell
nssm install rtlsdr-telegram "C:\yol\venv\Scripts\python.exe" "C:\yol\run.py -c C:\yol\config.yaml"
nssm start rtlsdr-telegram
```

---

## 3. config.yaml ayarları

Dosyayı açın (Linux: `sudo nano /opt/rtlsdr-telegram/config.yaml`). Yalnızca şu
anahtarlar zorunludur:

```yaml
language: tr                 # en | tr  (Telegram mesaj dili)
telegram:
  token: "123456789:AAF..."  # BotFather'dan
  chat_id: -1001234567890    # tools/telegram_ids.py çıktısı
  thread_id: 123             # konu kimliği (0 = Genel konu)
  admins: [987654321]        # kendi Telegram kullanıcı kimliğiniz
station:
  name: "İstasyonum"
  lat: 41.0082               # konumunuz (uydu geçişleri, mesafeler)
  lon: 28.9784
```

İşe yarar isteğe bağlı ayarlar:
```yaml
paths:
  retention_months: 6        # 6 aydan eski kayıt/olayları sil (veya retention_years)
transcription:
  engine: faster_whisper     # kapatmak için none
  model: base                # Raspberry Pi'de tiny
targets:
  adsb: {report_mode: summary}    # slot başına tek özet (yoğun hava sahası)
  ais:  {report_mode: summary}
  gsm:  {enabled: false}          # gerekmeyeni kapatın
```
Her hedefte `enabled`, `priority`, `dwell_s`, `period_s` vardır; tüm seçenekler
açıklamalarıyla `config.example.tr.yaml` içindedir. Dosyayı koruyun: `chmod 600 config.yaml`.

---

## 4. İlk çalıştırma ve testler

```bash
VENV=/opt/rtlsdr-telegram/venv/bin/python
CFG=/opt/rtlsdr-telegram/config.yaml
$VENV /opt/rtlsdr-telegram/run.py --check -c $CFG
```
Beklenen: `Dongle: PRESENT — ...`, ✓ işaretli 16 hedef, `Satellite prediction: on`.
✗ o hedefin aracı eksik demektir (hedef atlanır, başka hiçbir şey bozulmaz).

```bash
$VENV /opt/rtlsdr-telegram/run.py --test-telegram -c $CFG
```
Beklenen: `Message sent: [...]` ve konunuzda bir test mesajı.

Logları izlemek için bir kez ön planda çalıştırın (Ctrl+C durdurur):
```bash
$VENV /opt/rtlsdr-telegram/run.py -c $CFG
```

---

## 5. Servis olarak çalıştırma

Linux (betik kurar):
```bash
sudo systemctl enable --now rtlsdr-telegram
systemctl status rtlsdr-telegram
journalctl -u rtlsdr-telegram -f          # canlı log
```
Servis çökerse kendiliğinden yeniden başlar ve açılışta başlar. Loglar döngüseldir
(uygulama logları `logs/`, araç başına log 5 MB, journal 200 MB ile sınırlı).

---

## 6. Telegram'dan kontrol

Konunuzda `/durum` (veya `/status`) yazın; sistem durumu gelmeli. `/liste`, `/gecisler`,
`/tara 145.500` ve `/yardim` deneyin. Her açılışta 🟢 "sistem başladı" mesajı, her gün
09:00'da (ayarlanabilir) günlük özet gelir.

---

## 7. Güncelleme

```bash
cd rtlsdr-telegram && git pull
sudo cp -r rtlsdr_telegram tools run.py requirements.txt /opt/rtlsdr-telegram/
sudo /opt/rtlsdr-telegram/venv/bin/pip install -r requirements.txt
sudo systemctl restart rtlsdr-telegram
```
`config.yaml`, veritabanı ve kayıtlarınıza dokunulmaz.

---

## 8. Sorun giderme

| Belirti | Neden / çözüm |
|---------|---------------|
| `No supported devices found` | Dongle algılanmıyor. Başka port, hub'sız, çıkar-tak. Linux'ta DVB kara listesini kontrol edin (`lsmod | grep dvb_usb_rtl28xxu` boş olmalı). |
| `usb_claim_interface error -6` | Dongle'ı başka bir program tutuyor (SDR#, başka rtl_* süreci). Kapatın. |
| Telegram testi 401 veriyor | Token yanlış. |
| Test gönderiliyor ama konuda görünmüyor | `chat_id`/`thread_id` yanlış ya da bot grupta yönetici değil. |
| `/durum` "Yetkiniz yok" diyor | Yanıttaki kullanıcı kimliğini `telegram.admins`'e ekleyin, yeniden başlatın. |
| Ses bantlarında yalnız statik kaydediliyor | Anten zayıf. `min_dynamics_db`/`threshold_dbfs` artırın veya kategoriyi susturun. |
| Pi'de CPU yüksek | `transcription.model: tiny` veya `engine: none`; `spectrum.period_s` artırın. |
| Uydu geçişi yok | TLE indirilemedi; interneti kontrol edin. Düzelince `/gecisler` takvimi gösterir. |
| Disk doluyor | `paths.retention_months` küçültün; disk koruması %10 boşluğun altında kayıtları budar. |

Loglar: `logs/rtlsdr-telegram.log`, `logs/errors.log`, araç başına bir log (`logs/adsb.log` ...).
