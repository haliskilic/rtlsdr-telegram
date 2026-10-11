"""Alt süreç (subprocess) yönetimi için ortak yardımcılar.

Harici araçları (rtl_fm, rtl_433, dump1090/readsb, direwolf, satdump ...) başlatıp
satır satır çıktı okuyan, çökerse kontrollü kapanan, log dosyasına yazan sınıf.
"""
from __future__ import annotations

import collections
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable


def which(*names: str) -> str | None:
    import shutil
    for n in names:
        if not n:
            continue
        p = shutil.which(n)
        if p:
            return p
    return None


class ManagedProcess:
    """Bir alt süreci başlatır; stdout satırlarını bir geri çağırmaya iletir.

    `stderr` ayrı iş parçacığında log dosyasına yazılır. `stop()` önce SIGTERM,
    sonra SIGKILL dener; süreç grubu (setsid) ile çocuk süreçler de temizlenir.
    """

    def __init__(self, cmd: list[str], *, name: str = "", on_line: Callable[[str], None] | None = None,
                 on_stderr: Callable[[str], None] | None = None, log_path: str | Path | None = None,
                 env: dict | None = None, cwd: str | Path | None = None, text_stdout: bool = True):
        self.cmd = [str(c) for c in cmd]
        self.name = name or Path(self.cmd[0]).name
        self.on_line = on_line
        self.on_stderr = on_stderr
        self.log_path = Path(log_path) if log_path else None
        self.env = {**os.environ, **(env or {})}
        self.cwd = str(cwd) if cwd else None
        self.text_stdout = text_stdout
        self.proc: subprocess.Popen | None = None
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self.started_at = 0.0
        self._logfh = None
        # ikili (binary) stdout için zaman aşımılı okuma kuyruğu
        self._bin_q: "queue.Queue[bytes | None]" = queue.Queue(maxsize=256)
        self._bin_chunk = 4096
        # son stderr satırları (cihaz açma hatası tespiti için)
        self.stderr_tail: "collections.deque[str]" = collections.deque(maxlen=30)

    def start(self) -> None:
        self._stop.clear()
        creation = {}
        if os.name == "posix":
            creation["start_new_session"] = True
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._logfh = open(self.log_path, "a", encoding="utf-8", errors="replace")
            self._logfh.write(f"\n===== {self.name} start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            self._logfh.write("CMD: " + " ".join(self.cmd) + "\n")
            self._logfh.flush()
        self.proc = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            bufsize=1 if self.text_stdout else 0,
            universal_newlines=self.text_stdout,
            env=self.env, cwd=self.cwd, **creation,
        )
        self.started_at = time.time()
        if self.text_stdout:
            t = threading.Thread(target=self._pump_stdout, daemon=True, name=f"{self.name}-out")
        else:
            t = threading.Thread(target=self._pump_binary, daemon=True, name=f"{self.name}-bin")
        t.start()
        self._threads.append(t)
        t2 = threading.Thread(target=self._pump_stderr, daemon=True, name=f"{self.name}-err")
        t2.start()
        self._threads.append(t2)

    def _pump_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            for line in self.proc.stdout:
                if self._stop.is_set():
                    break
                line = line.rstrip("\n")
                if self.on_line:
                    try:
                        self.on_line(line)
                    except Exception:
                        pass
        except (ValueError, OSError):
            pass

    def _pump_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        try:
            for raw in self.proc.stderr:
                if self._stop.is_set():
                    break
                line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                line = line.rstrip("\n")
                self.stderr_tail.append(line)
                if self._logfh:
                    self._logfh.write(line + "\n")
                    self._logfh.flush()
                if self.on_stderr:
                    try:
                        self.on_stderr(line)
                    except Exception:
                        pass
        except (ValueError, OSError):
            pass

    def _pump_binary(self) -> None:
        """İkili stdout'u parçalar halinde kuyruğa akıtır (okuyucu bloklanmasın)."""
        assert self.proc and self.proc.stdout
        try:
            while not self._stop.is_set():
                chunk = self.proc.stdout.read(self._bin_chunk)
                if not chunk:
                    break
                try:
                    self._bin_q.put(chunk, timeout=2)
                except queue.Full:
                    # tüketici yavaş; en eskiyi at (gerçek zamanlı ses için kabul edilebilir)
                    try:
                        self._bin_q.get_nowait()
                    except queue.Empty:
                        pass
        except (ValueError, OSError):
            pass
        finally:
            try:
                self._bin_q.put_nowait(None)  # EOF işareti
            except queue.Full:
                pass

    def read_stdout_bytes(self, size: int, timeout: float = 0.5) -> bytes | None:
        """İkili stdout'tan en fazla `size` bayt okur; `timeout` içinde veri yoksa None.

        Süreç sustuğunda (örn. squelch kapalıyken rtl_fm) çağıran bloklanmaz;
        None 'veri yok' demektir, b'' ise EOF (süreç bitti)."""
        buf = bytearray()
        deadline = time.time() + timeout
        while len(buf) < size:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                chunk = self._bin_q.get(timeout=remaining)
            except queue.Empty:
                break
            if chunk is None:
                return bytes(buf) if buf else b""
            buf += chunk
        return bytes(buf) if buf else None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def returncode(self) -> int | None:
        return self.proc.poll() if self.proc else None

    def wait(self, timeout: float | None = None) -> int | None:
        if not self.proc:
            return None
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if not self.proc:
            return
        if self.proc.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                else:
                    self.proc.terminate()
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "posix":
                        os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                    else:
                        self.proc.kill()
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        for fh in (self.proc.stdout, self.proc.stderr):
            try:
                if fh:
                    fh.close()
            except OSError:
                pass
        if self._logfh:
            try:
                self._logfh.write(f"===== {self.name} stop rc={self.returncode} =====\n")
                self._logfh.close()
            except (ValueError, OSError):
                pass
            self._logfh = None


DEVICE_ERROR_MARKERS = ("usb_claim_interface", "Failed to open rtlsdr device", "usb_open error",
                        "No supported devices found", "Device or resource busy")


def looks_like_device_error(lines: Iterable[str]) -> bool:
    """stderr satırlarında dongle açılamadı/meşgul belirtisi var mı?"""
    for ln in lines:
        for m in DEVICE_ERROR_MARKERS:
            if m in ln:
                return True
    return False


def shell_pipeline(pipeline: str) -> list[str]:
    """Boru içeren bir komut dizgesini platforma uygun kabukla çalıştırmak için argv üretir."""
    if os.name == "nt":
        return ["cmd", "/c", pipeline]
    return ["bash", "-c", pipeline]


def run_capture(cmd: Iterable[str], timeout: float = 30, env: dict | None = None) -> tuple[int, str, str]:
    """Kısa ömürlü komutu çalıştırıp (rc, stdout, stderr) döndürür."""
    def _dec(x):
        if x is None:
            return ""
        return x.decode("utf-8", "replace") if isinstance(x, bytes) else x
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})})
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, _dec(e.stdout), _dec(e.stderr) + "\n[zaman aşımı]"
    except FileNotFoundError:
        return 127, "", "komut bulunamadı"
    except OSError as e:
        return 1, "", str(e)
