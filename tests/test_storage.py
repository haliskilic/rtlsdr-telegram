import time
import tempfile
from pathlib import Path

from rtlsdr_telegram.storage import Storage
from rtlsdr_telegram.events import Event, Category


def _store():
    d = tempfile.mkdtemp()
    return Storage(Path(d) / "t.db")


def test_event_insert_and_count():
    st = _store()
    ev = Event("ADS-B Uçak", Category.HAVACILIK, freq_mhz=1090.0, summary="x")
    eid = st.insert_event(ev)
    assert eid > 0
    now = time.time()
    assert st.events_count(now - 10, now + 10) == 1
    cats = st.count_by("category", now - 10, now + 10)
    assert cats and cats[0][0] == "aviation"  # language-neutral key


def test_queue_fifo_priority():
    st = _store()
    low = Event("A", Category.TARAMA, priority=5)
    high = Event("B", Category.ACIL, priority=0)
    st.queue_push(low)
    st.queue_push(high)
    qid, ev, att = st.queue_pop()
    assert ev.event_type == "B"  # yüksek öncelik (düşük sayı) önce
    st.queue_ack(qid)
    qid2, ev2, _ = st.queue_pop()
    assert ev2.event_type == "A"


def test_registry_new_then_seen():
    st = _store()
    is_new, first, count = st.registry_touch("aircraft", "abc123", {"flight": "THY1"})
    assert is_new and count == 1
    is_new2, first2, count2 = st.registry_touch("aircraft", "abc123")
    assert not is_new2 and count2 == 2 and first2 == first


def test_recordings_and_cleanup():
    st = _store()
    rid = st.add_recording(time.time(), "marine_voice", 156.8, "Kanal 16", 12.0,
                           "/tmp/x.ogg", "-20 dBFS", None)
    assert rid > 0
    assert len(st.recent_recordings(5)) == 1
    # eski kayıt ekle ve temizle
    st.add_recording(time.time() - 40 * 86400, "x", 100.0, None, 5.0, "/tmp/old.ogg", None, None)
    n, paths = st.cleanup(14)
    assert n >= 1


def test_kv():
    st = _store()
    st.kv_set("a", {"x": 1})
    assert st.kv_get("a")["x"] == 1
    assert st.kv_get("yok", "d") == "d"
