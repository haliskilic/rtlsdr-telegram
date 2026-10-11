# Windows Kurulumu

Windows'ta kaynaktan derleme zahmetlidir; hazır ikili (binary) araçlar kullanın.

## 1. Python
[python.org](https://www.python.org/downloads/) üzerinden Python 3.11+ kurun
("Add Python to PATH" işaretli).

## 2. RTL-SDR sürücüsü (Zadig)
1. Dongle'ı takın.
2. [Zadig](https://zadig.akeo.ie/) indirin, çalıştırın.
3. Options → List All Devices. "Bulk-In, Interface (0)" veya "RTL2832U" seçin.
4. Sürücü olarak **WinUSB** seçip **Replace/Install Driver** deyin.

## 3. SDR araçları (ikili)
- **rtl-sdr** (rtl_fm, rtl_power, rtl_sdr, rtl_test):
  [osmocom/rtl-sdr releases](https://github.com/osmocom/rtl-sdr/releases) veya
  [rtlsdrblog](https://www.rtl-sdr.com/tag/drivers/). ZIP'i açın, `bin` klasörünü PATH'e ekleyin.
- **rtl_433**: [releases](https://github.com/merbanan/rtl_433/releases) — exe'yi PATH'e koyun.
- **readsb/dump1090**: [dump1090 Windows derlemeleri](https://github.com/MalcolmRobb/dump1090) veya ADSBExchange paketleri.
- **SatDump**: [satdump.org](https://www.satdump.org/) Windows kurulumu.
- **multimon-ng**: [Windows derlemesi](https://github.com/EliasOenal/multimon-ng/releases).
- **AIS-catcher**: [Windows releases](https://github.com/jvde-github/AIS-catcher/releases).
- **ffmpeg**: [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) — `bin` PATH'e.
- acarsdec/dumpvdl2/gr-gsm Windows'ta zordur; bu hedefleri `enabled: false` yapabilirsiniz.

> Her aracın `.exe`'si PATH'te olmalı. Değilse `config.yaml` içinde ilgili
> `tool`/binary alanına tam yol verebilirsiniz.

## 4. Proje
```powershell
git clone https://github.com/<kullanici>/rtlsdr-telegram.git
cd rtlsdr-telegram
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy config.example.yaml config.yaml
notepad config.yaml   # token, chat_id, admins doldurun; platform: windows
venv\Scripts\python run.py --check -c config.yaml
venv\Scripts\python run.py -c config.yaml
```

## 5. Hizmet olarak (opsiyonel)
[NSSM](https://nssm.cc/) ile `run.py`'yi Windows servisi yapabilirsiniz:
```powershell
nssm install rtlsdr-telegram "C:\...\venv\Scripts\python.exe" "C:\...\run.py -c C:\...\config.yaml"
```
