import { Panel } from "@/components/Panel";
import { Chip } from "@/components/StatusChip";
import { percent } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import s from "./Quality.module.css";

interface Run {
  set: string;
  status_at_run?: string;
  rescored_because?: string;
  pii?: { listed_recall: number; unlisted_recall: number; documents: number; documents_with_listed_identifier_reaching_model: number; must_keep_destroyed: number; must_keep_total: number };
  grounding?: { accuracy: number; wrongly_grounded: number; items: number };
  guards?: Record<string, { recall: number; precision: number }>;
}

/** First runs of the blind sets, as recorded. They are never rewritten; a set studied after its run is a regression set. */
export function HeldoutPanel({ runs }: { runs: Record<string, Record<string, unknown>> }) {
  const { t, lang } = useI18n();
  const rows = Object.entries(runs) as unknown as Array<[string, Run]>;
  return (
    <Panel id="heldout" title={t("quality.heldout")}>
      <p className={s.note}>
        {lang === "de"
          ? "Geschrieben von jemandem, der den Code nicht kannte, und genau einmal gelaufen. Diese Zahlen wurden vor jeder Änderung aufgezeichnet."
          : "Written by someone who had not seen the code, and run exactly once. These numbers were recorded before any change."}
      </p>
      <div className={s.scroll}>
        <table className={s.table}>
          <thead>
            <tr>
              <th scope="col">Set</th>
              <th scope="col" className={s.num}>{lang === "de" ? "Gelistete Kennzeichen ersetzt" : "Listed identifiers replaced"}</th>
              <th scope="col" className={s.num}>{lang === "de" ? "Dokumente mit Kennzeichen beim Modell" : "Documents with an identifier at the model"}</th>
              <th scope="col" className={s.num}>{lang === "de" ? "Beleg-Prüfung richtig" : "Verifier correct"}</th>
              <th scope="col" className={s.num}>{lang === "de" ? "Fälschlich belegt" : "Wrongly grounded"}</th>
              <th scope="col" className={s.num}>{lang === "de" ? "Injektionen erkannt" : "Injections caught"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, r]) => (
              <tr key={name}>
                <th scope="row">
                  {name}{" "}
                  {r.rescored_because ? (
                    <Chip tone="neutral">{lang === "de" ? "neu bewertet" : "rescored"}</Chip>
                  ) : (
                    <Chip tone="neutral">{lang === "de" ? "erster Lauf" : "first run"}</Chip>
                  )}
                </th>
                <td className={s.num}>{r.pii ? percent(r.pii.listed_recall) : "–"}</td>
                <td className={s.num}>{r.pii ? `${r.pii.documents_with_listed_identifier_reaching_model} / ${r.pii.documents}` : "–"}</td>
                <td className={s.num}>{r.grounding ? percent(r.grounding.accuracy) : "–"}</td>
                <td className={s.num}>{r.grounding ? `${r.grounding.wrongly_grounded} / ${r.grounding.items}` : "–"}</td>
                <td className={s.num}>{r.guards?.injection ? percent(r.guards.injection.recall, 0) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
