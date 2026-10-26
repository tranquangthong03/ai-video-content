from app.core.hero import choose_hero, notable_texts, score_snapshot


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
