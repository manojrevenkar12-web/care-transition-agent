import { Bar, Panel } from "@/components/Panel";
import { SkeletonLines } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/States";
import { number, percent } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useOnline } from "./api";
import s from "./Quality.module.css";

/** What clinicians did with the drafts: no labels needed, the review actions are the signal. */
export function OnlinePanel() {
  const { t, lang } = useI18n();
  const q = useOnline();
  return (
    <Panel id="online" title={t("quality.online", { n: q.data?.window_days ?? 7 })}>
      {q.isPending && <SkeletonLines lines={4} label={t("state.loading")} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />}
      {q.data && q.data.events === 0 && <EmptyState title={t("quality.empty.online")} body={t("quality.lead")} />}
      {q.data && q.data.events > 0 && (
        <>
          <Bar label={lang === "de" ? "Belegte Werte übernommen" : "Grounded values accepted"} value={q.data.ready_accepted} max={1} display={percent(q.data.ready_accepted)} />
          <Bar label={lang === "de" ? "Belegte Werte geändert" : "Grounded values changed"} value={q.data.ready_edited} max={1} display={percent(q.data.ready_edited)} />
          <Bar label={lang === "de" ? "Markierungen berechtigt" : "Flags that were right"} value={q.data.flag_precision} max={1} display={percent(q.data.flag_precision)} />
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">{lang === "de" ? "Prompt und Modell" : "Prompt and model"}</th>
                <th scope="col" className={s.num}>{lang === "de" ? "Aktionen" : "Actions"}</th>
                <th scope="col" className={s.num}>{lang === "de" ? "übernommen" : "accepted"}</th>
                <th scope="col" className={s.num}>{lang === "de" ? "geändert" : "changed"}</th>
                <th scope="col" className={s.num}>{lang === "de" ? "Sekunden pro Feld" : "Seconds per field"}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(q.data.by_arm).map(([arm, v]) => (
                <tr key={arm}>
                  <th scope="row">{arm}</th>
                  <td className={s.num}>{v.n}</td>
                  <td className={s.num}>{percent(v.accepted ?? 0)}</td>
                  <td className={s.num}>{percent(v.edited ?? 0)}</td>
                  <td className={s.num}>{number(v.seconds_per_field, lang, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Panel>
  );
}
