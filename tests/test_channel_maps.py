from rtlsdr_telegram.channel_maps import channel_name, describe, MARINE, PMR446, CB
from rtlsdr_telegram.i18n import set_language


def test_marine_ch16_bilingual():
    set_language("en")
    assert channel_name(156.800, "marine") == "Channel 16 (Distress/Calling)"
    set_language("tr")
    assert channel_name(156.800, "marine") == "Kanal 16 (Acil/Çağrı)"
    set_language("en")


def test_pmr_channel():
    assert "PMR" in (channel_name(446.00625, "pmr") or "")


def test_cb_channel():
    name = channel_name(27.185, "cb")
    assert name and "19" in name


def test_describe_format():
    d = describe(156.800, "marine")
    assert "MHz" in d and "16" in d


def test_tables_nonempty():
    assert len(MARINE) > 20 and len(PMR446) == 16 and len(CB) == 40
