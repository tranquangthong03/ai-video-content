"""CAM-C: how scenes are stitched. Each rule is a pure function of cuts, frames and snapshots."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.producer.dead_frames import (
    FADE_MS,
    cut_dead,
    enforce_min_shot,
    flat_share,
    is_loading_crop,
    media_boxes,
    media_loading_runs,
    merge_runs,
    needs_fade,
)
from app.producer.trim import (
    Cut,
    apply_cuts,
    cuttable,
    fade_plan,
    new_item_windows,
    protected_windows,
    shift_time,
)


def test_overlapping_and_touching_runs_become_one() -> None:
    assert merge_runs([(500, 900), (0, 300), (250, 400), (900, 1000)]) == [(0, 400), (500, 1000)]
    assert merge_runs([]) == []


def test_a_blink_of_picture_between_two_blanks_is_cut_too() -> None:
    runs = [(1000, 2000), (2300, 3500)]  # 300 ms of picture between the blanks
    assert enforce_min_shot(runs, 0, 6000) == [(1000, 3500)]
    long = [(1000, 2000), (3000, 3500)]  # a whole second between them stays
    assert enforce_min_shot(long, 0, 6000) == long


def test_a_stub_at_the_start_or_the_end_of_the_clip_goes_as_well() -> None:
    assert enforce_min_shot([(400, 1500)], 0, 6000) == [(0, 1500)]  # 400 ms before the first cut
    assert enforce_min_shot([(5000, 5600)], 0, 6000) == [(5000, 6000)]  # 400 ms after the last
    assert enforce_min_shot([(0, 800), (5200, 6000)], 0, 6000) == [(0, 800), (5200, 6000)]


def test_every_shot_that_is_left_lasts_at_least_800_ms() -> None:
    runs = enforce_min_shot([(700, 1000), (1500, 2200), (2500, 4000), (4300, 4400)], 0, 8000)
    edges = [0, *[t for r in runs for t in r], 8000]
    kept = list(zip(edges[::2], edges[1::2], strict=False))
    assert all(b - a >= 800 or b == a for a, b in kept), kept


def test_a_junction_dissolves_only_when_the_picture_really_changes() -> None:
    assert needs_fade(12.0) and not needs_fade(0.4)  # blank -> page vs a freeze that continues


# --- a big picture that has not arrived ---------------------------------------------------------


def grey(level: int, size: tuple[int, int] = (320, 200)) -> Image.Image:
    return Image.new("L", size, level)


def test_a_box_that_is_mostly_one_flat_grey_or_black_is_loading_even_with_a_toolbar_on_it() -> None:
    dark = grey(40)
    for x in range(20, 120):  # a toolbar drawn over the canvas: part of the box is not flat
        for y in range(160, 190):
            dark.putpixel((x, y), 230 if (x + y) % 2 else 20)
    assert flat_share(dark) > 0.7 and is_loading_crop(dark)
    assert not is_loading_crop(grey(250))  # an empty white page is not a loading picture
    photo = Image.effect_noise((320, 200), 60)
    assert not is_loading_crop(photo)


def test_only_big_pictures_count_as_media_boxes() -> None:
    snap = {
        "items": [
            {"kind": "media", "bbox": {"x": 0, "y": 0, "w": 1440, "h": 900}},
            {"kind": "image", "bbox": {"x": 14, "y": 14, "w": 58, "h": 51}},  # a logo
            {"kind": "button", "bbox": {"x": 100, "y": 100, "w": 300, "h": 300}},
        ]
    }
    boxes = media_boxes(snap, (1440, 900))
    assert boxes == [(0, 0, 320, 200)]


# --- the cuts themselves ------------------------------------------------------------------------


def test_a_dissolve_takes_its_overlap_off_the_timeline() -> None:
    plain = [Cut(2000, 3000)]
    soft = [Cut(2000, 3000, FADE_MS)]
    assert shift_time(4000, plain) == 3000
    assert shift_time(4000, soft) == 3000 - FADE_MS
    assert shift_time(1000, soft) == 1000  # before the cut nothing moves


def test_the_pieces_a_set_of_cuts_leaves_know_which_ones_dissolve_in() -> None:
    cuts = [Cut(1000, 1500), Cut(3000, 3200, FADE_MS)]
    assert fade_plan(cuts, 5000) == [(0, 1000, 0), (1500, 3000, 0), (3200, 5000, FADE_MS)]
    assert fade_plan([], 4000) == [(0, 4000, 0)]


def colour_clip(path: Path) -> None:
    """1 s red, 1 s green, 1 s blue."""
    inputs = []
    for colour in ("red", "green", "blue"):
        inputs += ["-f", "lavfi", "-i", f"color=c={colour}:s=160x100:d=1:r=30"]
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip


def pixel(clip: Path, t: float) -> tuple[int, int, int]:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    )  # fmt: skip
    mid = (50 * 160 + 80) * 3
    return out.stdout[mid], out.stdout[mid + 1], out.stdout[mid + 2]


def duration(clip: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(out.stdout.strip())


@pytest.mark.slow
def test_a_cut_with_a_dissolve_blends_the_two_sides_and_a_plain_one_jumps(tmp_path: Path) -> None:
    raw = tmp_path / "raw.mp4"
    colour_clip(raw)
    soft, hard = tmp_path / "soft.mp4", tmp_path / "hard.mp4"
    apply_cuts(raw, soft, [Cut(1000, 2000, FADE_MS)])  # the green second goes, red melts into blue
    apply_cuts(raw, hard, [Cut(1000, 2000)])
    assert abs(duration(soft) - (2.0 - FADE_MS / 1000)) < 0.1
    assert abs(duration(hard) - 2.0) < 0.1
    r, g, b = pixel(soft, 0.92)  # inside the dissolve
    assert r > 40 and b > 40  # both colours present: neither red nor blue alone
    r, g, b = pixel(hard, 0.95)
    assert r > 150 and b < 80  # still plain red right up to the jump
    r, g, b = pixel(hard, 1.1)
    assert b > 150 and r < 80  # and plain blue after it


def noise_clip(path: Path, flat_from: float, flat_ms: float, total: float) -> None:
    """Noise (a busy picture), with one flat dark stretch where the picture has not arrived."""
    noise = "nullsrc=s=320x200:r=30,geq=random(1)*255:128:128"
    tail = total - flat_from - flat_ms / 1000
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"{noise},trim=duration={flat_from}",
         "-f", "lavfi", "-i", f"color=c=0x303030:s=320x200:d={flat_ms / 1000}:r=30",
         "-f", "lavfi", "-i", f"{noise},trim=duration={tail:.3f}",
         "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip


@pytest.mark.slow
def test_a_loading_slab_is_cut_and_the_jump_to_the_picture_dissolves(tmp_path: Path) -> None:
    clip = tmp_path / "s1.mp4"
    noise_clip(clip, 1.2, 400, 3.2)
    inventory = [
        {"t_ms": 0, "items": [{"kind": "media", "bbox": {"x": 0, "y": 0, "w": 1440, "h": 900}}]}
    ]
    done = cut_dead(clip, "s1", 0, 3200, inventory, (1440, 900))
    assert done is not None
    cuts = done[1]
    assert len(cuts) == 1 and 1100 <= cuts[0].from_ms <= 1300 and cuts[0].length >= 350
    assert cuts[0].fade_ms == FADE_MS  # one busy picture to another: it dissolves
    assert duration(clip) < 3.2 - 0.35


@pytest.mark.slow
def test_a_picture_that_is_flat_for_the_whole_clip_is_the_picture_not_a_wait(
    tmp_path: Path,
) -> None:
    clip = tmp_path / "s2.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x303030:s=320x200:d=3:r=30",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True, capture_output=True,
    )  # fmt: skip
    inventory = [
        {"t_ms": 0, "items": [{"kind": "media", "bbox": {"x": 0, "y": 0, "w": 1440, "h": 900}}]}
    ]
    runs = media_loading_runs(clip, inventory, clip_size=(1440, 900))
    assert runs == []  # it never gets any better: nothing to cut


# --- the moments a cut must stay away from ------------------------------------------------------


def test_a_cut_keeps_300_ms_away_from_the_moment_a_new_item_shows_up() -> None:
    inventory = [
        {"t_ms": 1000, "items": [{"id": "a", "is_new": False}]},
        {"t_ms": 5000, "items": [{"id": "b", "is_new": True}]},
    ]
    assert new_item_windows(inventory) == [(4700, 5300)]
    protect = protected_windows([], [], 0, inventory)
    pieces = cuttable([(3000, 7000)], protect, 0, 8000)  # a still stretch around the new item
    assert all(b <= 4700 or a >= 5300 for a, b in pieces)  # nothing of it is cut
    assert pieces  # but the rest of the stretch still may be
    assert new_item_windows(None) == []


# --- a plain colour is content, a picture that is still empty is a wait ------------------------------


def media_snapshot(loaded: bool | None) -> list[dict[str, object]]:
    item: dict[str, object] = {"kind": "media", "bbox": {"x": 0, "y": 0, "w": 1440, "h": 900}}
    if loaded is not None:
        item["loaded"] = loaded
    return [{"t_ms": 0, "items": [item]}]


@pytest.mark.slow
def test_a_flat_picture_the_page_says_is_loaded_is_content_not_a_wait(tmp_path: Path) -> None:
    clip = tmp_path / "flat.mp4"
    noise_clip(clip, 1.0, 1500, 4.0)  # busy, then a flat stretch of 1.5 s, then busy again
    runs = media_loading_runs(clip, media_snapshot(True), clip_size=(1440, 900))
    assert runs == []  # the canvas / img says it has its content: a plain colour is the picture
    waiting = media_loading_runs(clip, media_snapshot(False), clip_size=(1440, 900))
    assert len(waiting) == 1 and 1.4 <= (waiting[0][1] - waiting[0][0]) / 1000 <= 1.8
    unknown = media_loading_runs(clip, media_snapshot(None), clip_size=(1440, 900))
    assert unknown == waiting  # nothing said + it turns into content within 3 s: a wait


@pytest.mark.slow
def test_a_flat_stretch_of_over_three_seconds_the_page_does_not_vouch_for_is_content(
    tmp_path: Path,
) -> None:
    clip = tmp_path / "long.mp4"
    noise_clip(clip, 1.0, 3600, 6.0)
    assert media_loading_runs(clip, media_snapshot(None), clip_size=(1440, 900)) == []
    # but a picture the page itself says is still empty is a wait however long it takes
    assert len(media_loading_runs(clip, media_snapshot(False), clip_size=(1440, 900))) == 1
