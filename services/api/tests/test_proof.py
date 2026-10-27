import json
from pathlib import Path

from app.schemas.generated.product_profile import ProductProfile
from app.script.proof import (
    NumberFact,
    ProofBank,
    build_proof_bank,
    norm_number,
    numbers_in,
    strip_numbers,
    unsupported_numbers,
)

PROFILE = ProductProfile.model_validate(
    {
        "site_type": "tool", "product_name": "Squoosh", "one_liner": "Nén ảnh ngay trong trình duyệt.",
        "target_users": ["Nhà phát triển web"], "value_props": ["Giảm dung lượng ảnh tới 80%"],
        "features": [{
            "id": "f1", "name": "Nén ảnh", "description": "Nén ảnh", "importance": 0.9,
            "evidence": [
                {"source": "landing_claim", "url": "https://s.app/", "ref": None,
                 "quote": "Smaller images mean faster load times. Squoosh can reduce file size."},
                {"source": "app_action", "url": "https://s.app/", "ref": "e1",
                 "quote": "Tải ảnh lên (kéo thả/dán/chọn tệp)"},
            ],
        }],
    }
)  # fmt: skip
PAGES = [{
    "url": "https://s.app/", "title": "Squoosh", "meta_description": "Free image optimizer, no install.",
    "headings": [{"level": 2, "text": "Small"}],
    "key_texts": ["Worried about privacy? Images never leave your device.", "Try: Large photo 2.8MB", "Hi"],
}]  # fmt: skip
INVENTORY = [{"t_ms": 0, "items": [{"text": "1.6MB"}, {"text": "Saved 45%"}, {"text": ""}]}]


def test_numbers_are_read_with_their_unit_and_normalized() -> None:
    assert [(v, u) for v, u, *_ in numbers_in("Giảm 80% còn 2,8 MB sau 3 bước, 1.000 người")] == [
        ("80", "%"), ("2.8", "MB"), ("3", "bước"), ("1000", "người"),
    ]  # fmt: skip
    assert norm_number("2.80") == "2.8" and norm_number("1,000") == "1000"
    assert numbers_in("Squoosh 2 là hay")[0][:2] == ("2", "")  # no unit: still a number


def test_the_bank_collects_numbers_quotes_offers_and_pains_from_real_texts() -> None:
    bank = build_proof_bank(PROFILE, PAGES, INVENTORY)
    assert {(n.value, n.unit) for n in bank.numbers} >= {("80", "%"), ("2.8", "MB"), ("45", "%")}
    assert all(n.source and n.context for n in bank.numbers)
    assert "Smaller images mean faster load times. Squoosh can reduce file size." in bank.quotes
    assert all(20 <= len(q) <= 120 for q in bank.quotes)
    assert "Tải ảnh lên (kéo thả/dán/chọn tệp)" not in bank.quotes  # our own summary, not verbatim
    assert {o.id for o in bank.offers} >= {"free", "no_install", "private"}
    assert bank.audience_pains and "Worried" in bank.audience_pains[0]
    assert not bank.is_empty and ProofBank().is_empty


def test_a_number_without_a_source_is_found_and_a_sourced_one_is_not() -> None:
    bank = build_proof_bank(PROFILE, PAGES, INVENTORY)
    text = "Giảm 80% dung lượng, từ 1.6 MB; hơn 10.000 người dùng và 3 bước"
    assert unsupported_numbers(text, bank, INVENTORY) == ["10.000 người", "3 bước"]
    assert unsupported_numbers(text, bank, INVENTORY, extra=["3"]) == ["10.000 người"]
    assert unsupported_numbers("Không có số nào", bank) == []


def test_removing_numbers_leaves_a_tidy_sentence() -> None:
    bad = ["10.000 người"]
    assert strip_numbers("Hơn 10.000 người đã dùng, thử ngay.", bad) == "Hơn đã dùng, thử ngay."
    assert strip_numbers("Nén 80% , nhanh", ["80%"]) == "Nén, nhanh"


def test_the_saved_r4_jobs_build_a_non_empty_bank_without_crashing() -> None:
    root = Path(__file__).parents[1] / "out" / "r4-squoosh"
    if not (root / "confirmed_profile.json").is_file():
        return  # out/ is gitignored: only on the machine that ran R4
    profile = ProductProfile.model_validate_json(
        (root / "confirmed_profile.json").read_text("utf-8")
    )
    pages = [
        json.loads(p.read_text("utf-8"))
        for p in sorted((root / "explore" / "pages").glob("*.json"))
    ]
    bank = build_proof_bank(profile, pages)
    assert bank.offers and bank.quotes


def test_numbers_are_told_apart_by_what_they_mean_to_the_viewer() -> None:
    from app.script.proof import classify_number

    assert classify_number("80", "%", "giảm 80% dung lượng", "profile") == "benefit"
    assert classify_number("2.8", "MB", "Large photo 2.8MB", "frame") == "benefit"
    assert classify_number("5", "phút", "xong trong 5 phút", "page:x") == "benefit"
    assert classify_number("0736", "", "mã nhân viên 0736", "frame") == "identifier"
    assert classify_number("0443", "", "Employee Id 0443", "frame") == "identifier"
    assert (
        classify_number("123456", "", "gọi 123456", "profile") == "identifier"
    )  # a long bare number
    assert (
        classify_number("3", "", "3 items left!", "frame") == "identifier"
    )  # on the screen, typed or UI
    assert classify_number("4", "bước", "4 bước", "profile") == "other"


def test_only_benefit_numbers_pass_when_the_text_is_a_hook_a_headline_or_a_stat() -> None:
    bank = ProofBank(
        numbers=[
            NumberFact("80", "%", "giảm 80%", "profile", "benefit"),
            NumberFact("0736", "", "mã 0736", "frame", "identifier"),
        ]
    )
    text = "Giảm 80% và mã 0736"
    assert unsupported_numbers(text, bank) == []  # in the bank: fine in a chapter's voice-over
    assert unsupported_numbers(text, bank, benefit_only=True) == ["0736"]  # a hook promises results
    assert unsupported_numbers("Giảm 80%", bank, benefit_only=True) == []
    assert (
        unsupported_numbers("Còn 3 việc", bank, extra=["3"], benefit_only=True) == []
    )  # the flow's own


def test_a_long_cut_never_ends_on_a_connector() -> None:
    from app.core.trim_text import drop_dangling, trim_words

    assert (
        drop_dangling("Bạn mất bao lâu để dựng sơ đồ rồi gửi cho")
        == "Bạn mất bao lâu để dựng sơ đồ rồi gửi"
    )
    assert drop_dangling("Gửi cho") == "Gửi cho"  # keeps at least three words... or what is there
    cut = trim_words("Bạn mất bao lâu để dựng một sơ đồ rồi gửi cho đồng nghiệp xem thử ngay", 10)
    assert cut.rstrip(".").split()[-1] not in {"cho", "rồi", "để", "một", "và"}
