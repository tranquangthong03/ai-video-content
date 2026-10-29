"use client";

import { useState } from "react";
import type { InteractionRequest } from "@/lib/generated";
import { fileUrl } from "@/lib/api";
import {
  EDIT_EXAMPLES,
  FLOW_EXAMPLES,
  flowStatusLabel,
  canApprove,
  flowAnswers,
  flowStatusTone,
  groupByChapter,
  qualityLine,
  stepLine,
  submitOffer,
  toggleFlow,
} from "@/lib/flows";
import { buildResponse, editFields } from "@/lib/responses";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox, Textarea } from "@/components/ui/field";
import { ErrorNote, Notices, Section, useSend, type JobCtx } from "./shared";

type Pending = InteractionRequest;

/** select_flow: the proposed flows, a box to describe your own, and the submit switch (off). */
export function SelectFlowCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const flows = pending.flows ?? [];
  const sel = pending.flow_select!;
  const { send, busy, error } = useSend(ctx);
  const [order, setOrder] = useState<string[]>(() => sel.default);
  const [description, setDescription] = useState("");
  const [allowSubmit, setAllowSubmit] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const infeasible = sel.infeasible ?? {};
  const offer = submitOffer(flows, order, sel.submit_blocked_reason);
  const main = flows.find((f) => f.id === order[0]);

  const answer = (withDescription: boolean) =>
    send(() =>
      buildResponse(pending, "answer", {
        answers: flowAnswers({
          selected: order,
          description: withDescription ? description : "",
          allowSubmit,
          confirmed,
          blocked: sel.submit_blocked_reason,
        }),
      }),
    );

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold">Chọn luồng chính để quay</h2>
        <p className="text-sm text-muted-foreground">
          Video kể một việc trọn vẹn người dùng làm với sản phẩm, không phải vài nút rời rạc. Chọn 1 luồng chính (thêm 1 luồng phụ ngắn nếu video từ
          45s).
        </p>
      </div>
      <Notices message={pending.message} />
      <Section title="Tự mô tả luồng muốn quay">
        <p className="text-xs text-muted-foreground">
          Cách nhanh nhất để có video hay: nói bạn muốn khách thấy việc gì được làm xong. Hệ thống sẽ thử đúng việc đó.
        </p>
        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={FLOW_EXAMPLES[0]}
          aria-label="Mô tả luồng muốn quay"
          disabled={busy}
        />
        <div className="flex flex-wrap gap-2" role="group" aria-label="Ví dụ">
          {FLOW_EXAMPLES.map((e) => (
            <Button key={e} variant="outline" size="sm" disabled={busy} onClick={() => setDescription(e)}>
              {e}
            </Button>
          ))}
        </div>
        <Button variant="outline" disabled={busy || !description.trim()} onClick={() => answer(true)}>
          {busy ? "Đang xử lý..." : "Thêm luồng này"}
        </Button>
      </Section>
      {sel.empty_warning && (
        <p role="status" className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {sel.empty_warning}
        </p>
      )}
      {sel.env_warning && (
        <p role="status" aria-label="Cảnh báo môi trường" className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {sel.env_warning}
        </p>
      )}
      <Section title={`Luồng đề xuất (${order.length}/${sel.max} được chọn)`}>
        <div className="grid gap-3 lg:grid-cols-2">
          {flows.map((f) => {
            const on = order.includes(f.id);
            const cannot = infeasible[f.id];
            const full = !on && order.length >= sel.max;
            return (
              <label key={f.id} className={full || cannot ? "cursor-not-allowed" : "cursor-pointer"}>
                <Card className={cannot ? "opacity-60" : on ? "border-primary/60" : full ? "opacity-40" : "opacity-80"}>
                  <CardHeader className="flex-row items-start gap-2 pb-1">
                    <Checkbox
                      checked={on}
                      disabled={full || Boolean(cannot)}
                      onChange={() => setOrder(toggleFlow(order, f.id, sel.max, infeasible))}
                      className="mt-0.5"
                    />
                    <div className="min-w-0 flex-1">
                      <CardTitle className="text-sm">
                        {on && <span className="mr-1 text-primary">{order.indexOf(f.id) === 0 ? "Chính ·" : "Phụ ·"}</span>}
                        {f.title}
                      </CardTitle>
                      <p className="text-xs text-muted-foreground">{f.persona}</p>
                    </div>
                    {f.needs_submit && <Badge tone="warning">Cần gửi dữ liệu</Badge>}
                    {f.source === "user" && <Badge tone="success">Bạn mô tả</Badge>}
                  </CardHeader>
                  <CardContent className="space-y-2 text-xs text-muted-foreground">
                    {(() => {
                      const q = qualityLine(sel.quality?.[f.id]);
                      return q ? (
                        <p className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-foreground">{q.text}</span>
                          {q.warn && <Badge tone="warning">{q.warn}</Badge>}
                        </p>
                      ) : null;
                    })()}
                    {cannot && (
                      <p role="status" className="rounded-md bg-red-50 px-2 py-1.5 text-red-800">
                        Không khả thi trên tài khoản này: {cannot}
                      </p>
                    )}
                    <p>{f.goal}</p>
                    <ul className="list-disc space-y-0.5 pl-4">
                      {f.expected_steps.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                    <p>
                      <span className="font-medium text-foreground">Thấy khi xong:</span> {f.success_signal}
                    </p>
                    {f.confidence < 0.5 && f.notes && <p className="text-amber-700">{f.notes}</p>}
                  </CardContent>
                </Card>
              </label>
            );
          })}
        </div>
      </Section>
      {offer.offered && (
        <Section title="Gửi dữ liệu trong luồng">
          {offer.blocked ? (
            <p role="status" className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              Không thể bật: {offer.blocked} Hệ thống dừng ngay trước nút Gửi/Lưu và tô sáng nút đó.
            </p>
          ) : (
            <div className="space-y-2">
              <label className="flex cursor-pointer items-start gap-2 text-sm">
                <Checkbox
                  checked={allowSubmit}
                  onChange={() => {
                    setAllowSubmit(!allowSubmit);
                    setConfirmed(false);
                  }}
                  className="mt-0.5"
                />
                <span>Cho phép hệ thống bấm Gửi/Lưu trong luồng này (mặc định: tắt, dừng trước nút Gửi)</span>
              </label>
              {allowSubmit && (
                <div role="alert" className="space-y-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <p>Hệ thống sẽ tạo dữ liệu thật trên website này (tối đa 2 lần bấm). Chỉ bật khi đó là tài khoản thử nghiệm của bạn.</p>
                  <label className="flex cursor-pointer items-start gap-2">
                    <Checkbox checked={confirmed} onChange={() => setConfirmed(!confirmed)} className="mt-0.5" />
                    <span>Đây là tài khoản thử nghiệm của tôi, được phép tạo dữ liệu</span>
                  </label>
                </div>
              )}
            </div>
          )}
        </Section>
      )}
      <ErrorNote text={error} />
      <Button disabled={busy || order.length < 1 || (allowSubmit && !confirmed)} onClick={() => answer(false)}>
        {busy ? "Đang gửi..." : main ? `Quay luồng «${main.title}»` : "Tiếp tục"}
      </Button>
    </div>
  );
}

