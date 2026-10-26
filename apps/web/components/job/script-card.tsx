"use client";

import { useState } from "react";
import { Pencil } from "lucide-react";
import type { InteractionRequest } from "@/lib/generated";
import type { SceneView } from "@/lib/api";
import { SHOT_LABEL, seconds, splitHighlight } from "@/lib/labels";
import { buildResponse, editFields, setOpFields } from "@/lib/responses";
import { HOOK_KIND_LABEL, criticRows } from "@/lib/critic";
import type { CriticReport, HookOption } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/field";
import { ErrorNote, Notices, Section, useSend, type JobCtx } from "./shared";

const TYPE_LABEL: Record<string, string> = {
  hook: "Mở đầu",
  feature_demo: "Demo tính năng",
  before_after: "Trước / sau",
  cta: "Kêu gọi",
};

function SceneCard({
  index,
  scene,
  disabled,
  onSet,
}: {
  index: number;
  scene: SceneView;
  disabled: boolean;
  onSet: (field: "voiceover" | "on_screen_text", value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [voice, setVoice] = useState(scene.voiceover ?? "");
  const [onScreen, setOnScreen] = useState(scene.on_screen_text ?? "");

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center gap-2 pb-1">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
          {index + 1}
        </span>
        <Badge tone="muted">{TYPE_LABEL[scene.type] ?? scene.type}</Badge>
        <Badge tone={scene.shot === "chữ" ? "warning" : "success"}>{SHOT_LABEL[scene.shot] ?? scene.shot}</Badge>
        <span className="ml-auto text-xs text-muted-foreground">{seconds(scene.estimated_ms)}</span>
        <Button variant="ghost" size="sm" aria-label={`Sửa cảnh ${index + 1}`} onClick={() => setEditing(!editing)}>
          <Pencil className="h-3.5 w-3.5" /> Sửa
        </Button>
      </CardHeader>
      <CardContent className="space-y-2">
        {scene.key_point && <p className="text-sm font-medium">{scene.key_point}</p>}
        {!editing ? (
          <>
            <p className="text-sm text-muted-foreground">{scene.voiceover}</p>
            {scene.on_screen_text && <p className="text-xs">Chữ trên màn hình: “{scene.on_screen_text}”</p>}
          </>
        ) : (
          <div className="space-y-2">
            <label className="block space-y-1 text-xs">
              Lời đọc
              <Textarea value={voice} onChange={(e) => setVoice(e.target.value)} />
            </label>
            <label className="block space-y-1 text-xs">
              Chữ trên màn hình
              <Input value={onScreen} onChange={(e) => setOnScreen(e.target.value)} />
            </label>
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={disabled || !voice.trim()}
                onClick={() => {
                  if (voice.trim() !== (scene.voiceover ?? "")) onSet("voiceover", voice.trim());
                  else if (onScreen.trim() !== (scene.on_screen_text ?? "")) onSet("on_screen_text", onScreen.trim());
                  setEditing(false);
                }}
              >
                Lưu
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Hủy
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Five score bars of the copy critic, with its one-line summary. */
function CriticPanel({ report }: { report: CriticReport }) {
  const rows = criticRows(report);
  if (report.error || rows.length === 0) return null;
  const view = report.final ?? report.before;
  return (
    <Section title="Chấm điểm nội dung">
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.key} className="space-y-0.5">
            <div className="flex items-center justify-between text-xs">
              <span>{r.label}</span>
              <span className={r.ok === false ? "font-semibold text-amber-700" : "text-muted-foreground"}>
                {r.score === null ? "chưa có bằng chứng" : `${r.score}/10`}
              </span>
            </div>
            <div
              role="meter"
              aria-label={r.label}
              aria-valuemin={0}
              aria-valuemax={10}
              aria-valuenow={r.score ?? 0}
              className="h-2 overflow-hidden rounded bg-muted"
            >
              <div className={`h-full ${r.ok === false ? "bg-amber-500" : "bg-emerald-600"}`} style={{ width: `${r.percent}%` }} />
            </div>
            {r.reason && <p className="text-xs text-muted-foreground">{r.reason}</p>}
          </li>
        ))}
      </ul>
      {view?.summary && <p className="text-sm">{view.summary}</p>}
      {report.rewritten && report.rewritten.length > 0 && report.kept_rewrite && (
        <p className="text-xs text-muted-foreground">Đã tự viết lại cảnh {report.rewritten.join(", ")} theo gợi ý.</p>
      )}
      {report.edited && <p className="text-xs text-muted-foreground">Điểm của bản trước khi bạn sửa (không chấm lại tự động).</p>}
    </Section>
  );
}

/** Two hook options: pick one (a deterministic edit, no model). */
function HookChooser({
  options,
  chosen,
  disabled,
  onPick,
}: {
  options: HookOption[];
  chosen: number | null | undefined;
  disabled: boolean;
  onPick: (n: number) => void;
}) {
  if (options.length < 2) return null;
  return (
    <Section title="Chọn hook mở đầu">
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((o, i) => (
          <button
            key={o.kind}
            type="button"
            disabled={disabled}
            aria-pressed={chosen === i + 1}
            onClick={() => chosen !== i + 1 && onPick(i + 1)}
            className={`rounded-lg border p-3 text-left text-sm ${chosen === i + 1 ? "border-primary bg-accent" : "border-border"}`}
          >
            <Badge tone="muted">{HOOK_KIND_LABEL[o.kind] ?? o.kind}</Badge>
            <p className="mt-1">{o.voiceover}</p>
            {o.on_screen_text && <p className="mt-1 text-xs text-muted-foreground">Chữ: “{o.on_screen_text}”</p>}
          </button>
        ))}
      </div>
    </Section>
  );
}

