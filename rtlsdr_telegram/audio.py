"""Eşik tetiklemeli ses kaydı (madde 2, ses üreten hedefler; madde 3).

rtl_fm'den s16le PCM akışını okur, kendi VOX (ses varlığı) algılamasını yapar:
seviye eşiği aşılınca segment başlar, sessizlik `hangover_s` kadar sürünce
segment kapanır ve dosyaya yazılır. Her segment için (yol, süre, tepe/ortalama
seviye) döndürülür. rtl_fm'in squelch davranışından bağımsız çalışır.

Kapanan her dosya ffmpeg ile ogg/opus'a (veya mp3) çevrilir; ham WAV isteğe bağlı
tutulur. Dosya daha sonra Dispatcher tarafından gönderilir ve Transcriber ile
yazıya dökülür.
"""
from __future__ import annotations

import math
import struct
import subprocess
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .proc import ManagedProcess


def _rms_dbfs(block: bytes) -> float:
    n = len(block) // 2
    if n == 0:
        return -120.0
    try:
        import numpy as np
        a = np.frombuffer(block, dtype="<i2").astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
    except ImportError:
        acc = 0.0
        for i in range(n):
            v = struct.unpack_from("<h", block, i * 2)[0] / 32768.0
            acc += v * v
        rms = math.sqrt(acc / n)
    return 20 * math.log10(rms) if rms > 0 else -120.0


@dataclass
class Segment:
    path: str
    start_utc: datetime
    duration_s: float
    peak_dbfs: float
    mean_dbfs: float
    freq_hz: int
    final_path: str = ""
    channel: str | None = None


