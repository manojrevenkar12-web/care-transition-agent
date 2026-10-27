/** Shapes returned by the API (src/cta/api.py). */

export type Role = "clinician" | "coordinator" | "quality";

export interface Me {
  user: string;
  tenant: string;
  tenant_name: string;
  role: Role;
  permissions: string[];
}

export interface CaseSummary {
  id: string;
  external_ref: string | null;
  as_of: string;
  created_at: string;
  status: string;
  documents: number;
  blocked: number;
  draft_id: string | null;
  draft_status: "draft" | "released" | null;
  draft_at: string | null;
  pending: number | null;
  flagged: number | null;
}

export interface CaseDocumentMeta {
  id: string;
  kind: string;
  title: string;
  authored_at: string;
  author_role: string | null;
  leak_kinds: string[];
  replaced: number;
  injections: number;
}

export interface CaseDetail {
  id: string;
  external_ref: string | null;
  as_of: string;
  created_at: string;
  retention_until: string;
  documents: CaseDocumentMeta[];
  drafts: Array<{ id: string; status: string; prompt_version: string; model: string; created_at: string }>;
}

export interface Replacement {
  start: number;
  end: number;
  out_start: number;
  out_end: number;
  kind: string;
  tag: string;
}

export interface CaseDocument {
  id: string;
  kind: string;
  title: string;
  authored_at: string;
  author_role: string | null;
  blocked: boolean;
  text: string;
  pseudo: string;
  replacements: Replacement[];
  injection_spans: Array<[number, number]>;
}

export interface Evidence {
  doc_id: string;
  quote?: string;
  start: number;
  end: number;
  orig_start?: number;
  orig_end?: number;
  status?: string;
  authored_at?: string;
}

export type AgentStatus =
  | "grounded"
  | "conflict"
  | "contradicted"
  | "unsupported"
  | "quote_not_found"
  | "injection"
  | "invalid"
  | "unknown"
  | "unknown_but_mentioned"
  | "missing";

export type ReviewState = "pending" | "accepted" | "edited" | "answered" | "rejected";

export interface DraftField {
  field: string;
  section: string;
  label: { de: string; en: string };
  type: "enum" | "boolean" | "date" | "text" | "summary";
  options: Array<{ value: string; label: string }>;
  required: boolean;
  required_if: Record<string, unknown> | null;
  severity: "major" | "minor";
  agent_value: unknown;
  agent_label: string;
  agent_status: AgentStatus;
  reason: string | null;
  evidence: Evidence[];
  counter: Evidence[];
  question: string | null;
  review: ReviewState;
  final_value: unknown;
  final_label: string;
  reviewed_by: string | null;
}

export interface Draft {
  id: string;
  case_id: string;
  run_id: string | null;
  status: "draft" | "released" | "superseded";
  prompt_version: string;
  model: string;
  created_at: string;
  released_at: string | null;
  released_by: string | null;
  fields: DraftField[];
  blocking: Array<{ field: string; reason: string }>;
}

export interface DraftRun {
  run_id: string;
  draft_id: string | null;
  status: string;
  prompt_version: string;
  model: string;
  arm: string;
  model_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
}

export interface ChatMessage {
  id: number;
  run_id: string | null;
  role: "user" | "assistant";
  text: string;
  citations: Array<{ doc_id: string; quote: string; found?: boolean }>;
  status: string;
  feedback: string | null;
  at: string;
}

export interface ChatReply {
  run_id: string;
  workflow: string;
  status: string;
  kind: "answer" | "refusal" | "draft" | "providers" | "error";
  text?: string;
  display_text?: string;
}

export interface Run {
  id: string;
  case_id: string;
  workflow: string;
  status: string;
  prompt: string | null;
  prompt_version: string | null;
  model: string | null;
  upstream: string | null;
  trace_id: string | null;
  started_at: string;
  finished_at: string | null;
  input_tokens: number;
  output_tokens: number;
  model_calls: number;
  tool_calls: number;
  error: string | null;
}

export interface RunStep {
  seq: number;
  kind: "model" | "tool" | "guard";
  name: string;
  started_at: string;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  status: string;
  detail: Record<string, unknown>;
}

export interface RunDetail extends Run {
  steps: RunStep[];
}

export interface OfflineMetrics {
  cases: number;
  fields: number;
  field_accuracy: number;
  ready_share: number;
  ready_precision: number;
  wrong_ready: number;
  major_wrong_ready: number;
  review_load: number;
  silent_major_omissions: number;
  creola: Record<string, number>;
  tokens_per_case: number;
  model_calls_per_case: number;
  summary_flagged: number;
}

export interface GateResult {
  passed: boolean;
  checks: Array<{ check: string; passed: boolean; value: string | number }>;
}

export interface OfflineReport {
  set: string;
  candidate: string;
  baseline?: string;
  metrics: OfflineMetrics;
  baseline_metrics?: OfflineMetrics;
  paired_accuracy?: { delta: number; low: number; high: number; n: number };
  gate?: GateResult;
}

export interface JudgeCriterion {
  n: number;
  accuracy: number;
  kappa: number;
  fail_recall: number;
  fail_n: number;
  trusted: boolean;
}

export interface Reports {
  eval: Record<string, OfflineReport | { judge: Record<string, JudgeCriterion> }>;
  heldout: Record<string, Record<string, unknown>>;
}

export interface OnlineMetrics {
  window_days: number;
  events: number;
  ready_accepted: number;
  ready_edited: number;
  flag_precision: number;
  by_arm: Record<string, { n: number; seconds_per_field: number | null; [action: string]: number | null }>;
  by_status: Record<string, { n: number; [action: string]: number }>;
  most_edited_fields: Array<[string, number]>;
  chat: Record<string, number>;
}

export interface PromptTable {
  files: Record<string, Array<{ version: string; sha: string; default: boolean }>>;
  defaults: Record<string, { version: string; model: string }>;
  deployments: Array<{ tenant_id: string; prompt: string; version: string; model: string; share: number; since: string }>;
}