/** script_review: scenes, totals, warnings, quick edits, free edit, versions. */
export function ScriptCard({ ctx, pending }: { ctx: JobCtx; pending: InteractionRequest }) {
  const extra = ctx.job.pending_extra;
  const { send, busy, error } = useSend(ctx);
  const [text, setText] = useState("");
  if (!extra) return <p className="text-sm text-muted-foreground">Đang tải kịch bản...</p>;

  const version = extra.version;
  const [pre, mark, post] = splitHighlight(extra.headline ?? "", extra.headline_highlight);
  const diff = (extra.estimated_ms / 1000 / extra.target_duration_s - 1) * 100;
  const ratio = extra.footage_ratio;
  const lowFootage = ratio !== null && extra.footage_min !== null && ratio < extra.footage_min;
  const old = extra.versions.filter((v) => v !== version);

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        {extra.badge && <Badge>{extra.badge}</Badge>}
        <h2 className="text-2xl font-bold leading-tight">
          {pre}
          <span style={{ color: extra.theme?.primary }}>{mark}</span>
          {post}
        </h2>
        <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          <span className="flex items-center gap-1.5">
            Màu thương hiệu
            <span aria-label="màu thương hiệu" className="inline-block h-4 w-4 rounded border border-border" style={{ background: extra.theme?.primary }} />
            <code className="text-xs">{extra.theme?.primary}</code>
          </span>
          <Badge tone="muted">Kịch bản v{version}</Badge>
        </div>
      </div>

      <Notices message={pending.message} />
      <div className="grid gap-2 rounded-lg bg-muted p-3 text-sm sm:grid-cols-3">
        <div>
          Thời lượng: <b>{(extra.estimated_ms / 1000).toFixed(1)}s</b> / mục tiêu {extra.target_duration_s}s{" "}
          <span className={Math.abs(diff) > 10 ? "text-amber-700" : "text-emerald-700"}>({diff >= 0 ? "+" : ""}{diff.toFixed(0)}%)</span>
        </div>
        <div>
          Cảnh quay thật: <b>{ratio === null ? "—" : `${Math.round(ratio * 100)}%`}</b>
          {extra.footage_min !== null && <span className="text-muted-foreground"> (cần ≥ {Math.round(extra.footage_min * 100)}%)</span>}
        </div>
        <div>{extra.scenes.length} cảnh</div>
      </div>
      {(extra.warnings.length > 0 || lowFootage) && (
        <ul className="space-y-1">
          {extra.warnings.map((w, i) => (
            <li key={i} className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
              {w}
            </li>
          ))}
        </ul>
      )}

      {extra.critic && <CriticPanel report={extra.critic} />}
      {extra.hook_scene_id && (
        <HookChooser
          options={extra.hook_options ?? []}
          chosen={extra.chosen_hook}
          disabled={busy}
          onPick={(n) =>
            send(() => buildResponse(pending, "edit", { ...setOpFields(extra.hook_scene_id!, "hook_option", String(n)), base_version: version }))
          }
        />
      )}

      <div className="space-y-3">
        {extra.scenes.map((s, i) => (
          <SceneCard
            key={`${version}-${s.id}`}
            index={i}
            scene={s}
            disabled={busy}
            onSet={(field, value) => send(() => buildResponse(pending, "edit", { ...setOpFields(s.id, field, value), base_version: version }))}
          />
        ))}
      </div>

      <Section title="Sửa bằng câu tự do">
        <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Ví dụ: scene 2 nói ngắn hơn, đổi màu chủ đạo thành #0F766E..." />
      </Section>
      <ErrorNote text={error} />
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy || !text.trim()} onClick={() => send(() => buildResponse(pending, "edit", { ...editFields(text), base_version: version }))}>
          Gửi yêu cầu sửa
        </Button>
        <Button disabled={busy} onClick={() => send(() => buildResponse(pending, "approve", { base_version: version }))}>
          Duyệt & sản xuất
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => send(() => buildResponse(pending, "regenerate", { base_version: version }))}>
          Sinh lại
        </Button>
      </div>
      {old.length > 0 && (
        <Section title="Lịch sử phiên bản">
          <div className="flex flex-wrap gap-2">
            {old.map((v) => (
              <Button key={v} size="sm" variant="outline" disabled={busy} onClick={() => send(() => buildResponse(pending, "revert", { revert_to: v, base_version: version }))}>
                Quay về v{v}
              </Button>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
