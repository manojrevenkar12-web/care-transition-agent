import { Bar, Panel } from "@/components/Panel";
import { Chip } from "@/components/StatusChip";
import { useI18n } from "@/lib/i18n";
import type { JudgeCriterion } from "@/lib/types";
import s from "./Quality.module.css";

const NAMES: Record<string, { de: string; en: string }> = {
  covers_needs: { de: "Deckt den Bedarf ab", en: "Covers the care needs" },
  faithful: { de: "Nur Belegtes", en: "Faithful to the documents" },
  no_identifiers: { de: "Keine Kennzeichen", en: "No identifiers" },
  no_advice: { de: "Keine Therapieempfehlung", en: "No treatment advice" },
};

/** Agreement of the LLM judge with clinicians' labels. A criterion is used only when Cohen's kappa clears the bar. */
export function JudgePanel({ judge, minKappa = 0.6 }: { judge: Record<string, JudgeCriterion>; minKappa?: number }) {
  const { t, lang } = useI18n();
  return (
    <Panel id="judge" title={t("quality.judge")}>
      <p className={s.note}>
        {lang === "de"
          ? `Cohens Kappa gegen ärztliche Bewertungen; verwendet wird ein Kriterium ab κ ≥ ${minKappa}. Der Strich markiert die Schwelle.`
          : `Cohen's kappa against clinician labels; a criterion is used from κ ≥ ${minKappa}. The line marks the threshold.`}
      </p>
      {Object.entries(judge).map(([k, c]) => (
        <div key={k} className={s.judgeRow}>
          <Bar
            label={NAMES[k]?.[lang] ?? k}
            value={Math.max(0, c.kappa)}
            max={1}
            display={`κ ${c.kappa.toFixed(2)}`}
            tone={c.trusted ? "primary" : "muted"}
            marker={{ at: minKappa, label: `κ ${minKappa}` }}
          />
          <Chip tone={c.trusted ? "ready" : "review"}>
            {c.trusted ? (lang === "de" ? "verwendet" : "in use") : lang === "de" ? "nicht verwendet" : "not used"}
          </Chip>
        </div>
      ))}
    </Panel>
  );
}
