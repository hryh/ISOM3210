from procurement.catalog import CATEGORIES, category_ids, get_category


def test_three_categories():
    assert category_ids() == ["monitor", "keyboard", "chair"]


def test_every_category_has_attributes():
    for cid, spec in CATEGORIES.items():
        assert spec.attributes, f"{cid} has no attributes"
        for attr in spec.attributes:
            assert attr.type in ("int", "str", "bool", "list")


def test_get_category():
    assert get_category("monitor").id == "monitor"
    assert get_category("nope") is None
    assert get_category(None) is None


def test_monitor_attributes():
    spec = CATEGORIES["monitor"]
    names = [a.name for a in spec.attributes]
    assert names == ["screen_inches_min", "resolution", "connectors"]


def test_detect_category_matches_labels_and_plurals():
    from procurement.catalog import detect_category

    assert detect_category("6 monitors, 27 inch") == "monitor"
    assert detect_category("mechanical KEYBOARD for the team") == "keyboard"
    assert detect_category("2 office chairs with lumbar support") == "chair"


def test_detect_category_returns_none_for_unlisted_items():
    from procurement.catalog import detect_category

    assert detect_category("noise cancelling headphones") is None
    assert detect_category("") is None
    assert detect_category(None) is None
