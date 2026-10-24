import { UserResponseSchema, type InteractionRequest, type UserResponse } from "./generated";

type Fields = Partial<Omit<UserResponse, "interaction_id" | "job_id" | "action">>;

/** Builds a UserResponse for the pending question and validates it with the generated schema. */
export function buildResponse(
  pending: Pick<InteractionRequest, "interaction_id" | "job_id">,
  action: UserResponse["action"],
  fields: Fields = {},
): UserResponse {
  return UserResponseSchema.parse({
    interaction_id: pending.interaction_id,
    job_id: pending.job_id,
    action,
    ...fields,
  });
}

/** confirm_understanding → "answer": feature ids to drop, an edited description, free notes. */
export function confirmFields(opts: {
  allFeatureIds: string[];
  selected: Set<string>;
  oneLiner: string;
  originalOneLiner: string;
  answers: Record<string, string>;
  notes: string;
}): Fields {
  const exclude = opts.allFeatureIds.filter((id) => !opts.selected.has(id));
  const answers: Record<string, string> = {};
  for (const [k, v] of Object.entries(opts.answers)) if (v.trim()) answers[k] = v.trim();
  if (opts.notes.trim()) answers.notes = opts.notes.trim();
  const changedLine = opts.oneLiner.trim() !== opts.originalOneLiner.trim() && opts.oneLiner.trim() !== "";
  return {
    profile_edit: {
      exclude_feature_ids: exclude,
      one_liner: changedLine ? opts.oneLiner.trim() : null,
      target_users: null,
      added_features: [],
    },
    answers: Object.keys(answers).length ? answers : null,
  };
}

/** choose_concept: the chosen concept, plus a duration note when it is not the proposed one. */
export function conceptFields(opts: {
  conceptId: string;
  durationS: number;
  proposedS: number;
  notes: string;
}): Fields {
  const parts = [opts.notes.trim()];
  if (opts.durationS !== opts.proposedS) parts.push(`Đặt thời lượng ${opts.durationS} giây.`);
  const notes = parts.filter(Boolean).join(" ");
  return { answers: { concept_id: opts.conceptId, notes } };
}

export const editFields = (instruction: string): Fields => ({
  edit: { instruction: instruction.trim(), targets: [], ops: [] },
});

/** A quick edit of one scene field becomes a deterministic `set` op (no LLM). */
export function setOpFields(sceneId: string, field: "voiceover" | "on_screen_text", value: string): Fields {
  return { edit: { instruction: null, targets: [], ops: [{ op: "set", scene_id: sceneId, field, value }] } };
}
