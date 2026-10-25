import { describe, expect, it } from "vitest";
import { isPointingOnly, moveSelection, toggleSelection } from "./selection";
import { buildResponse, exploreFields, selectFields } from "./responses";

describe("selection order", () => {
  it("adds at the end, removes, and stops at the maximum", () => {
    expect(toggleSelection(["a"], "b")).toEqual(["a", "b"]);
    expect(toggleSelection(["a", "b"], "a")).toEqual(["b"]);
    expect(toggleSelection(["a", "b", "c", "d"], "e")).toEqual(["a", "b", "c", "d"]);
  });

  it("moves one place and ignores the edges", () => {
    expect(moveSelection(["a", "b", "c"], "c", -1)).toEqual(["a", "c", "b"]);
    expect(moveSelection(["a", "b", "c"], "a", -1)).toEqual(["a", "b", "c"]);
    expect(moveSelection(["a", "b", "c"], "c", 1)).toEqual(["a", "b", "c"]);
    expect(moveSelection(["a", "b"], "zz", 1)).toEqual(["a", "b"]);
  });

  it("warns only for features that can merely be pointed at", () => {
    expect(isPointingOnly("failed")).toBe(true);
    expect(isPointingOnly("interaction")).toBe(false);
  });
});

describe("select_features responses", () => {
  const pending = { interaction_id: "int_2", job_id: "j1" };

  it("sends the ordered ids as answers.selected_features", () => {
    const r = buildResponse(pending, "answer", selectFields(["b", "a"]));
    expect(r.answers).toEqual({ selected_features: ["b", "a"] });
  });

  it("explore_more carries a description and an optional url", () => {
    const r = buildResponse(pending, "explore_more", exploreFields(" Lộ trình học ", " https://x.com/paths "));
    expect(r.explore).toEqual({ urls: ["https://x.com/paths"], description: "Lộ trình học" });
    expect(exploreFields("chỉ mô tả", "").explore).toEqual({ urls: [], description: "chỉ mô tả" });
  });
});
