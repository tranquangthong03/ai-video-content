"use client";

import { useState } from "react";
import type { InteractionRequest } from "@/lib/generated";
import { addPoint, editPoint, emptyForm, MAX_POINTS, pickIdea, pointProblems, removePoint, toBrief, type BriefForm } from "@/lib/brief";
import { buildResponse } from "@/lib/responses";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/field";
import { ErrorNote, Notices, Section, useSend, type JobCtx } from "./shared";

type Pending = InteractionRequest;

/** Suggestions as chips: a click fills the field, a second click clears it. */
function Chips({ ideas, value, onPick, disabled }: { ideas: string[]; value: string; onPick: (idea: string) => void; disabled: boolean }) {
  if (ideas.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Gợi ý">
      {ideas.map((idea) => {
        const on = value.trim() === idea.trim();
        return (
          <button
            key={idea}
            type="button"
            disabled={disabled}
            aria-pressed={on}
            onClick={() => onPick(idea)}
            className={
              "rounded-full border px-3 py-1 text-xs transition-colors " +
              (on ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:border-primary/60 hover:text-foreground")
            }
          >
            {idea}
          </button>
        );
      })}
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      {children}
    </label>
  );
}

/** marketing_brief: what the website does not say. Every field is optional; «Bỏ qua» keeps the old behaviour. */
export function MarketingBriefCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const form0 = pending.brief_form!;
  const ideas = form0.suggestions;
  const { send, busy, error } = useSend(ctx);
  const [form, setForm] = useState<BriefForm>(emptyForm);
  const set = (patch: Partial<BriefForm>) => setForm((f) => ({ ...f, ...patch }));
  const problems = pointProblems(form);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold">Bổ sung brief cho video</h2>
        <p className="text-sm text-muted-foreground">
          Website không nói hết đối tượng, lợi ích và ưu đãi. Bấm gợi ý hoặc tự nhập; mọi ô đều tùy chọn.
        </p>
      </div>
      <Notices message={pending.message} />
      <p role="note" className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
        {form0.note}
      </p>

      <Section title="Ai sẽ xem và dùng sản phẩm?">
        <Chips ideas={ideas.audience} value={form.audience} onPick={(i) => set({ audience: pickIdea(form.audience, i) })} disabled={busy} />
        <Input value={form.audience} onChange={(e) => set({ audience: e.target.value })} placeholder="Ví dụ: Phòng nhân sự doanh nghiệp nhỏ" aria-label="Đối tượng" disabled={busy} />
      </Section>

      <Section title="Họ được gì khi dùng? (lợi ích chính)">
        <Chips ideas={ideas.main_benefit} value={form.mainBenefit} onPick={(i) => set({ mainBenefit: pickIdea(form.mainBenefit, i) })} disabled={busy} />
        <Input value={form.mainBenefit} onChange={(e) => set({ mainBenefit: e.target.value })} placeholder="Ví dụ: Tạo hồ sơ nhân viên mới trong vài phút" aria-label="Lợi ích chính" disabled={busy} />
        <Field label="Lợi ích phụ" hint="Mỗi lợi ích một dòng hoặc cách nhau bằng dấu ;">
          <Textarea value={form.secondary} onChange={(e) => set({ secondary: e.target.value })} aria-label="Lợi ích phụ" disabled={busy} />
        </Field>
      </Section>

      <Section title="Số liệu thật">
        <p className="text-xs text-muted-foreground">Chỉ nhập số liệu có thật: số này sẽ được nói và hiện trong video.</p>
        {form.points.map((p, i) => (
          <Card key={i}>
            <CardContent className="grid gap-2 pt-4 sm:grid-cols-[100px_100px_1fr_auto]">
              <Input value={p.value} onChange={(e) => set(editPoint(form, i, { value: e.target.value }))} placeholder="Con số" aria-label={`Con số ${i + 1}`} disabled={busy} />
              <Input value={p.unit} onChange={(e) => set(editPoint(form, i, { unit: e.target.value }))} placeholder="Đơn vị" aria-label={`Đơn vị ${i + 1}`} disabled={busy} />
              <Input value={p.claim} onChange={(e) => set(editPoint(form, i, { claim: e.target.value }))} placeholder="Câu đầy đủ, ví dụ: Giảm 40% thời gian nhập hồ sơ" aria-label={`Câu chứa số liệu ${i + 1}`} disabled={busy} />
              <Button variant="outline" size="sm" disabled={busy} onClick={() => set(removePoint(form, i))} aria-label={`Xóa số liệu ${i + 1}`}>
                Xóa
              </Button>
            </CardContent>
          </Card>
        ))}
        {problems.length > 0 && (
          <ul role="status" className="space-y-1 text-sm text-amber-700">
            {problems.map((m) => (
              <li key={m}>{m} (dòng này sẽ không được gửi)</li>
            ))}
          </ul>
        )}
        <Button variant="outline" size="sm" disabled={busy || form.points.length >= MAX_POINTS} onClick={() => set(addPoint(form))}>
          + Thêm số liệu
        </Button>
      </Section>

      <Section title="Ưu đãi và lời kêu gọi">
        <Chips ideas={ideas.offer} value={form.offer} onPick={(i) => set({ offer: pickIdea(form.offer, i) })} disabled={busy} />
        <Input value={form.offer} onChange={(e) => set({ offer: e.target.value })} placeholder="Ví dụ: Mã nguồn mở, dùng miễn phí" aria-label="Ưu đãi" disabled={busy} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Lời kêu gọi">
            <Input value={form.ctaText} onChange={(e) => set({ ctaText: e.target.value })} placeholder="Dùng thử ngay" disabled={busy} />
          </Field>
          <Field label="Địa chỉ hiện ở cảnh cuối">
            <Input value={form.ctaUrl} onChange={(e) => set({ ctaUrl: e.target.value })} placeholder="example.com/dung-thu" disabled={busy} />
          </Field>
        </div>
      </Section>

      <Section title="Giọng điệu và điều cần tránh">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Giọng điệu">
            <Input value={form.tone} onChange={(e) => set({ tone: e.target.value })} placeholder="Gần gũi, ngắn gọn" disabled={busy} />
          </Field>
          <Field label="Điều cần tránh nói" hint="Cách nhau bằng dấu ;">
            <Input value={form.avoid} onChange={(e) => set({ avoid: e.target.value })} placeholder="rẻ nhất; số 1" disabled={busy} />
          </Field>
        </div>
      </Section>

      <ErrorNote text={error} />
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => send(() => buildResponse(pending, "answer", { brief: toBrief(form) }))}>
          {busy ? "Đang gửi..." : "Dùng brief này"}
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => send(() => buildResponse(pending, "skip"))}>
          Bỏ qua
        </Button>
      </div>
    </div>
  );
}
