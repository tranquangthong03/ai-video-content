/** Ordered feature selection for select_features (pure helpers, tested in selection.test.ts). */

export const MAX_SELECTED = 4;

/** Adds the id at the end (lowest priority) or removes it; refuses to go over `max`. */
export function toggleSelection(order: string[], id: string, max = MAX_SELECTED): string[] {
  if (order.includes(id)) return order.filter((x) => x !== id);
  return order.length >= max ? order : [...order, id];
}

/** Moves an id one place up (-1) or down (+1) in the priority list. */
export function moveSelection(order: string[], id: string, delta: -1 | 1): string[] {
  const i = order.indexOf(id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= order.length) return order;
  const next = [...order];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

/** Features that can only be pointed at (no real interaction can be recorded). */
export const isPointingOnly = (demoKind: string | null | undefined): boolean => demoKind === "failed";
