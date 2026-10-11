"""Shared management of the single RTL-SDR dongle.

Only one process can open the dongle at a time. This class "leases" it with a
mutex: while one target uses the dongle nobody else can take it. The scheduler
coordinates the leases.

It also provides hardware probing (rtl_test) and command builders for rtl_power
sweeps, rtl_fm demodulation and raw IQ capture.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..proc import ManagedProcess, run_capture, which


class SdrError(Exception):
    pass


@dataclass
class DeviceInfo:
    present: bool
    index: int = 0
    name: str = ""
    tuner: str = ""
    serial: str = ""
    detail: str = ""


class DeviceLease:
    """Holds the dongle for the duration of a `with manager.lease(owner):` block."""

    def __init__(self, manager: "SdrManager", owner: str):
        self.manager = manager
        self.owner = owner

    def __enter__(self) -> "SdrManager":
        self.manager._acquire(self.owner)
        return self.manager

    def __exit__(self, *exc) -> None:
        self.manager._release(self.owner)


class SdrManager:
    """Serializes access to the dongle."""

    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        sdr = cfg.section("sdr")
        self.device_index = int(sdr.get("device_index", 0))
        self.serial = str(sdr.get("serial", "") or "")
        self.sample_rate = int(sdr.get("sample_rate", 2400000))
        self.gain = sdr.get("gain", 40)
        self.ppm = int(sdr.get("ppm", 0))
        self.bias_tee = bool(sdr.get("bias_tee", False))
        self.library_path = sdr.get("library_path", "")
        self._lock = threading.RLock()
        self._owner: str | None = None
        self._owner_since = 0.0
        self.info: DeviceInfo | None = None
        self._probe_ts = 0.0
        self._probe_ttl = 30.0
        # Minimum gap between consecutive opens so libusb releases the device;
        # otherwise the next tool fails with "usb_claim_interface error -6".
        self._last_release = 0.0
        self.release_gap_s = 1.0
        # external tool paths
        self.bin_rtl_test = which("rtl_test")
        self.bin_rtl_fm = which("rtl_fm")
        self.bin_rtl_power = which("rtl_power")
        self.bin_rtl_sdr = which("rtl_sdr")
        self.bin_rtl_eeprom = which("rtl_eeprom")

    # --------------------------------------------------------------- hardware
    def probe(self, force: bool = False) -> DeviceInfo:
        """Probe the dongle with rtl_test; reports 'busy' when another process holds it.

        rtl_test never exits on its own (it keeps sampling), so we read its output
        briefly and terminate it. The result is cached for a short time because
        the scheduler asks on every loop."""
        now = time.time()
        if not force and self.info is not None and (now - self._probe_ts) < self._probe_ttl:
            return self.info
        if not self.bin_rtl_test:
            self.info = DeviceInfo(False, detail="rtl_test not found (rtl-sdr not installed)")
            self._probe_ts = now
            return self.info
        lines: list[str] = []
        from ..proc import ManagedProcess
        proc = ManagedProcess([self.bin_rtl_test], name="rtl_test",
                              on_stderr=lambda l: lines.append(l))
        try:
            proc.start()
            deadline = now + 3.0
            while time.time() < deadline:
                text_now = "\n".join(lines)
                if "Sampling at" in text_now or "No supported devices" in text_now or "usb_claim" in text_now:
                    break
                if not proc.running:
                    break
                time.sleep(0.1)
        finally:
            proc.stop(timeout=2)
            self._last_release = time.time()
        text = "\n".join(lines)
        self._probe_ts = time.time()
        m = re.search(r"Found (\d+) device", text)
        if not m or int(m.group(1)) == 0:
            if "usb_claim_interface error" in text or "Device or resource busy" in text or "usb_open error" in text:
                self.info = DeviceInfo(True, detail="dongle busy (another process may be using it)")
                return self.info
            self.info = DeviceInfo(False, detail="dongle not found")
            return self.info
        name = tuner = serial = ""
        for line in text.splitlines():
            dm = re.match(r"\s*(\d+):\s+(.*?),\s+(.*?),\s+SN:\s*(\S+)", line)
            if dm and int(dm.group(1)) == self.device_index:
                name, serial = dm.group(3).strip(), dm.group(4).strip()
        tm = re.search(r"Found (.*?) tuner", text)
        if tm:
            tuner = tm.group(1).strip()
        self.info = DeviceInfo(True, self.device_index, name, tuner, serial,
                               detail=f"{name or 'RTL-SDR'} / {tuner or 'unknown tuner'}")
        return self.info

    def device_present(self) -> bool:
        # if the dongle is currently leased by a target it is certainly present
        if self._owner is not None:
            return True
        info = self.probe()
        return info.present

    def note_device_ok(self) -> None:
        """A target used the dongle successfully — mark present and refresh the probe time."""
        self.info = DeviceInfo(True, self.device_index, detail=(self.info.detail if self.info else "RTL-SDR"))
        self._probe_ts = time.time()

    # ----------------------------------------------------------- leasing
    def lease(self, owner: str) -> DeviceLease:
        return DeviceLease(self, owner)

    def _acquire(self, owner: str, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if self._owner is None:
                    gap = self.release_gap_s - (time.time() - self._last_release)
                    if gap <= 0:
                        self._owner = owner
                        self._owner_since = time.time()
                        return
                elif self._owner == owner:
                    return
            if time.time() > deadline:
                raise SdrError(f"dongle is held by '{self._owner}', '{owner}' could not acquire it")
            time.sleep(0.1)

    def _release(self, owner: str) -> None:
        with self._lock:
            if self._owner == owner:
                self._owner = None
                self._owner_since = 0.0
                self._last_release = time.time()

    def mark_released(self) -> None:
        """A subprocess that used the dongle stopped — restart the release gap timer."""
        self._last_release = time.time()

    def wait_ready(self) -> None:
        """Wait for the minimum gap between consecutive tools in one slot (rtl_power -> rtl_fm)
        so libusb has released the device."""
        gap = self.release_gap_s - (time.time() - self._last_release)
        if gap > 0:
            time.sleep(gap)

    @property
    def current_owner(self) -> str | None:
        return self._owner

    def force_release(self) -> None:
        with self._lock:
            self._owner = None

    # ------------------------------------------------- argument helpers
    def _dev_args(self, prefix_d: str = "-d") -> list[str]:
        return [prefix_d, str(self.device_index)]

    def gain_args(self, gain=None, flag: str = "-g") -> list[str]:
        g = self.gain if gain is None else gain
        if g is None or str(g).strip().lower() in ("auto", "agc", "-1", ""):
            return []
        return [flag, str(g)]

    @staticmethod
    def is_auto_gain(g) -> bool:
        return g is None or str(g).strip().lower() in ("auto", "agc", "-1", "")

    # ---------------------------------------------------------- rtl_power
    def power_scan(self, start_hz: int, end_hz: int, bin_hz: int, *, integration: str = "1",
                   gain=None, oneshot: bool = True, crop: int = 0, log_path=None) -> ManagedProcess:
        """Build the rtl_power process (CSV on stdout); the caller parses the lines."""
        if not self.bin_rtl_power:
            raise SdrError("rtl_power not found")
        self.wait_ready()
        cmd = [self.bin_rtl_power, "-f", f"{start_hz}:{end_hz}:{bin_hz}", "-i", str(integration),
               "-p", str(self.ppm)] + self.gain_args(gain)
        if crop:
            cmd += ["-c", f"{crop}%"]
        if oneshot:
            cmd += ["-1"]
        cmd += self._dev_args()
        return ManagedProcess(cmd, name="rtl_power", log_path=log_path)

    # ------------------------------------------------------------- rtl_fm
    def rtl_fm_cmd(self, freq_hz: int, *, mode: str = "fm", sample_rate: int = 24000,
                   resample: int | None = None, gain=None, squelch: int = 0,
                   extra: list[str] | None = None) -> list[str]:
        """Build the rtl_fm command line (raw s16le PCM on stdout)."""
        if not self.bin_rtl_fm:
            raise SdrError("rtl_fm not found")
        cmd = [self.bin_rtl_fm, "-M", mode, "-f", str(freq_hz), "-s", str(sample_rate),
               "-p", str(self.ppm), "-l", str(squelch)] + self.gain_args(gain) + self._dev_args()
        if resample:
            cmd += ["-r", str(resample)]
        if extra:
            cmd += list(extra)
        cmd += ["-"]
        return cmd

    def iq_cmd(self, freq_hz: int, sample_rate: int, *, gain=None, num_samples: int | None = None) -> list[str]:
        """rtl_sdr raw IQ (u8) capture command — to stdout."""
        if not self.bin_rtl_sdr:
            raise SdrError("rtl_sdr not found")
        cmd = [self.bin_rtl_sdr, "-f", str(freq_hz), "-s", str(sample_rate), "-p", str(self.ppm)]
        cmd += self.gain_args(gain)
        if num_samples:
            cmd += ["-n", str(num_samples)]
        cmd += self._dev_args()
        cmd += ["-"]
        return cmd
