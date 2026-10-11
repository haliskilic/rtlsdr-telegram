# Proxmox LXC Kurulumu (USB RTL-SDR geçişi)

Bu depo, 192.168.1.250 adresindeki Proxmox üzerinde ayrıcalıksız bir LXC'ye
kurulmak üzere hazırlandı. Adımlar her Proxmox için geçerlidir.

## 1. Host hazırlığı: DVB sürücüsünü kara listeye al
RTL2832U takılınca kernel onu bir DVB-T TV alıcısı sanıp sahiplenir. SDR için
bunu engellemek gerekir (host'ta):
```bash
cat > /etc/modprobe.d/blacklist-rtlsdr.conf <<'BL'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
blacklist rtl2832_sdr
blacklist dvb_usb_v2
BL
for m in rtl2832_sdr dvb_usb_rtl28xxu rtl2832 dvb_usb_v2; do rmmod $m 2>/dev/null; done

cat > /etc/udev/rules.d/20-rtlsdr.rules <<'UD'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666", SYMLINK+="rtl_sdr"
UD
udevadm control --reload-rules && udevadm trigger
```

## 2. LXC oluştur (ayrıcalıksız, nesting)
```bash
pct create 102 local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst \
  --hostname rtlsdr-telegram --cores 4 --memory 2048 --swap 1024 \
  --rootfs local-lvm:16 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --onboot 1
```

## 3. USB geçişi
LXC yapılandırmasına (`/etc/pve/lxc/102.conf`) ekleyin:
```
lxc.cgroup2.devices.allow: c 189:* rwm
lxc.mount.entry: /dev/bus/usb dev/bus/usb none bind,optional,create=dir
```
> Not: Bu yöntem USB bus'ını bind eder. Dongle'ı host'a taktığınızda konteyner
> içinde `rtl_test` ile görünür. Dongle farklı bir fiziksel porta takılırsa
> bus/aygıt numarası değişebilir; kalıcılık için host udev + sembolik link
> veya belirli bir USB aygıtını `dev0: /dev/...` ile geçirme tercih edilebilir.

## 4. Konteyner içinde kurulum
```bash
pct start 102
pct exec 102 -- bash
# konteyner içinde:
apt update && apt install -y git
git clone <repo-url> /opt/rtlsdr-telegram-src
cd /opt/rtlsdr-telegram-src
bash install/debian-linux.sh
nano /opt/rtlsdr-telegram/config.yaml
systemctl enable --now rtlsdr-telegram
```

## 5. Doğrulama
```bash
pct exec 102 -- rtl_test            # "Found 1 device(s)" görmelisiniz (dongle takılıysa)
pct exec 102 -- systemctl status rtlsdr-telegram
pct exec 102 -- journalctl -u rtlsdr-telegram -f
```

## Sorun: "No supported devices found"
- Dongle host'a fiziksel takılı mı? Host'ta `lsusb | grep 0bda`.
- DVB modülü yeniden yüklenmiş olabilir: host'ta `lsmod | grep rtl`, gerekiyorsa
  `rmmod dvb_usb_rtl28xxu`.
- LXC `102.conf` içinde cgroup/mount satırları var mı? Değişiklik sonrası
  `pct stop 102 && pct start 102`.
