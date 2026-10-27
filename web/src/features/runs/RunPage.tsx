import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Link, useParams } from "react-router-dom";
import { Panel } from "@/components/Panel";
import { SkeletonLines } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/States";
import { Chip } from "@/components/StatusChip";
import { api } from "@/lib/api";
import { dateTime, number } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { RunDetail, RunStep } from "@/lib/types";
import { motion as m } from "@/theme/tokens";
import s from "./RunPage.module.css";

const KIND = {
  model: { de: "Modell", en: "Model" },
  tool: { de: "Werkzeug", en: "Tool" },
  guard: { de: "Schutzregel", en: "Guard" },
};

/** One agent run as a waterfall: what the model was asked, which tools ran, how long each took. No content is stored. */
export function RunPage() {
  const { runId = "" } = useParams();
  const { t, lang } = useI18n();
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => api<RunDetail>(`/api/runs/${runId}`) });

  if (q.isPending) return <SkeletonLines lines={10} label={t("state.loading")} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const r = q.data;
  const t0 = new Date(r.started_at).getTime();
  const spans = r.steps.map((st) => ({ st, from: new Date(st.started_at).getTime() - t0 }));
  const total = Math.max(1, ...spans.map(({ st, from }) => from + st.duration_ms));

  return (
    <div className={s.page}>
      <header>
        <Link to={`/cases/${r.case_id}`} className={s.back}>
          {t("review.back")}
        </Link>
        <h1>
          {t("runs.title")} {r.workflow}
        </h1>
        <p className={s.meta}>
          {dateTime(r.started_at, lang)}, {r.prompt_version ? `${r.prompt_version}@${r.model}` : ""} {r.upstream ? `via ${r.upstream}` : ""}
        </p>
      </header>
      <dl className={s.facts}>
        <div>
          <dt>Status</dt>
          <dd>
            <Chip tone={r.status === "completed" ? "ready" : "alert"}>{r.status}</Chip>
          </dd>
        </div>
        <div>
          <dt>{lang === "de" ? "Modellaufrufe" : "Model calls"}</dt>
          <dd>{r.model_calls}</dd>
        </div>
        <div>
          <dt>{lang === "de" ? "Werkzeugaufrufe" : "Tool calls"}</dt>
          <dd>{r.tool_calls}</dd>
        </div>
        <div>
          <dt>{lang === "de" ? "Tokens ein / aus" : "Tokens in / out"}</dt>
          <dd>
            {number(r.input_tokens, lang)} / {number(r.output_tokens, lang)}
          </dd>
        </div>
        <div>
          <dt>{lang === "de" ? "Dauer" : "Duration"}</dt>
          <dd>{number(total, lang)} ms</dd>
        </div>
        {r.trace_id && (
          <div>
            <dt>Trace</dt>
            <dd className={s.mono}>{r.trace_id}</dd>
          </div>
        )}
      </dl>
      {r.error && <ErrorState error={new Error(r.error)} compact />}
      <Panel id="steps" title={t("runs.steps")}>
        {r.steps.length === 0 ? (
          <EmptyState title={t("runs.empty")} body="" />
        ) : (
          <ol className={s.waterfall}>
            {spans.map(({ st, from }, i) => (
              <Step key={st.seq} st={st} from={from} total={total} i={i} />
            ))}
          </ol>
        )}
      </Panel>
    </div>
  );
}

function Step({ st, from, total, i }: { st: RunStep; from: number; total: number; i: number }) {
  const { lang } = useI18n();
  const left = (from / total) * 100;
  const width = Math.max(0.6, (st.duration_ms / total) * 100);
  const detail = Object.entries(st.detail)
    .filter(([, v]) => v !== null && v !== "" && typeof v !== "object")
    .map(([k, v]) => `${k} ${String(v)}`)
    .join(", ");
  return (
    <li className={s.step}>
      <span className={s.label}>
        <span className={`${s.kind} ${s[st.kind]}`}>{KIND[st.kind][lang]}</span> {st.name}
        {detail && <span className={s.detail}>{detail}</span>}
      </span>
      <span className={s.lane}>
        <motion.span
          className={`${s.bar} ${s[st.kind]}`}
          style={{ left: `${left}%` }}
          initial={{ width: 0 }}
          animate={{ width: `${width}%` }}
          transition={{ duration: m.expand.duration, delay: Math.min(i, 30) * 0.015, ease: m.ease }}
          title={`${st.duration_ms} ms`}
        />
      </span>
      <span className={s.ms}>
        {st.duration_ms} ms{st.kind === "model" ? `, ${st.input_tokens}+${st.output_tokens} tok` : ""}
      </span>
    </li>
  );
}
