import { describe, expect, it } from "vitest";
import { MarketingBriefSchema } from "./generated";
import { buildResponse } from "./responses";
import { addPoint, editPoint, emptyForm, isEmpty, MAX_POINTS, pickIdea, pointProblems, removePoint, toBrief } from "./brief";

describe("the marketing brief form", () => {
  it("an untouched form is an empty brief and a valid one", () => {
    const brief = toBrief(emptyForm());
    expect(isEmpty(brief)).toBe(true);
    expect(MarketingBriefSchema.parse(brief)).toEqual(brief);
  });

  it("a chip fills the field, the same chip again clears it", () => {
    expect(pickIdea("", "Dùng thử miễn phí")).toBe("Dùng thử miễn phí");
    expect(pickIdea("Dùng thử miễn phí", "Dùng thử miễn phí")).toBe("");
    expect(pickIdea("cái khác", "Dùng thử miễn phí")).toBe("Dùng thử miễn phí");
  });

  it("figures are added and removed row by row, up to the limit", () => {
    let f = emptyForm();
    for (let i = 0; i < MAX_POINTS + 2; i++) f = addPoint(f);
    expect(f.points).toHaveLength(MAX_POINTS);
    f = editPoint(f, 1, { value: "40", unit: "%", claim: "Giảm 40% thời gian" });
    expect(removePoint(f, 0).points[0].value).toBe("40");
  });

  it("only rows with a number and a sentence are sent, half-filled rows are reported", () => {
    let f = addPoint(addPoint(addPoint(emptyForm())));
    f = editPoint(f, 0, { value: "40", unit: "%", claim: "Giảm 40% thời gian nhập hồ sơ" });
    f = editPoint(f, 1, { value: "3", claim: "" });
    f = editPoint(f, 2, { value: "x", claim: "không có số" });
    expect(pointProblems(f)).toEqual(["Số liệu 2: cần câu đầy đủ chứa con số", "Số liệu 3: cần một con số"]);
    const brief = toBrief(f);
    expect(brief.proof_points).toEqual([{ value: "40", unit: "%", claim: "Giảm 40% thời gian nhập hồ sơ", source_note: null }]);
  });

  it("lists are split on ; and lines, trimmed and de-duplicated", () => {
    const brief = toBrief({ ...emptyForm(), secondary: "Không giấy tờ; Nhanh\nNhanh ", avoid: "rẻ nhất;; ", audience: "  HR   nhỏ " });
    expect(brief.secondary_benefits).toEqual(["Không giấy tờ", "Nhanh"]);
    expect(brief.avoid).toEqual(["rẻ nhất"]);
    expect(brief.audience).toBe("HR nhỏ");
  });

  it("the answer and the skip are valid UserResponses", () => {
    const pending = { interaction_id: "int_1", job_id: "j1" };
    const brief = toBrief({ ...emptyForm(), mainBenefit: "Tạo hồ sơ trong vài phút" });
    expect(buildResponse(pending, "answer", { brief }).brief?.main_benefit).toBe("Tạo hồ sơ trong vài phút");
    expect(buildResponse(pending, "skip").action).toBe("skip");
  });
});
