import type { Caption } from "./props";

export type TimedWord = { text: string; start_ms: number; end_ms: number };

/**
 * Per-word timing of a caption group. Uses `words` when the caption has them (TTS timestamps);
 * otherwise splits the group's time over its words in proportion to their character count.
 */
export function wordsOf(caption: Caption): TimedWord[] {
  if (caption.words && caption.words.length > 0) return caption.words;
  const parts = caption.text.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return [];
  const total = parts.reduce((sum, w) => sum + w.length, 0);
  const span = caption.end_ms - caption.start_ms;
  let cursor = caption.start_ms;
  return parts.map((text, i) => {
    const start = cursor;
    cursor += (span * text.length) / total;
    return { text, start_ms: Math.round(start), end_ms: i === parts.length - 1 ? caption.end_ms : Math.round(cursor) };
  });
}

/** Index of the word being spoken at `ms` (the last one that has started), or -1 before the first. */
export function activeWordIndex(words: TimedWord[], ms: number): number {
  let idx = -1;
  for (let i = 0; i < words.length; i++) if (ms >= words[i].start_ms) idx = i;
  return idx;
}
