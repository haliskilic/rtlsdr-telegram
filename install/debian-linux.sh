#!/usr/bin/env bash
# Debian/Ubuntu Linux PC veya LXC kurulumu. root/sudo ile çalıştırın.
# Kaynaktan derlenen araçlar: acarsdec, dumpvdl2, AIS-catcher, rtl-ais.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ">>> APT paketleri (SDR araçları + Python)"
apt-get update -qq
apt-get install -y \
  rtl-sdr librtlsdr-dev libusb-1.0-0-dev \
  rtl-433 multimon-ng direwolf readsb satdump gr-gsm \
  ffmpeg sox \
  python3 python3-venv python3-dev python3-pip \
  python3-numpy python3-scipy python3-matplotlib python3-pil \
  python3-yaml python3-httpx python3-skyfield python3-psutil python3-aprslib \
  git cmake build-essential pkg-config \
  libsndfile1-dev libglib2.0-dev libsqlite3-dev libzmq3-dev libjansson-dev \
  libxml2-dev zlib1g-dev libncurses-dev libcurl4-openssl-dev

echo ">>> Kaynaktan derleme (acarsdec, dumpvdl2, AIS-catcher, rtl-ais)"
mkdir -p /opt/src && cd /opt/src
build() { url="$1"; dir="$2"; shift 2
  [ -d "$dir" ] || git clone --depth 1 "$url" "$dir"
  cd "/opt/src/$dir"; rm -rf build; mkdir build; cd build
  cmake .. "$@" && make -j"$(nproc)" && make install; cd /opt/src; }
build https://github.com/szpajder/libacars.git libacars; ldconfig
build https://github.com/TLeconte/acarsdec.git acarsdec -Drtl=ON || echo "acarsdec derlenemedi (atlanıyor)"
build https://github.com/szpajder/dumpvdl2.git dumpvdl2 -DRTLSDR=ON || echo "dumpvdl2 derlenemedi"
build https://github.com/jvde-github/AIS-catcher.git AIS-catcher || echo "AIS-catcher derlenemedi"
# readsb: Debian paketi RTL-SDR desteği OLMADAN derlenmiş olabilir (yalnız Beast/ifile).
if ! ldd "$(command -v readsb 2>/dev/null || echo /bin/true)" 2>/dev/null | grep -q rtlsdr; then
  echo ">>> apt readsb'de RTL-SDR desteği yok; kaynaktan derleniyor (/usr/local/bin/readsb)"
  [ -d readsb ] || git clone --depth 1 https://github.com/wiedehopf/readsb.git readsb
  ( cd readsb && make -j"$(nproc)" RTLSDR=yes AIRCRAFT_HASH_BITS=12 && install -m 755 readsb /usr/local/bin/readsb ) \
    || echo "readsb derlenemedi (ADS-B hedefi çalışmayabilir)"
fi
[ -d rtl-ais ] || git clone --depth 1 https://github.com/dgiardini/rtl-ais.git rtl-ais
cd /opt/src/rtl-ais && make -j"$(nproc)" && cp rtl_ais /usr/local/bin/ || echo "rtl-ais derlenemedi"
ldconfig

echo ">>> Ortak kurulum"
bash "$SRC_DIR/install/common.sh"

echo ">>> İsteğe bağlı: yerel transkripsiyon (faster-whisper)"
echo "    /opt/rtlsdr-telegram/venv/bin/pip install faster-whisper"
