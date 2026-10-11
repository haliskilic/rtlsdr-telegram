"""Automatic transcription of audio recordings (feature A, spec section 4).

The engine is selected in the configuration:
  - faster_whisper (default): local, CTranslate2 based, fast on CPU.
  - whisper: the openai-whisper package (local, heavier).
  - api: an OpenAI-compatible /audio/transcriptions endpoint.
  - none: transcription disabled.

The language is auto-detected or forced per target (tr/en). Aviation and
maritime targets can use an English vocabulary hint (initial_prompt).

The heavy model is loaded lazily on first use; when it is missing or fails to
load the module degrades gracefully to "none".
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import wave
from pathlib import Path


class TranscriptionResult:
    def __init__(self, text: str = "", language: str | None = None, status: str = "empty", detail: str = ""):
        self.text = (text or "").strip()
        self.language = language
        self.status = status if self.text else ("empty" if status == "done" else status)
        self.detail = detail

    def __bool__(self) -> bool:
        return bool(self.text)


class Transcriber:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        tc = cfg.section("transcription")
        self.engine = (tc.get("engine") or "none").lower()
        self.model_name = tc.get("model", "base")
        self.device = tc.get("device", "cpu")
        self.compute_type = tc.get("compute_type", "int8")
        self.language = (tc.get("language") or "auto").lower()
        self.timeout_s = int(tc.get("timeout_s", 300))
        self.vad = bool(tc.get("vad", True))
        self.beam_size = int(tc.get("beam_size", 1))
        self.prompts = tc.get("prompts", {}) or {}
        self.api = tc.get("api", {}) or {}
        self.ffmpeg = cfg.get("audio.ffmpeg", "ffmpeg")
        self._model = None
        self._model_failed = False
        self.available = self.engine not in ("none", "")

    # -------------------------------------------------- model loading (lazy)
    def _load_local(self) -> bool:
        if self._model is not None:
            return True
        if self._model_failed:
            return False
        try:
            if self.engine == "faster_whisper":
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
            elif self.engine == "whisper":
                import whisper
                self._model = whisper.load_model(self.model_name)
            else:
                self._model_failed = True
                return False
            self.log.info("transcription: model '%s' loaded (%s)", self.model_name, self.engine)
            return True
        except Exception as e:  # model not downloaded / package missing
            self._model_failed = True
            self.log.warning("transcription model failed to load (%s): %s — transcription skipped", self.engine, e)
            return False

    # -------------------------------------------------------- audio preparation
    def _to_wav16k(self, src: str | Path) -> str | None:
        """Convert the recording to 16 kHz mono WAV (whisper input)."""
        src = str(src)
        if src.lower().endswith(".wav"):
            try:
                with wave.open(src, "rb") as w:
                    if w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2:
                        return src
            except (wave.Error, EOFError, OSError):
                pass
        fd, out = tempfile.mkstemp(suffix=".wav", prefix="asr_")
        os.close(fd)
        cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "16000", out]
        try:
            subprocess.run(cmd, check=True, timeout=120, capture_output=True)
            return out
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            self.log.warning("ffmpeg conversion error: %s", e)
            try:
                os.unlink(out)
            except OSError:
                pass
            return None

    def _lang_for(self, category: str | None, forced: str | None) -> str | None:
        if forced and forced.lower() in ("tr", "en"):
            return forced.lower()
        if self.language in ("tr", "en"):
            return self.language
        return None  # auto-detect

    def _prompt_for(self, category: str | None, override: str | None) -> str | None:
        """Vocabulary hint for the model: config override, else built-in per category key."""
        if override:
            return override
        if not category:
            return None
        if category in self.prompts:          # user-provided (keyed by category key or legacy name)
            return self.prompts[category]
        from .i18n import t
        key = f"asr.prompt.{category}"
        text = t(key)
        return None if text == key else text

    # --------------------------------------------------------------- transcribe
    def transcribe(self, audio_path: str | Path, *, category: str | None = None,
                   language: str | None = None, prompt: str | None = None) -> TranscriptionResult:
        """Transcribe the given audio file."""
        if not self.available:
            return TranscriptionResult(status="none")
        if not Path(audio_path).exists():
            return TranscriptionResult(status="failed", detail="file missing")
        lang = self._lang_for(category, language)
        prm = self._prompt_for(category, prompt)
        try:
            if self.engine == "api":
                return self._transcribe_api(audio_path, lang, prm)
            wav = self._to_wav16k(audio_path)
            if not wav:
                return TranscriptionResult(status="failed", detail="audio conversion failed")
            try:
                if not self._load_local():
                    return TranscriptionResult(status="none")
                if self.engine == "faster_whisper":
                    return self._transcribe_fw(wav, lang, prm)
                return self._transcribe_whisper(wav, lang, prm)
            finally:
                if wav != str(audio_path):
                    try:
                        os.unlink(wav)
                    except OSError:
                        pass
        except Exception as e:
            self.log.warning("transcription error: %s", e)
            return TranscriptionResult(status="failed", detail=str(e))

    @staticmethod
    def _wav_to_array(wav: str):
        """Convert the 16 kHz mono WAV to a float32 numpy array for faster-whisper.

        Passing a file path makes faster-whisper use PyAV, which breaks on version
        mismatches (metadata_errors); passing the array bypasses that path."""
        import wave as _wave
        import numpy as np
        with _wave.open(wav, "rb") as w:
            n = w.getnframes()
            raw = w.readframes(n)
            ch = w.getnchannels()
            sw = w.getsampwidth()
        if sw == 2:
            a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        elif sw == 1:
            a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
        else:
            a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1)
        return a

    def _transcribe_fw(self, wav: str, lang: str | None, prompt: str | None) -> TranscriptionResult:
        try:
            audio = self._wav_to_array(wav)
        except Exception:
            audio = wav  # last resort: file path (PyAV)
        segments, info = self._model.transcribe(
            audio, language=lang, beam_size=self.beam_size, vad_filter=self.vad,
            initial_prompt=prompt, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segments).strip()
        return TranscriptionResult(text, getattr(info, "language", lang), "done")

    def _transcribe_whisper(self, wav: str, lang: str | None, prompt: str | None) -> TranscriptionResult:
        res = self._model.transcribe(wav, language=lang, initial_prompt=prompt,
                                     condition_on_previous_text=False, fp16=False)
        return TranscriptionResult(res.get("text", ""), res.get("language", lang), "done")

    def _transcribe_api(self, audio_path: str | Path, lang: str | None, prompt: str | None) -> TranscriptionResult:
        import httpx
        base = self.api.get("base_url", "https://api.openai.com/v1").rstrip("/")
        key = self.api.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
        model = self.api.get("model", "whisper-1")
        if not key:
            return TranscriptionResult(status="failed", detail="API key missing")
        data = {"model": model}
        if lang:
            data["language"] = lang
        if prompt:
            data["prompt"] = prompt
        with open(audio_path, "rb") as fh:
            files = {"file": (Path(audio_path).name, fh, "application/octet-stream")}
            headers = {"Authorization": f"Bearer {key}"}
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.post(f"{base}/audio/transcriptions", data=data, files=files, headers=headers)
            r.raise_for_status()
            js = r.json()
        return TranscriptionResult(js.get("text", ""), js.get("language", lang), "done")


class TranscriptionWorker:
    """Transcribes events with audio attachments in the background.

    Targets produce audio events with `transcript_status="pending"` and route
    them here. The worker transcribes WITHOUT holding the dongle (own thread),
    fills the event's summary/transcript and hands it to the Dispatcher (audio
    and text go out in the same message thread). Without an engine the event is
    forwarded directly.
    """

    def __init__(self, transcriber: "Transcriber", dispatcher, storage, logger):
        import queue
        self.transcriber = transcriber
        self.dispatcher = dispatcher
        self.st = storage
        self.log = logger
        self._q: "queue.Queue" = queue.Queue()
        self._stop = False
        self._thread = None

    def start(self):
        import threading
        self._thread = threading.Thread(target=self._loop, name="transcriber", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=10)

    def submit(self, event):
        if not self.transcriber or not self.transcriber.available:
            event.transcript_status = "none"
            self.dispatcher.submit(event)
            return
        self._q.put(event)

    def _loop(self):
        while not self._stop:
            ev = self._q.get()
            if ev is None:
                break
            try:
                self._process(ev)
            except Exception as e:
                self.log.warning("transcription worker error: %s", e)
                ev.transcript_status = "failed"
            finally:
                self.dispatcher.submit(ev)

    def _process(self, ev):
        audio_att = next((a for a in ev.attachments if a.kind in ("voice", "audio")), None)
        if not audio_att:
            ev.transcript_status = "none"
            return
        res = self.transcriber.transcribe(
            audio_att.path, category=ev.category.value,
            language=ev.transcription_language, prompt=ev.transcription_prompt)
        ev.transcript = res.text
        ev.transcript_lang = res.language
        ev.transcript_status = res.status
        if res.text:
            # update the summary with the first transcript line
            ev.summary = (ev.summary + " · " if ev.summary else "") + res.text.strip().splitlines()[0][:80]
            rec_id = ev.extra.get("recording_id")
            if rec_id:
                try:
                    self.st._exec("UPDATE recordings SET transcript=? WHERE id=?", (res.text, rec_id))
                except Exception:
                    pass
