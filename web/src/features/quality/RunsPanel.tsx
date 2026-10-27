import { Link } from "react-router-dom";
import { Panel } from "@/components/Panel";
import { SkeletonLines } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/States";
import { Chip } from "@/components/StatusChip";
import { dateTime, number } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useRuns } from "./api";
import s from "./Quality.module.css";

export function RunsPanel() {
  const { t, lang } = useI18n();
  const q = useRuns();
  return (
    <Panel id="runs" title={t("quality.runs")}>
      {q.isPending && <SkeletonLines lines={5} label={t("state.loading")} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />}
      {q.data?.length === 0 && <EmptyState title={t("runs.empty")} body={t("quality.lead")} />}
      {q.data && q.data.length > 0 && (
        <div className={s.scroll}>
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">{lang === "de" ? "Gestartet" : "Started"}</th>
                <th scope="col">Workflow</th>
                <th scope="col">{lang === "de" ? "Prompt und Modell" : "Prompt and model"}</th>
                <th scope="col" className={s.num}>{lang === "de" ? "Modellaufrufe" : "Model calls"}</th>
                <th scope="col" className={s.num}>Tokens</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((r) => (
                <tr key={r.id}>
                  <th scope="row">
                    <Link to={`/runs/${r.id}`}>{dateTime(r.started_at, lang)}</Link>
                  </th>
                  <td>{r.workflow}</td>
                  <td>{r.prompt_version ? `${r.prompt_version}@${r.model}` : "–"}</td>
                  <td className={s.num}>{r.model_calls}</td>
                  <td className={s.num}>{number(r.input_tokens + r.output_tokens, lang)}</td>
                  <td>
                    <Chip tone={r.status === "completed" ? "ready" : r.status === "running" ? "neutral" : "alert"}>{r.status}</Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
