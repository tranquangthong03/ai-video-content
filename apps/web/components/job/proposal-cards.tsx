"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Star } from "lucide-react";
import type { InteractionRequest } from "@/lib/generated";
import { fileUrl } from "@/lib/api";
import { demoKindLabel, demoKindTone } from "@/lib/labels";
import { buildResponse, conceptFields, confirmFields, editFields, exploreFields, selectFields } from "@/lib/responses";
import { isPointingOnly, moveSelection, toggleSelection } from "@/lib/selection";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox, Input, Textarea } from "@/components/ui/field";
import { ErrorNote, Notices, Section, useSend, type JobCtx } from "./shared";

type Profile = NonNullable<InteractionRequest["profile"]>;
type Pending = InteractionRequest;

/** confirm_understanding: name, editable description, audience, feature grid, open questions. */
export function ConfirmCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const profile = pending.profile as Profile;
  const { send, busy, error } = useSend(ctx);
  const [oneLiner, setOneLiner] = useState(profile.one_liner);
  const [selected, setSelected] = useState(() => new Set(profile.features.map((f) => f.id)));
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const jobId = ctx.job.state.job_id;

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold">{profile.product_name}</h2>
        <p className="text-sm text-muted-foreground">Kiểm tra mình hiểu sản phẩm đúng chưa, bỏ chọn tính năng không muốn đưa vào video.</p>
      </div>
      <Section title="Mô tả (có thể sửa)">
        <Textarea value={oneLiner} onChange={(e) => setOneLiner(e.target.value)} aria-label="Mô tả sản phẩm" />
      </Section>
      {profile.target_users.length > 0 && (
        <Section title="Đối tượng">
          <div className="flex flex-wrap gap-2">
            {profile.target_users.map((u) => (
              <Badge key={u} tone="muted">
                {u}
              </Badge>
            ))}
          </div>
        </Section>
      )}
      <Section title={`Tính năng (${selected.size}/${profile.features.length} được chọn)`}>
        <div className="grid gap-3 sm:grid-cols-2">
          {profile.features.map((f) => {
            const thumb = (f as { thumbnail_url?: string | null }).thumbnail_url;
            return (
              <label key={f.id} className="cursor-pointer">
                <Card className={selected.has(f.id) ? "border-primary/60" : "opacity-60"}>
                  {thumb && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={fileUrl(jobId, thumb)} alt="" className="h-28 w-full rounded-t-lg object-cover object-top" />
                  )}
                  <CardHeader className="flex-row items-start gap-2 pb-1">
                    <Checkbox checked={selected.has(f.id)} onChange={() => toggle(f.id)} className="mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <CardTitle className="text-sm">{f.name}</CardTitle>
                    </div>
                    <Badge tone={demoKindTone(f.demo_kind)}>{demoKindLabel(f.demo_kind)}</Badge>
                  </CardHeader>
                  <CardContent className="text-xs text-muted-foreground">{(f as { description?: string }).description}</CardContent>
                </Card>
              </label>
            );
          })}
        </div>
      </Section>
      {pending.questions.length > 0 && (
        <Section title="Mình cần hỏi thêm">
          {pending.questions.map((q) => (
            <label key={q.id} className="block space-y-1 text-sm">
              <span>{q.text}</span>
              <Input value={answers[q.id] ?? ""} onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })} />
            </label>
          ))}
        </Section>
      )}
      <Section title="Ghi chú thêm (không bắt buộc)">
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Ví dụ: nhấn mạnh tốc độ, giọng vui vẻ..." />
      </Section>
      <ErrorNote text={error} />
      <Button
        disabled={busy || selected.size === 0}
        onClick={() =>
          send(() =>
            buildResponse(
              pending,
              "answer",
              confirmFields({
                allFeatureIds: profile.features.map((f) => f.id),
                selected,
                oneLiner,
                originalOneLiner: profile.one_liner,
                answers,
                notes,
              }),
            ),
          )
        }
      >
        {busy ? "Đang gửi..." : "Xác nhận"}
      </Button>
    </div>
  );
}

