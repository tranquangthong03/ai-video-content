import { describe, expect, it } from "vitest";
import {
  STAGGER_MS,
  anchorFrame,
  highlightIndex,
  kineticWords,
  pickStatCorner,
  popOf,
  quietWeight,
  punchFactor,
  splitHalves,
  statStartFrame,
} from "./finish";

const FPS = 30;

describe("kinetic text", () => {
  it("shows the words one after another, 60-90 ms apart, from the anchor", () => {
    const words = kineticWords("Xong trong 1 phút", 20, FPS);
    expect(words.map((w) => w.text)).toEqual(["Xong", "trong", "1", "phút"]);
    expect(STAGGER_MS).toBeGreaterThanOrEqual(60);
    expect(STAGGER_MS).toBeLessThanOrEqual(90);
    const gaps = words.slice(1).map((w, i) => ((w.startFrame - words[i].startFrame) / FPS) * 1000);
    for (const g of gaps) expect(Math.abs(g - STAGGER_MS)).toBeLessThanOrEqual(1000 / FPS); // within one frame
    expect(words[0].startFrame).toBe(20);
  });

  it("colours the number, else the longest word, and nothing in a short text", () => {
    expect(highlightIndex(["Giảm", "80%", "dung", "lượng"])).toBe(1);
    expect(highlightIndex(["Nhanh", "hơn", "nhiều"])).toBe(0);
    expect(highlightIndex(["Đi", "ngay"])).toBe(-1);
    expect(kineticWords("Giảm 80% dung lượng", 0, FPS).filter((w) => w.highlight)).toHaveLength(1);
  });

  it("starts on the beat of the voice-over word that matches its first word", () => {
    const captions = [
      {
        text: "Xin nghỉ phép nhanh",
        start_ms: 0,
        end_ms: 2000,
        words: [
          { text: "Xin", start_ms: 0, end_ms: 400 },
          { text: "nghỉ", start_ms: 400, end_ms: 900 },
          { text: "phép", start_ms: 900, end_ms: 1400 },
          { text: "nhanh", start_ms: 1400, end_ms: 2000 },
        ],
      },
    ];
    expect(anchorFrame("Phép nhanh!", captions, FPS, 6)).toBe(Math.round(0.9 * FPS));
    expect(anchorFrame("Khác hẳn", captions, FPS, 6)).toBe(6); // not said: the fallback
    expect(anchorFrame("", captions, FPS, 6)).toBe(6);
  });

  it("pops from 0.85 to full size and is invisible before its frame", () => {
    expect(popOf(5, 10)).toEqual({ scale: 0.85, opacity: 0 });
    expect(popOf(10, 10).scale).toBeCloseTo(0.85);
    expect(popOf(40, 10)).toEqual({ scale: 1, opacity: 1 });
    expect(popOf(14, 10).scale).toBeGreaterThan(0.85);
  });
});

describe("punch-ins", () => {
  const punches = [{ t_ms: 1000, scale: 0.06 }];
  it("does nothing before the punch, reaches its size after nine frames and eases back", () => {
    expect(punchFactor(20, punches, FPS)).toBe(1);
    expect(punchFactor(30 + 9, punches, FPS)).toBeCloseTo(1.06, 3);
    expect(punchFactor(30 + 9 + 12, punches, FPS)).toBeLessThan(1.06);
    expect(punchFactor(30 + 9 + 40, punches, FPS)).toBe(1);
  });

  it("grows by no more than 2.5 % from one frame to the next", () => {
    let prev = 1;
    for (let f = 0; f < 90; f++) {
      const x = punchFactor(f, punches, FPS);
      expect(Math.abs(x / prev - 1)).toBeLessThanOrEqual(0.025);
      prev = x;
    }
  });

  it("keeps out of the way of a camera move: full strength only when the camera is quiet", () => {
    const moves = [{ start: 2000, duration: 600 }];
    expect(quietWeight(500, moves)).toBe(1);
    expect(quietWeight(2300, moves)).toBe(0); // inside the move
    expect(quietWeight(2000 - 125, moves)).toBeCloseTo(0.5, 2); // ramping out before it
    expect(quietWeight(2600 + 250, moves)).toBe(1); // and back after it
    expect(quietWeight(100, [])).toBe(1);
  });
  it("stays between 1 and 1+scale", () => {
    for (let f = 0; f < 120; f++) {
      const x = punchFactor(
        f,
        [
          { t_ms: 500, scale: 0.06 },
          { t_ms: 2000, scale: 0.04 },
        ],
        FPS,
      );
      expect(x).toBeGreaterThanOrEqual(1);
      expect(x).toBeLessThanOrEqual(1.06 + 1e-9);
    }
  });
});

describe("stat callout", () => {
  it("pops inside the first 30 % of the scene", () => {
    expect(statStartFrame(300)).toBeLessThanOrEqual(90);
    expect(statStartFrame(300)).toBeGreaterThan(0);
  });

  it("takes the top-right corner, and moves away from the focus when they would meet", () => {
    const frame = { w: 1000, h: 1250 };
    const box = { w: 300, h: 160 };
    expect(pickStatCorner(null, frame, box)).toBe("top-right");
    expect(pickStatCorner({ x: 100, y: 500, w: 200, h: 100 }, frame, box)).toBe("top-right");
    expect(pickStatCorner({ x: 650, y: 20, w: 300, h: 200 }, frame, box)).toBe("top-left");
    const cover = { x: 0, y: 0, w: 1000, h: 400 };
    expect(pickStatCorner(cover, frame, box, 28, 340)).toBe("bottom-right");
  });
});

describe("before / after", () => {
  it("splits the frame in two halves side by side", () => {
    const { left, right } = splitHalves({ w: 1000, h: 1250 });
    expect(left.x).toBe(0);
    expect(right.x).toBeGreaterThan(left.w);
    expect(left.w + right.w + 6).toBe(1000);
    expect(left.h).toBe(1250);
  });
});
