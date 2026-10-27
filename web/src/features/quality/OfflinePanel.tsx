import { Bar, Panel } from "@/components/Panel";
import { Chip } from "@/components/StatusChip";
import { number, percent, signed } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { OfflineMetrics, OfflineReport } from "@/lib/types";
import s from "./Quality.module.css";

const ROWS: Array<{ key: keyof OfflineMetrics; de: string; en: string; fmt: "pct" | "int" | "num" }> = [
  { key: "field_accuracy", de: "Feldgenauigkeit", en: "Field accuracy", fmt: "pct" },
  { key: "major_wrong_ready", de: "Falsch, aber als belegt gezeigt (schwer)", en: "Wrong but shown as grounded (major)", fmt: "int" },
  { key: "ready_share", de: "Als belegt gezeigt", en: "Shown as grounded", fmt: "pct" },
  { key: "review_load", de: "Prüflast (markiert, aber richtig)", en: "Review load (flagged but right)", fmt: "pct" },
  { key: "tokens_per_case", de: "Tokens pro Fall", en: "Tokens per case", fmt: "int" },
  { key: "model_calls_per_case", de: "Modellaufrufe pro Fall", en: "Model calls per case", fmt: "num" },
];

const CREOLA: Record<string, { de: string; en: string }> = {
  fabrication: { de: "Erfunden", en: "Fabrication" },
  negation: { de: "Verneinung übersehen", en: "Negation" },
  contextual: { de: "Falscher Kontext", en: "Contextual" },
  omission: { de: "Ausgelassen", en: "Omission" },
  other: { de: "Sonstige", en: "Other" },
};

export function OfflinePanel({ name, report }: { name: string; report: OfflineReport }) {
  const { t, lang } = useI18n();
  const c = report.metrics;
  const b = report.baseline_metrics;
  const fmt = (v: number, f: "pct" | "int" | "num") => (f === "pct" ? percent(v) : number(v, lang, f === "num" ? 2 : 0));
  const kinds = Object.keys(CREOLA).filter((k) => (c.creola[k] ?? 0) + (b?.creola[k] ?? 0) > 0);
  const maxErr = Math.max(1, ...kinds.flatMap((k) => [c.creola[k] ?? 0, b?.creola[k] ?? 0]));

  return (
    <Panel
      id={`offline-${name}`}
      title={`${report.candidate}${report.baseline ? (lang === "de" ? " gegen " : " vs ") + report.baseline : ""}`}
      aside={
        report.gate ? (
          <Chip tone={report.gate.passed ? "ready" : "alert"}>
            {report.gate.passed ? (lang === "de" ? "Gate bestanden" : "Gate passed") : lang === "de" ? "Gate nicht bestanden" : "Gate failed"}
          </Chip>
        ) : undefined
      }
    >
      <p className={s.note}>
        {lang === "de"
          ? `Goldstandard „${report.set}“, ${c.cases} Fälle, ${c.fields} Felder.`
          : `Golden set "${report.set}", ${c.cases} cases, ${c.fields} fields.`}
        {report.paired_accuracy &&
          (lang === "de" ? " Gepaarter Unterschied der Genauigkeit " : " Paired accuracy difference ") +
            `${signed(report.paired_accuracy.delta)} (95 % CI ${signed(report.paired_accuracy.low)} … ${signed(report.paired_accuracy.high)}).`}
      </p>
      <table className={s.table}>
        <thead>
          <tr>
            <th scope="col">{lang === "de" ? "Kennzahl" : "Metric"}</th>
            <th scope="col" className={s.num}>
              {report.candidate}
            </th>
            {b && (
              <th scope="col" className={s.num}>
                {report.baseline}
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r[lang]}</th>
              <td className={s.num}>{fmt(c[r.key] as number, r.fmt)}</td>
              {b && <td className={s.num}>{fmt(b[r.key] as number, r.fmt)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {kinds.length > 0 && (
        <div className={s.bars}>
          <p className={s.subhead}>{lang === "de" ? "Fehlerarten nach CREOLA" : "Error types (CREOLA)"}</p>
          {kinds.map((k) => (
            <div key={k} className={s.pair}>
              <Bar label={`${CREOLA[k]![lang]}, ${report.candidate}`} value={c.creola[k] ?? 0} max={maxErr} display={String(c.creola[k] ?? 0)} />
              {b && (
                <Bar
                  label={`${CREOLA[k]![lang]}, ${report.baseline}`}
                  value={b.creola[k] ?? 0}
                  max={maxErr}
                  display={String(b.creola[k] ?? 0)}
                  tone="muted"
                />
              )}
            </div>
          ))}
        </div>
      )}
      {report.gate && (
        <ul className={s.checks}>
          {report.gate.checks.map((ch) => (
            <li key={ch.check} className={ch.passed ? s.pass : s.fail}>
              <span>{ch.passed ? t("review.yes") : t("review.no")}</span> {ch.check}
              <span className={s.checkValue}>{String(ch.value)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