/** select_features: pick 1-4 features and put them in priority order; ask for a missing one. */
export function SelectFeaturesCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const profile = pending.profile as Profile;
  const sel = pending.selection!;
  const { send, busy, error } = useSend(ctx);
  const [order, setOrder] = useState<string[]>(() => sel.default);
  const [description, setDescription] = useState("");
  const [url, setUrl] = useState("");
  const jobId = ctx.job.state.job_id;
  const byId = useMemo(() => new Map(profile.features.map((f) => [f.id, f])), [profile.features]);
  const tooMany = order.length > sel.recommended_max;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold">Chọn tính năng để review</h2>
        <p className="text-sm text-muted-foreground">
          Chọn {sel.min}–{sel.max} tính năng (khuyến nghị 2–{sel.recommended_max}). Video chỉ nói về các tính năng này, theo thứ tự ưu tiên bên dưới.
        </p>
      </div>
      <Notices message={pending.message} />
      <Section title={`Tính năng (${order.length}/${sel.max} được chọn)`}>
        <div className="grid gap-3 sm:grid-cols-2">
          {profile.features.map((f) => {
            const thumb = (f as { thumbnail_url?: string | null }).thumbnail_url;
            const on = order.includes(f.id);
            const isNew = sel.new_ids.includes(f.id);
            const full = !on && order.length >= sel.max;
            return (
              <label key={f.id} className={full ? "cursor-not-allowed" : "cursor-pointer"}>
                <Card className={on ? "border-primary/60" : full ? "opacity-40" : "opacity-70"}>
                  {thumb && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={fileUrl(jobId, thumb)} alt="" className="h-28 w-full rounded-t-lg object-cover object-top" />
                  )}
                  <CardHeader className="flex-row items-start gap-2 pb-1">
                    <Checkbox checked={on} disabled={full} onChange={() => setOrder(toggleSelection(order, f.id, sel.max))} className="mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <CardTitle className="text-sm">
                        {on && <span className="mr-1 text-primary">{order.indexOf(f.id) + 1}.</span>}
                        {f.name}
                      </CardTitle>
                    </div>
                    {isNew && <Badge tone="success">Mới thêm</Badge>}
                    <Badge tone={demoKindTone(f.demo_kind)}>{demoKindLabel(f.demo_kind)}</Badge>
                  </CardHeader>
                  <CardContent className="space-y-1 text-xs text-muted-foreground">
                    <p>{(f as { description?: string }).description}</p>
                    {on && isPointingOnly(f.demo_kind) && (
                      <p className="text-amber-700">Chỉ quay được cảnh chỉ vị trí, không thao tác thật.</p>
                    )}
                  </CardContent>
                </Card>
              </label>
            );
          })}
        </div>
      </Section>
      {order.length > 0 && (
        <Section title="Thứ tự ưu tiên">
          <ol className="space-y-2">
            {order.map((id, i) => (
              <li key={id} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                <span className="w-5 font-semibold text-primary">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate">{byId.get(id)?.name ?? id}</span>
                <Button variant="outline" size="sm" aria-label="Lên" disabled={i === 0} onClick={() => setOrder(moveSelection(order, id, -1))}>
                  <ArrowUp className="h-4 w-4" />
                </Button>
                <Button variant="outline" size="sm" aria-label="Xuống" disabled={i === order.length - 1} onClick={() => setOrder(moveSelection(order, id, 1))}>
                  <ArrowDown className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ol>
          {tooMany && <p className="text-sm text-amber-700">Chọn nhiều hơn {sel.recommended_max} tính năng thì mỗi tính năng sẽ có ít thời gian hơn.</p>}
        </Section>
      )}
      <Section title="Tính năng chưa có trong danh sách?">
        <p className="text-sm text-muted-foreground">Mô tả tính năng (và dán URL trang chứa nó nếu có), mình sẽ xem thêm tối đa 3 trang rồi hiện lại danh sách.</p>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Ví dụ: Lộ trình học theo vai trò (Learning Paths)" aria-label="Mô tả tính năng cần thêm" disabled={busy} />
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="URL (không bắt buộc)" aria-label="URL trang chứa tính năng" disabled={busy} />
        <Button
          variant="outline"
          disabled={busy || (!description.trim() && !url.trim())}
          onClick={() => send(() => buildResponse(pending, "explore_more", exploreFields(description, url)))}
        >
          {busy ? "Đang khám phá thêm..." : "Khám phá thêm"}
        </Button>
      </Section>
      <ErrorNote text={error} />
      <Button disabled={busy || order.length < sel.min} onClick={() => send(() => buildResponse(pending, "answer", selectFields(order)))}>
        {busy ? "Đang gửi..." : `Tiếp tục với ${order.length} tính năng`}
      </Button>
    </div>
  );
}

const DURATIONS = [30, 45, 60] as const;

/** choose_concept: three concept cards, duration picker with a warning, regenerate. */
export function ConceptCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const concepts = pending.concepts ?? [];
  const { send, busy, error } = useSend(ctx);
  const proposed = concepts[0]?.duration_s ?? 30;
  const [duration, setDuration] = useState<number>(proposed);
  const [notes, setNotes] = useState("");

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold">Chọn hướng video</h2>
        <p className="text-sm text-muted-foreground">Mỗi hướng kể một câu chuyện khác nhau. Thời lượng đề xuất: {proposed}s.</p>
      </div>
      <Section title="Thời lượng">
        <div className="flex flex-wrap gap-2">
          {DURATIONS.map((d) => (
            <Button key={d} variant={duration === d ? "default" : "outline"} size="sm" onClick={() => setDuration(d)}>
              {d}s{d === proposed ? " (đề xuất)" : ""}
            </Button>
          ))}
        </div>
        {duration > proposed && (
          <p role="status" className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Sản phẩm chỉ đủ nội dung trình diễn cho khoảng {proposed}s. Video {duration}s sẽ có nhiều cảnh không quay thao tác,
            bạn có thể chọn lại thời lượng hoặc giữ nguyên.
          </p>
        )}
      </Section>
      <div className="grid gap-3 lg:grid-cols-3">
        {concepts.map((c) => (
          <Card key={c.id} className={c.recommended ? "border-primary/60" : ""}>
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <CardTitle>{c.title}</CardTitle>
                {c.recommended && (
                  <Badge className="shrink-0 gap-1">
                    <Star className="h-3 w-3 fill-current" /> Đề xuất
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{c.why}</p>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="rounded-md bg-muted px-3 py-2 text-sm italic">“{c.hook_example}”</p>
              <ol className="list-decimal space-y-1 pl-5 text-sm">
                {c.beats.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ol>
              <Button
                className="w-full"
                disabled={busy}
                onClick={() =>
                  send(() =>
                    buildResponse(pending, "answer", conceptFields({ conceptId: c.id, durationS: duration, proposedS: proposed, notes })),
                  )
                }
              >
                Chọn hướng này
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
      <Section title="Ghi chú thêm (không bắt buộc)">
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Ví dụ: thêm phần bộ lọc, giọng trẻ trung..." />
      </Section>
      <ErrorNote text={error} />
      <Button
        variant="outline"
        disabled={busy}
        onClick={() => send(() => buildResponse(pending, "regenerate", { answers: { notes } }))}
      >
        Đề xuất lại
      </Button>
    </div>
  );
}

/** outline_review: numbered beats with feature labels, change badges, notices, free-text edit. */
export function OutlineCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const outline = pending.outline!;
  const { send, busy, error } = useSend(ctx);
  const [text, setText] = useState("");
  const names = useMemo(() => new Map((pending.profile?.features ?? []).map((f) => [f.id, f.name])), [pending.profile]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="flex flex-wrap items-center gap-2 text-xl font-bold">
          {outline.title} <Badge tone="muted">v{outline.version}</Badge> <Badge tone="muted">{outline.duration_s}s</Badge>
        </h2>
        <p className="text-sm text-muted-foreground">Mỗi beat sẽ thành một cảnh trong video.</p>
      </div>
      <Notices message={pending.message} />
      {pending.changes && pending.changes.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Thay đổi của bản mới">
          {pending.changes.map((c, i) => (
            <Badge key={i} tone="success">
              {c}
            </Badge>
          ))}
        </div>
      )}
      <ol className="space-y-2">
        {outline.beats.map((b, i) => (
          <li key={b.id} className="flex gap-3 rounded-lg border border-border bg-card p-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-sm">{b.text}</p>
              {b.feature_id && <Badge tone="default">{names.get(b.feature_id) ?? b.feature_id}</Badge>}
            </div>
          </li>
        ))}
      </ol>
      <Section title="Bạn muốn sửa gì?">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ví dụ: đổi mở đầu thành câu hỏi, bỏ ý 3, thêm phần bộ lọc..."
        />
      </Section>
      <ErrorNote text={error} />
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || !text.trim()} variant="outline" onClick={() => send(() => buildResponse(pending, "edit", editFields(text)))}>
          Gửi yêu cầu sửa
        </Button>
        <Button disabled={busy} onClick={() => send(() => buildResponse(pending, "approve"))}>
          Duyệt dàn ý
        </Button>
        <Button disabled={busy} variant="ghost" onClick={() => send(() => buildResponse(pending, "regenerate"))}>
          Tạo lại
        </Button>
      </div>
    </div>
  );
}

/** clarify: the pipeline needs a choice before it can apply an edit. */
export function ClarifyCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const q = pending.questions[0];
  const { send, busy, error } = useSend(ctx);
  const [custom, setCustom] = useState("");
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">Cần làm rõ một chút</h2>
      <p>{q?.text ?? pending.message}</p>
      <div className="flex flex-wrap gap-2">
        {q?.options.map((o) => (
          <Button key={o.id} variant="outline" disabled={busy} onClick={() => send(() => buildResponse(pending, "answer", { answers: { clarify: o.id } }))}>
            {o.label}
          </Button>
        ))}
      </div>
      {q?.allow_custom && (
        <div className="flex gap-2">
          <Input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Hoặc nhập ý khác" />
          <Button disabled={busy || !custom.trim()} onClick={() => send(() => buildResponse(pending, "answer", { answers: { clarify: custom.trim() } }))}>
            Gửi
          </Button>
        </div>
      )}
      <ErrorNote text={error} />
    </div>
  );
}