/** flow_storyboard_review: what the agent did, step by step, under its chapters. */
export function StoryboardCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const run = pending.flow_review!;
  const flow = pending.flows?.[0];
  const { send, busy, error } = useSend(ctx);
  const [instruction, setInstruction] = useState("");
  const jobId = ctx.job.state.job_id;
  const groups = groupByChapter(run);
  const report = run.report;

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-bold">Storyboard luồng{flow ? `: ${flow.title}` : ""}</h2>
          <Badge tone={flowStatusTone(run.status)}>{flowStatusLabel(run)}</Badge>
          {pending.script_version != null && <Badge tone="muted">bản {pending.script_version}</Badge>}
        </div>
        <p className="text-sm text-muted-foreground">
          Đây là những gì hệ thống đã làm trên website, từng bước. Duyệt nếu đúng, hoặc sửa bằng một câu: các bước đầu vẫn đúng sẽ được giữ lại.
        </p>
        {report && (
          <p className="text-xs text-muted-foreground">
            Agent: {report.llm_calls} lần gọi, {report.seconds}s{report.used_images ? ", có nhìn ảnh màn hình" : ", chỉ đọc chữ"}.
          </p>
        )}
      </div>
      <Notices message={pending.message} />
      {run.warnings.length > 0 && (
        <ul className="space-y-1">
          {run.warnings.map((w, i) => (
            <li key={i} className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {w}
            </li>
          ))}
        </ul>
      )}
      {groups.map((g) => (
        <Section key={g.id || "other"} title={g.title}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {g.steps.map((s) => (
              <Card key={s.i} className={`overflow-hidden ${s.blank || s.no_effect ? "opacity-60" : ""}`}>
                {s.screenshot && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={fileUrl(jobId, s.screenshot)} alt={`Bước ${s.i}`} className="h-36 w-full object-cover object-top" />
                )}
                <CardContent className="space-y-1 pt-3 text-xs">
                  <p className="font-medium">
                    <span className="mr-1 text-primary">{s.i}.</span>
                    {stepLine(s)}
                  </p>
                  {(s.blank || s.no_effect) && (
                    <p className="text-amber-700">
                      {s.blank ? "Trang trống sau khi chờ, bước này không dùng cho video." : "Bước này không làm trang đổi, không dùng cho video."}
                    </p>
                  )}
                  {s.url_after && <p className="truncate text-muted-foreground">{s.url_after}</p>}
                </CardContent>
              </Card>
            ))}
          </div>
        </Section>
      ))}
      <Section title="Cần sửa gì không?">
        <Textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="Ví dụ: chọn loại nghỉ Annual thay vì Personal"
          aria-label="Yêu cầu sửa luồng"
          disabled={busy}
        />
        <div className="flex flex-wrap gap-2">
          {EDIT_EXAMPLES.map((e) => (
            <Button key={e} variant="outline" size="sm" disabled={busy} onClick={() => setInstruction(e)}>
              {e}
            </Button>
          ))}
        </div>
      </Section>
      <ErrorNote text={error} />
      {(pending.flow_quality?.label || pending.flow_quality?.empty_warning || pending.flow_quality?.env_warning) && (
        <ul role="status" aria-label="Cảnh báo chất lượng luồng" className="space-y-1">
          {[pending.flow_quality.label, pending.flow_quality.empty_warning, pending.flow_quality.env_warning].filter((w): w is string => Boolean(w)).map((w) => (
            <li key={w} className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {w.replace(/\.?$/, ".")} Bạn vẫn có thể duyệt.
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || !canApprove(run)} onClick={() => send(() => buildResponse(pending, "approve"))}>
          {busy ? "Đang gửi..." : "Duyệt luồng này"}
        </Button>
        <Button variant="outline" disabled={busy || !instruction.trim()} onClick={() => send(() => buildResponse(pending, "edit", editFields(instruction)))}>
          Gửi yêu cầu sửa
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => send(() => buildResponse(pending, "regenerate"))}>
          Chạy lại từ đầu
        </Button>
      </div>
      {!canApprove(run) && <p className="text-sm text-amber-700">Luồng chưa có đủ bước để quay. Hãy sửa hoặc chạy lại.</p>}
    </div>
  );
}
