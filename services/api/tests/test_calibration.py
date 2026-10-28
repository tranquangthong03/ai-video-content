from scripts import critic_calibration as cc


def test_the_filled_tables_are_read_and_blank_cells_are_left_out() -> None:
    text = (
        "## A (`orangehrm`)\n\n| Tiêu chí | Câu hỏi | Điểm của bạn |\n|---|---|---|\n"
        "| hook_strength | q | 7 |\n| benefit_clarity | q | 5,5 |\n| proof_usage | q | |\n"
        "| cta_strength | q | 10 |\n| flow | q | |\n\n"
        "## B (`squoosh`)\n\n| hook_strength | q | 8 |\n"
    )
    assert cc.filled_scores(text) == {
        "orangehrm": {"hook_strength": 7.0, "benefit_clarity": 5.5, "cta_strength": 10.0},
        "squoosh": {"hook_strength": 8.0},
    }


def test_the_generated_document_shows_every_script_but_none_of_the_critics_scores() -> None:
    cc.gen()
    text = cc.DOC.read_text(encoding="utf-8")
    assert all(f"(`{n}`)" in text for n in cc.NAMES)
    assert text.count("| hook_strength |") == 3 and text.count("**HOOK**") == 3
    assert cc.filled_scores(text) == {n: {} for n in cc.NAMES}  # nothing filled in yet
