"""Light DSP helpers: power/dBFS measurement, FM/AM demodulation, WAV writing.

Decoders such as rtl_433 and readsb do their own demodulation; this module only
serves simple measurements needed by the audio and spectrum paths.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:  # without numpy only the basic functions work
    HAVE_NUMPY = False


def u8_iq_to_complex(raw: bytes):
    """Convert rtl_sdr u8 IQ bytes into a normalized complex64 array."""
    if not HAVE_NUMPY:
        raise RuntimeError("numpy required")
    data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    data = (data - 127.5) / 127.5
    if len(data) % 2:
        data = data[:-1]
    return data[0::2] + 1j * data[1::2]


def power_dbfs(iq) -> float:
    """Mean power of complex samples (dBFS, full scale = 0)."""
    if not HAVE_NUMPY:
        return -99.0
    if len(iq) == 0:
        return -120.0
    p = float(np.mean(np.abs(iq) ** 2))
    return 10 * math.log10(p) if p > 0 else -120.0


def welch_psd(iq, nfft: int = 1024):
    """Simple Welch PSD; returns a dBFS array centred on the frequency bin index."""
    if not HAVE_NUMPY:
        raise RuntimeError("numpy required")
    n = (len(iq) // nfft) * nfft
    if n == 0:
        return np.full(nfft, -120.0, dtype=np.float32)
    seg = iq[:n].reshape(-1, nfft)
    win = np.hanning(nfft).astype(np.float32)
    seg = seg * win
    spec = np.fft.fftshift(np.fft.fft(seg, axis=1), axes=1)
    psd = np.mean(np.abs(spec) ** 2, axis=0) / (np.sum(win ** 2))
    psd = np.maximum(psd, 1e-12)
    return (10 * np.log10(psd)).astype(np.float32)


def fm_demod(iq, gain: float = 1.0):
    """Quadrature FM demodulation (differential phase)."""
    if not HAVE_NUMPY:
        raise RuntimeError("numpy required")
    if len(iq) < 2:
        return np.zeros(0, dtype=np.float32)
    prod = iq[1:] * np.conj(iq[:-1])
    return (gain * np.angle(prod)).astype(np.float32)


def am_demod(iq):
    if not HAVE_NUMPY:
        raise RuntimeError("numpy required")
    mag = np.abs(iq)
    mag = mag - np.mean(mag)
    return mag.astype(np.float32)


def write_wav(path: str | Path, samples, rate: int) -> None:
    """Write float32 [-1,1] or int16 samples as 16-bit mono WAV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if HAVE_NUMPY:
        arr = np.asarray(samples)
        if arr.dtype != np.int16:
            peak = float(np.max(np.abs(arr))) if arr.size else 0.0
            if peak > 0:
                arr = arr / peak * 0.95
            arr = (arr * 32767).astype(np.int16)
        payload = arr.tobytes()
    else:
        payload = b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(payload)


def rms_dbfs_pcm16(pcm: bytes) -> float:
    """RMS level of s16le PCM bytes (dBFS)."""
    if not pcm:
        return -120.0
    if HAVE_NUMPY:
        a = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if a.size == 0:
            return -120.0
        rms = float(np.sqrt(np.mean(a ** 2)))
    else:
        n = len(pcm) // 2
        if n == 0:
            return -120.0
        acc = 0.0
        for i in range(n):
            v = struct.unpack_from("<h", pcm, i * 2)[0] / 32768.0
            acc += v * v
        rms = math.sqrt(acc / n)
    return 20 * math.log10(rms) if rms > 0 else -120.0
