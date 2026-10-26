from app.core.hero import before_after_pair, choose_hero, hero_item, notable_texts, score_snapshot


def snap(t: int, *items: tuple[str, str, bool]) -> dict:
    return {"t_ms": t, "items": [{"kind": k, "text": x, "is_new": n} for k, x, n in items]}


EMPTY_FORM = snap(0, ("heading", "Add Employee", False), ("input", "First Name", False))
FILLED = snap(
    5000,
    ("heading", "Add Employee", False),
    ("input", "Nguyễn Văn An", True),
    ("input", "Mã nhân viên 0042", True),
    ("list_item", "Personal Details", False),
    ("paragraph", "Điền họ tên và mã nhân viên rồi lưu hồ sơ nhân sự mới của công ty", False),
)
WALL = snap(9000, ("paragraph", "x" * 2000, False))


def test_the_filled_form_with_new_items_beats_the_empty_one_and_a_wall_of_text() -> None:
    hero = choose_hero([EMPTY_FORM, FILLED, WALL])
    assert hero is not None and hero.t_ms == 5000
    assert score_snapshot(FILLED, 0.5) > max(score_snapshot(EMPTY_FORM, 0), score_snapshot(WALL, 1))


def test_later_wins_a_tie_and_from_ms_limits_the_search() -> None:
    a, b = snap(1000, ("heading", "A", False)), snap(2000, ("heading", "A", False))
    assert choose_hero([a, b]).t_ms == 2000  # type: ignore[union-attr]
    assert choose_hero([EMPTY_FORM, FILLED], from_ms=6000) is None
    assert choose_hero([]) is None


def test_notable_texts_are_short_unique_and_capped() -> None:
    texts = notable_texts(
        snap(0, *[("list_item", f"item {i} " + "z" * 80, False) for i in range(20)])
    )
    assert len(texts) == 8 and all(len(t) <= 60 for t in texts)
    assert notable_texts(FILLED)[0] == "Add Employee"


def test_a_before_after_pair_needs_distance_and_something_new() -> None:
    first = snap(
        0,
        ("heading", "Add Employee", False),
        ("input", "First Name", False),
        ("button", "Save", False),
    )
    hero = snap(
        5000,
        ("heading", "Add Employee", False),
        ("input", "Nguyễn Văn An", True),
        ("input", "Mã nhân viên 0042", True),
        ("button", "Save", False),
    )
    inventory = [first, hero]
    assert before_after_pair(inventory, 5000) == (0, 5000)
    assert (
        before_after_pair(
            [first, snap(1000, *[(i["kind"], i["text"], False) for i in hero["items"]])], 1000
        )
        is None
    )  # too close
    same = snap(
        5000,
        ("heading", "Add Employee", False),
        ("input", "First Name", False),
        ("button", "Save", False),
    )
    assert before_after_pair([first, same], 5000) is None  # nothing changed
    assert before_after_pair(inventory, 7777) is None  # not a frame of the inventory
    assert (
        before_after_pair(inventory, 5000, from_ms=1000) is None
    )  # the first frame is hidden loading


def test_the_hero_item_is_what_is_new_then_a_heading_and_never_the_menu() -> None:
    items = [
        {
            "kind": "heading",
            "text": "Add Employee",
            "is_new": False,
            "region": "main",
            "bbox": {"x": 0, "y": 0, "w": 300, "h": 40},
        },
        {
            "kind": "list_item",
            "text": "Nguyễn Văn An",
            "is_new": True,
            "region": "main",
            "bbox": {"x": 0, "y": 50, "w": 300, "h": 40},
        },
        {
            "kind": "heading",
            "text": "Menu",
            "is_new": True,
            "region": "nav",
            "bbox": {"x": 0, "y": 0, "w": 100, "h": 40},
        },
    ]
    assert hero_item(items, (1440, 900))["text"] == "Nguyễn Văn An"  # type: ignore[index]
    assert hero_item(items[:1] + items[2:], (1440, 900))["text"] == "Add Employee"  # type: ignore[index]
    assert hero_item([], (1440, 900)) is None
