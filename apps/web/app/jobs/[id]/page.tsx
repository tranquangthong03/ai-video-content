"use client";

import { use, useState } from "react";
import { api } from "@/lib/api";
import { useJob } from "@/lib/use-job";
import { Button } from "@/components/ui/button";
import { LoginCard } from "@/components/job/login-card";
import { MarketingBriefCard } from "@/components/job/brief-card";
import { SelectFlowCard, StoryboardCard } from "@/components/job/flow-cards";
import { ClarifyCard, ConceptCard, ConfirmCard, OutlineCard, SelectFeaturesCard } from "@/components/job/proposal-cards";
import { FailedPanel, RunningPanel, Sidebar, StatusBadge, VideoPanel } from "@/components/job/panels";
import { ScriptCard } from "@/components/job/script-card";
import { ErrorNote, type JobCtx } from "@/components/job/shared";

export default function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { job, error, refresh, markAnswered } = useJob(id);
  const [cancelling, setCancelling] = useState(false);

  if (!job) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-10">
        {error ? <ErrorNote text={error} /> : <p className="text-sm text-muted-foreground">Đang tải...</p>}
      </main>
    );
  }

  const ctx: JobCtx = { job, refresh, markAnswered };
  const { state, pending } = job;
  const active = ["queued", "running", "waiting"].includes(state.status);

  async function cancel() {
    setCancelling(true);
    try {
      await api.cancel(id);
      await refresh();
    } finally {
      setCancelling(false);
    }
  }

  let body: React.ReactNode;
  if (state.status === "done") body = <VideoPanel ctx={ctx} />;
  else if (state.status === "failed" || state.status === "cancelled") body = <FailedPanel ctx={ctx} />;
  else if (state.status === "waiting" && pending) {
    if (pending.kind === "login_required" && pending.login) body = <LoginCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "confirm_understanding" && pending.profile) body = <ConfirmCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "select_features" && pending.profile) body = <SelectFeaturesCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "select_flow" && pending.flow_select) body = <SelectFlowCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "flow_storyboard_review" && pending.flow_review) body = <StoryboardCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "marketing_brief" && pending.brief_form) body = <MarketingBriefCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "choose_concept") body = <ConceptCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "outline_review" && pending.outline) body = <OutlineCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "script_review") body = <ScriptCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else if (pending.kind === "clarify") body = <ClarifyCard key={pending.interaction_id} ctx={ctx} pending={pending} />;
    else body = <p className="text-sm text-muted-foreground">Bước này chưa hỗ trợ trên giao diện web.</p>;
  } else body = <RunningPanel job={job} />;

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <a href="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← Công việc
        </a>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{state.url}</span>
        <StatusBadge status={state.status} />
        {active && (
          <Button variant="outline" size="sm" disabled={cancelling} onClick={cancel}>
            Hủy
          </Button>
        )}
      </div>
      <ErrorNote text={error} />
      <div className="grid gap-8 lg:grid-cols-[220px_1fr]">
        <Sidebar job={job} />
        <div className="min-w-0">{body}</div>
      </div>
    </main>
  );
}
