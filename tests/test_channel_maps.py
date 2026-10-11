from rtlsdr_telegram.channel_maps import channel_name, describe, MARINE, PMR446, CB


def test_marine_ch16():
    assert "16" in (channel_name(156.800, "marine") or "")


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
