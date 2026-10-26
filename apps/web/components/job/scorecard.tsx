"use client";

import { CheckCircle2, CircleDashed, Info, XCircle } from "lucide-react";
import type { ScoreLine, Scorecard } from "@/lib/api";
import { STATUS_TEXT, scoreVerdict } from "@/lib/scorecard";
import { Badge } from "@/components/ui/badge";
import { Section } from "./shared";

function StatusIcon({ status }: { status: ScoreLine["status"] }) {
  if (status === "pass") return <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden />;
  if (status === "fail") return <XCircle className="h-4 w-4 text-red-600" aria-hidden />;
  if (status === "na") return <CircleDashed className="h-4 w-4 text-muted-foreground" aria-hidden />;
  return <Info className="h-4 w-4 text-muted-foreground" aria-hidden />;
}

/** The marketing scorecard of the finished video: one line per promise, pass / fail. */
export function ScorecardPanel({ card }: { card: Scorecard }) {
  return (
    <Section title="Chấm điểm video">
      <div className="flex items-center gap-2 text-sm">
        <Badge tone={card.all_passed ? "success" : card.failed > 0 ? "warning" : "muted"}>{scoreVerdict(card)}</Badge>
      </div>
      <ul className="divide-y divide-border rounded-lg border border-border text-sm">
        {card.lines.map((l) => (
          <li key={l.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
            <StatusIcon status={l.status} />
            <span className="font-medium">{l.label}</span>
            <span className="text-xs text-muted-foreground">
              {l.value === null ? "—" : String(l.value)} · cần {l.target}
            </span>
            <span className="ml-auto text-xs" aria-label={`${l.label}: ${STATUS_TEXT[l.status]}`}>
              {STATUS_TEXT[l.status]}
            </span>
            {l.note && <span className="w-full text-xs text-muted-foreground">{l.note}</span>}
          </li>
        ))}
      </ul>
    </Section>
  );
}
