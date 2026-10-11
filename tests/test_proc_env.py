"""Child tools always get a HOME (systemd root services do not export one; SatDump aborts without it)."""
import os

from rtlsdr_telegram.proc import tool_env, ManagedProcess


def test_tool_env_restores_missing_home(monkeypatch):
    monkeypatch.delenv("HOME", raising=False)
    env = tool_env({"X": "1"})
    assert env.get("HOME") and env["X"] == "1"
    mp = ManagedProcess(["true"])
    assert mp.env.get("HOME") == env["HOME"]


def test_tool_env_keeps_existing_home(monkeypatch):
    monkeypatch.setenv("HOME", "/srv/custom-home")
    assert tool_env()["HOME"] == "/srv/custom-home"
    assert os.environ["HOME"] == "/srv/custom-home"
