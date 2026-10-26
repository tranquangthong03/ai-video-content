import subprocess
from pathlib import Path

from app.recorder import sync


def make_clip(path: Path, parts: list[tuple[str, float]]) -> Path:
    """A 160x90 clip made of solid colours: [(colour, seconds), ...]."""
    inputs: list[str] = []
    for colour, seconds in parts:
        inputs += ["-f", "lavfi", "-i", f"color=c={colour}:s=160x90:r=30:d={seconds}"]
    n = len(parts)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
         "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p",
         "-c:v", "libx264", "-crf", "20", str(path)],
        check=True,
    )  # fmt: skip
    return path


def test_the_pulse_colour_is_told_from_page_colours() -> None:
    magenta, white, red, blue = (255, 0, 255), (255, 255, 255), (255, 0, 0), (0, 0, 255)
    assert sync.is_pulse_pixel(*magenta)
    assert not any(sync.is_pulse_pixel(*c) for c in (white, red, blue, (0, 0, 0), (200, 100, 200)))
    frame = bytes(magenta) * 10 + bytes(white) * 30
    assert sync.pulse_share(frame) == 0.25


def test_the_first_pulse_frame_gives_the_offset_between_the_clocks(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "a.mp4", [("white", 0.5), ("magenta", 0.3), ("white", 1.0)])
    seen = sync.find_pulse(clip)
    assert seen is not None and abs(seen - 500) <= 70
    same = sync.measure_offset(clip, 500)
    assert same is not None and abs(same) <= 70  # the clocks agree
    ahead = sync.measure_offset(clip, 100)  # the log says the pulse was at 100 ms, the video at 500
    assert ahead is not None and abs(ahead - 400) <= 70
    assert sync.measure_offset(clip, 5000) is None  # an offset this large is not believed


def test_no_pulse_no_offset(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "b.mp4", [("white", 1.0), ("blue", 1.0)])
    assert sync.find_pulse(clip) is None and sync.measure_offset(clip, 0) is None


def test_a_finished_video_is_scanned_for_a_leaked_pulse(tmp_path: Path) -> None:
    leaked = make_clip(tmp_path / "c.mp4", [("white", 1.0), ("magenta", 0.3), ("white", 1.0)])
    assert sync.video_has_pulse(leaked)
    assert not sync.video_has_pulse(leaked, from_ms=1600)  # looking only after the pulse
    clean = make_clip(tmp_path / "d.mp4", [("white", 1.0), ("red", 0.5), ("blue", 1.0)])
    assert not sync.video_has_pulse(clean)
