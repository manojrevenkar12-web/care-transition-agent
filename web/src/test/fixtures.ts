import type { CaseDetail, CaseDocument, CaseSummary, Draft, DraftField, Me } from "@/lib/types";

export const me: Me = {
  user: "dr.weber",
  tenant: "klinikum-nord",
  tenant_name: "Klinikum Nord",
  role: "clinician",
  permissions: ["cases.read", "cases.import", "documents.original", "drafts.run", "drafts.review", "drafts.release", "chat", "runs.read"],
};

export const caseSummary: CaseSummary = {
  id: "c1",
  external_ref: "FALL-0001",
  as_of: "2026-10-12",
  created_at: "2026-10-12T08:00:00",
  status: "open",
  documents: 2,
  blocked: 0,
  draft_id: "d1",
  draft_status: "draft",
  draft_at: "2026-10-12T09:00:00",
  pending: 2,
  flagged: 1,
};

const docText = "Pat. Frau Erika Lang mobil mit Rollator. Kein Sauerstoff mehr nötig.";
const pseudo = "Pat. Frau «Patient» mobil mit Rollator. Kein Sauerstoff mehr nötig.";
export const documents: CaseDocument[] = [
  {
    id: "d1",
    kind: "pflege",
    title: "Pflegebericht",
    authored_at: "2026-10-10T08:00:00",
    author_role: "Pflege",
    blocked: false,
    text: docText,
    pseudo,
    replacements: [{ start: 10, end: 20, out_start: 10, out_end: 19, kind: "name", tag: "«Patient»" }],
    injection_spans: [],
  },
];

export const caseDetail: CaseDetail = {
  id: "c1",
  external_ref: "FALL-0001",
  as_of: "2026-10-12",
  created_at: "2026-10-12T08:00:00",
  retention_until: "2026-11-11",
  documents: [{ id: "d1", kind: "pflege", title: "Pflegebericht", authored_at: "2026-10-10T08:00:00", author_role: "Pflege", leak_kinds: [], replaced: 1, injections: 0 }],
  drafts: [{ id: "d1", status: "draft", prompt_version: "v2", model: "sim-careful", created_at: "2026-10-12T09:00:00" }],
};

const quoteStart = pseudo.indexOf("mit Rollator");
function field(over: Partial<DraftField>): DraftField {
  return {
    field: "mobility",
    section: "mobilitaet",
    label: { de: "Mobilität", en: "Mobility" },
    type: "enum",
    options: [
      { value: "rollator", label: "Rollator" },
      { value: "rollstuhl", label: "Rollstuhl" },
    ],
    required: true,
    required_if: null,
    severity: "major",
    agent_value: "rollator",
    agent_label: "Rollator",
    agent_status: "grounded",
    reason: null,
    evidence: [{ doc_id: "d1", quote: "mit Rollator", start: quoteStart, end: quoteStart + 12, orig_start: docText.indexOf("mit Rollator"), orig_end: docText.indexOf("mit Rollator") + 12 }],
    counter: [],
    question: null,
    review: "pending",
    final_value: null,
    final_label: "",
    reviewed_by: null,
    ...over,
  };
}

export const draft: Draft = {
  id: "d1",
  case_id: "c1",
  run_id: "r1",
  status: "draft",
  prompt_version: "v2",
  model: "sim-careful",
  created_at: "2026-10-12T09:00:00",
  released_at: null,
  released_by: null,
  fields: [
    field({}),
    field({
      field: "oxygen",
      section: "behandlungspflege",
      label: { de: "Sauerstoff", en: "Oxygen" },
      type: "boolean",
      options: [],
      agent_value: true,
      agent_label: "",
      agent_status: "contradicted",
      reason: "the quoted statement says the opposite",
      evidence: [{ doc_id: "d1", quote: "Sauerstoff", start: pseudo.indexOf("Sauerstoff"), end: pseudo.indexOf("Sauerstoff") + 10 }],
    }),
  ],
  blocking: [
    { field: "mobility", reason: "needs a decision" },
    { field: "oxygen", reason: "needs a decision" },
  ],
};

type Handler = (init: RequestInit | undefined, url: string) => { status?: number; body: unknown };

/** A fetch stand-in that answers by "METHOD path" and records calls. */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  const fetchMock = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const path = url.split("?")[0]!;
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const route = routes[`${method} ${path}`];
    if (route === undefined) return new Response(JSON.stringify({ detail: `no mock for ${method} ${path}` }), { status: 404 });
    const res = typeof route === "function" ? (route as Handler)(init, url) : { body: route };
    return new Response(JSON.stringify(res.body), { status: res.status ?? 200, headers: { "Content-Type": "application/json" } });
  };
  globalThis.fetch = fetchMock as typeof fetch;
  return calls;
}
