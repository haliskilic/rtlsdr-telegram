"""Bot access control: only admins in the configured group (or admin DMs) may act;
foreign chats are ignored and left automatically."""
import logging
import tempfile
from pathlib import Path

from rtlsdr_telegram.config import load_config
from rtlsdr_telegram.storage import Storage
from rtlsdr_telegram.commands import CommandHandler
from rtlsdr_telegram.i18n import set_language

GROUP = -1003000000000
ADMIN = 111
STRANGER = 999


class FakeClient:
    def __init__(self):
        self.sent = []
        self.left = []
    def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text)); return [1]
    def leave_chat(self, chat_id):
        self.left.append(chat_id); return True
    def get_updates(self, *a, **k): return []


class FakeSched:
    targets = []
    def status_dict(self):
        return {"device_present": True, "current_name": "x", "current_freq": "—", "current_since_s": 0,
                "next_info": "", "queue_len": 0, "muted": [], "boosts": {}}
    sdr = type("S", (), {"info": None})()


def _handler(client):
    set_language("en")
    cfg = load_config()
    cfg.data["telegram"].update({"chat_id": GROUP, "admins": [ADMIN], "allow_private_admin_commands": True})
    st = Storage(Path(tempfile.mkdtemp()) / "t.db")
    h = CommandHandler(cfg, client, FakeSched(), st, None, None, logging.getLogger("t"), 0)
    # replace the real handler (needs psutil/scheduler) with a marker
    for k in ("status", "durum"):
        h.handlers[k] = lambda args, reply, uid: client.sent.append((reply["chat_id"], "STATUS"))
    return h


def _update(chat_id, user_id, text, chat_type="supergroup"):
    return {"update_id": 1, "message": {"message_id": 5, "text": text,
                                        "chat": {"id": chat_id, "type": chat_type},
                                        "from": {"id": user_id}}}


def test_admin_in_group_is_served():
    c = FakeClient(); h = _handler(c)
    h._handle_update(_update(GROUP, ADMIN, "/status"))
    assert c.sent and c.sent[-1][1] == "STATUS"


def test_stranger_in_group_gets_hint_only():
    c = FakeClient(); h = _handler(c)
    h._handle_update(_update(GROUP, STRANGER, "/status"))
    assert c.sent and "Not authorized" in c.sent[-1][1] and "STATUS" not in c.sent[-1][1]


def test_foreign_group_is_ignored_silently():
    c = FakeClient(); h = _handler(c)
    h._handle_update(_update(-1009999999999, ADMIN, "/status"))
    h._handle_update(_update(-1009999999999, STRANGER, "/status"))
    assert c.sent == []


def test_stranger_private_chat_gets_no_reply():
    c = FakeClient(); h = _handler(c)
    h._handle_update(_update(STRANGER, STRANGER, "/status", chat_type="private"))
    assert c.sent == []


def test_admin_private_chat_is_served():
    c = FakeClient(); h = _handler(c)
    h._handle_update(_update(ADMIN, ADMIN, "/status", chat_type="private"))
    assert c.sent and c.sent[-1][1] == "STATUS"


def test_added_to_foreign_group_leaves():
    c = FakeClient(); h = _handler(c)
    h._handle_update({"update_id": 2, "my_chat_member": {
        "chat": {"id": -1008888888888, "type": "supergroup", "title": "Strangers"},
        "from": {"id": STRANGER}, "new_chat_member": {"status": "member"}}})
    assert c.left == [-1008888888888]
    # the configured group is never left
    h._handle_update({"update_id": 3, "my_chat_member": {
        "chat": {"id": GROUP, "type": "supergroup", "title": "Mine"},
        "from": {"id": ADMIN}, "new_chat_member": {"status": "administrator"}}})
    assert c.left == [-1008888888888]


def test_empty_admin_list_refuses_everyone():
    c = FakeClient(); h = _handler(c)
    h.admins = set()
    h._handle_update(_update(GROUP, ADMIN, "/status"))
    assert c.sent and "Not authorized" in c.sent[-1][1]