class AudioRecorder:
    """Verilen frekansta bir zaman penceresi boyunca etkinlik segmentlerini kaydeder."""

    def __init__(self, cfg, sdr, logger):
        self.cfg = cfg
        self.sdr = sdr
        self.log = logger
        a = cfg.section("audio")
        self.out_format = a.get("format", "ogg")
        self.ffmpeg = a.get("ffmpeg", "ffmpeg")
        self.opus_bitrate = a.get("opus_bitrate", "24k")
        self.keep_wav = bool(a.get("keep_wav", False))
        self.rec_dir = cfg.recordings_dir
        self.tmp_dir = cfg.data_dir / "tmp"
        try:
            from zoneinfo import ZoneInfo
            self.tz = ZoneInfo(cfg.get("timezone", "Europe/Istanbul"))
        except Exception:
            self.tz = timezone.utc

    def record_window(self, freq_hz: int, duration_s: float, stop_event: threading.Event, *,
                      mode: str = "fm", audio_rate: int = 16000, threshold_dbfs: float = -45.0,
                      hangover_s: float = 1.5, min_segment_s: float = 0.6,
                      max_segment_s: float = 120.0, gain=None, squelch: int = 0,
                      channel: str | None = None, prefix: str = "rec",
                      require_dynamics: bool = True, min_dynamics_db: float = 2.5) -> list[Segment]:
        """Pencere boyunca kayıt yapıp tamamlanan segmentleri döndürür."""
        try:
            cmd = self.sdr.rtl_fm_cmd(freq_hz, mode=mode, sample_rate=audio_rate,
                                      resample=audio_rate, gain=gain, squelch=squelch)
        except Exception as e:
            self.log.warning("rtl_fm komutu kurulamadı: %s", e)
            return []
        proc = ManagedProcess(cmd, name=f"{prefix}-rtlfm", text_stdout=False,
                              log_path=self.cfg.log_dir / f"{prefix}_rtlfm.log")
        segments: list[Segment] = []
        try:
            self.sdr.wait_ready()
        except Exception:
            pass
        try:
            proc.start()
        except Exception as e:
            self.log.warning("rtl_fm başlatılamadı: %s", e)
            return []

        bytes_per_s = audio_rate * 2
        block_bytes = max(2, int(bytes_per_s * 0.1))  # ~100 ms blok
        deadline = time.time() + duration_s

        active = False
        buf = bytearray()
        seg_start = 0.0
        last_voice = 0.0
        peak = -120.0
        acc_lin = 0.0
        acc_n = 0
        levels: list[float] = []

        def finalize():
            nonlocal buf, peak, acc_lin, acc_n, active, levels
            dur = len(buf) / bytes_per_s
            # Dinamik-aralık (dynamics) kapısı: FM statiği/taşıyıcısı düz seviyelidir;
            # gerçek konuşma hecelerle dalgalanır. Seviye std sapması düşükse (düz),
            # muhtemelen gürültü/taşıyıcıdır — reddet. (min_dynamics_db ile ayarlanır)
            flat = False
            if require_dynamics and len(levels) >= 4:
                m = sum(levels) / len(levels)
                var = sum((x - m) ** 2 for x in levels) / len(levels)
                std = var ** 0.5
                flat = std < min_dynamics_db
            if dur >= min_segment_s and not flat:
                seg = self._write_segment(bytes(buf), audio_rate, freq_hz, seg_start, dur,
                                          peak, acc_lin, acc_n, channel, prefix)
                if seg:
                    segments.append(seg)
            elif flat:
                self.log.debug("segment reddedildi (düz seviye, muhtemelen statik): std<%.1f dB", min_dynamics_db)
            buf = bytearray()
            peak = -120.0
            acc_lin = 0.0
            acc_n = 0
            levels = []
            active = False

        try:
            while time.time() < deadline and not stop_event.is_set():
                block = proc.read_stdout_bytes(block_bytes, timeout=0.5)
                now = time.time()
                if block == b"":
                    break  # EOF: rtl_fm bitti/çöktü
                if block is None:
                    # Veri yok (squelch kapalı ya da duraklama): sessizlik olarak işle
                    if active and now - last_voice >= hangover_s:
                        finalize()
                    if not proc.running:
                        break
                    continue
                lvl = _rms_dbfs(block)
                if lvl >= threshold_dbfs:
                    if not active:
                        active = True
                        seg_start = now
                        buf = bytearray()
                        peak = lvl
                        acc_lin = 0.0
                        acc_n = 0
                    last_voice = now
                    buf += block
                    peak = max(peak, lvl)
                    acc_lin += 10 ** (lvl / 10)
                    acc_n += 1
                    levels.append(lvl)
                    if len(buf) / bytes_per_s >= max_segment_s:
                        finalize()
                elif active:
                    buf += block  # hangover sırasında da yaz
                    if now - last_voice >= hangover_s:
                        # kuyruk sessizliğini kırp
                        tail = int(hangover_s * bytes_per_s)
                        if len(buf) > tail:
                            buf = buf[:-tail]
                        finalize()
            if active:
                finalize()
        finally:
            proc.stop()
            try:
                self.sdr.mark_released()
            except Exception:
                pass
        return segments

    def _write_segment(self, pcm: bytes, rate: int, freq_hz: int, start_ts: float, dur: float,
                       peak: float, acc_lin: float, acc_n: int, channel, prefix) -> Segment | None:
        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        mean = 10 * math.log10(acc_lin / acc_n) if acc_n else peak
        stamp = start_dt.astimezone(self.tz).strftime("%Y%m%d-%H%M%S")
        base = f"{prefix}_{stamp}_{freq_hz // 1000}k"
        wav_path = self.tmp_dir / f"{base}.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with wave.open(str(wav_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm)
        except (wave.Error, OSError) as e:
            self.log.warning("WAV yazılamadı: %s", e)
            return None
        seg = Segment(str(wav_path), start_dt, dur, peak, mean, freq_hz, channel=channel)
        final = self._encode(wav_path, base)
        seg.final_path = final or str(wav_path)
        if final and final != str(wav_path) and not self.keep_wav:
            try:
                wav_path.unlink()
            except OSError:
                pass
        return seg

    def _encode(self, wav_path: Path, base: str) -> str | None:
        """WAV'ı hedef formata çevirir; ffmpeg yoksa WAV döndürür."""
        if self.out_format == "wav":
            dst = self.rec_dir / f"{base}.wav"
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if str(wav_path) != str(dst):
                    import shutil
                    shutil.copy2(wav_path, dst)
                return str(dst)
            except OSError:
                return str(wav_path)
        ext = "ogg" if self.out_format == "ogg" else "mp3"
        dst = self.rec_dir / f"{base}.{ext}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if self.out_format == "ogg":
            cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path),
                   "-c:a", "libopus", "-b:a", self.opus_bitrate, "-application", "voip", str(dst)]
        else:
            cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path),
                   "-c:a", "libmp3lame", "-b:a", "48k", str(dst)]
        try:
            subprocess.run(cmd, check=True, timeout=120, capture_output=True)
            return str(dst)
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            self.log.warning("ses kodlama hatası (%s), WAV kullanılacak: %s", self.out_format, e)
            # WAV'ı kayıt klasörüne taşı
            try:
                fallback = self.rec_dir / f"{base}.wav"
                import shutil
                shutil.copy2(wav_path, fallback)
                return str(fallback)
            except OSError:
                return str(wav_path)
