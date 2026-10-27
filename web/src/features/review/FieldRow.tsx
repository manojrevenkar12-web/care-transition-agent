import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/Button";
import { ErrorState } from "@/components/States";
import { StatusChip } from "@/components/StatusChip";
import { valueLabel } from "@/lib/format";
import { REASONS, REVIEW, useI18n } from "@/lib/i18n";
import type { CaseDocument, DraftField, Evidence } from "@/lib/types";
import { motion as m } from "@/theme/tokens";
import type { ReviewInput } from "./api";
import { FieldEditor } from "./FieldEditor";
import { toOriginal } from "./highlight";
import s from "./FieldRow.module.css";

/** The words a clinician reads for a piece of evidence: the original text where it can be located. */
function evidenceText(e: Evidence, docs: CaseDocument[] | undefined): string {
  const d = docs?.find((x) => x.id === e.doc_id);
  if (d && e.start >= 0) {
    const [a, b] = e.orig_start !== undefined && e.orig_end !== undefined ? [e.orig_start, e.orig_end] : toOriginal(e.start, e.end, d.replacements);
    return Array.from(d.text).slice(a, b).join("");
  }
  return e.quote ?? "";
}

export function FieldRow({
  field,
  open,
  onToggle,
  onShowEvidence,
  docs,
  canReview,
  readOnly,
  onReview,
  busy,
  error,
}: {
  field: DraftField;
  open: boolean;
  onToggle: () => void;
  onShowEvidence: (e: Evidence) => void;
  docs: CaseDocument[] | undefined;
  canReview: boolean;
  readOnly: boolean;
  onReview: (r: ReviewInput) => void;
  busy: boolean;
  error: unknown;
}) {
  const { t, lang } = useI18n();
  const [editing, setEditing] = useState(false);
  const openedAt = useRef<number>(0);
  useEffect(() => {
    openedAt.current = open ? Date.now() : 0;
  }, [open]);

  const reviewed = field.review !== "pending";
  const shown = reviewed ? field.final_value : field.agent_value;
  const shownLabel = reviewed ? field.final_label : field.agent_label;
  const text = valueLabel(shown, shownLabel, lang);
  const seconds = () => (openedAt.current ? Math.round((Date.now() - openedAt.current) / 1000) : undefined);
  const act = (action: ReviewInput["action"], value?: unknown) => {
    onReview({ field: field.field, action, value, seconds: seconds() });
    setEditing(false);
  };
  const panelId = `field-${field.field}`;

  return (
    <li className={`${s.row} ${open ? s.open : ""} ${reviewed ? s.done : ""}`} data-field={field.field}>
      <button className={s.summary} onClick={onToggle} aria-expanded={open} aria-controls={panelId}>
        <span className={s.label}>
          {field.label[lang]}
          {field.required && field.review === "pending" && <span className={s.req}>{t("review.required")}</span>}
        </span>
        <span className={`${s.value} ${field.type === "summary" ? s.summaryValue : ""}`}>
          {text || <span className={s.none}>{"—"}</span>}
        </span>
        <span className={s.state}>
          {reviewed ? (
            <span className={`${s.reviewState} ${s[field.review]}`}>{REVIEW[field.review]?.[lang]}</span>
          ) : (
            <StatusChip status={field.agent_status} />
          )}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={panelId}
            className={s.panel}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: m.expand.duration, ease: m.ease }}
          >
            <div className={s.panelInner}>
              {reviewed && <StatusChip status={field.agent_status} />}
              {field.reason && field.agent_status !== "grounded" && (
                <p className={s.reason}>{lang === "de" ? (REASONS[field.reason] ?? field.reason) : field.reason}</p>
              )}

              {field.evidence.length > 0 ? (
                <div className={s.quotes}>
                  <p className={s.quotesTitle}>{t("review.evidence")}</p>
                  {field.evidence.map((e, i) => (
                    <button key={i} className={s.quote} onClick={() => onShowEvidence(e)}>
                      <span className={s.quoteText}>{evidenceText(e, docs) || e.quote}</span>
                      <span className={s.quoteDoc}>{docs?.find((d) => d.id === e.doc_id)?.title ?? e.doc_id}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className={s.reason}>{t("review.noevidence")}</p>
              )}

              {field.counter.length > 0 && (
                <div className={s.quotes}>
                  <p className={`${s.quotesTitle} ${s.counterTitle}`}>{t("review.counter")}</p>
                  {field.counter.map((e, i) => (
                    <button key={i} className={`${s.quote} ${s.counterQuote}`} onClick={() => onShowEvidence(e)}>
                      <span className={s.quoteText}>{evidenceText(e, docs) || e.quote}</span>
                      <span className={s.quoteDoc}>{docs?.find((d) => d.id === e.doc_id)?.title ?? e.doc_id}</span>
                    </button>
                  ))}
                </div>
              )}

              {field.question && (
                <p className={s.question}>
                  <span className={s.quotesTitle}>{t("review.question")}</span> {field.question}
                </p>
              )}

              {error ? <ErrorState error={error} compact /> : null}

              {canReview && !readOnly && !editing && (
                <div className={s.actions}>
                  {field.agent_value !== null && field.agent_value !== undefined && (
                    <Button variant="primary" busy={busy} onClick={() => act("accept")}>
                      {t("review.accept")}
                    </Button>
                  )}
                  <Button variant="secondary" onClick={() => setEditing(true)} disabled={busy}>
                    {field.agent_value === null || field.agent_value === undefined ? t("review.answer") : t("review.edit")}
                  </Button>
                  {field.agent_value !== null && field.agent_value !== undefined && (
                    <Button variant="danger" onClick={() => act("reject")} disabled={busy}>
                      {t("review.reject")}
                    </Button>
                  )}
                  {field.reviewed_by && <span className={s.by}>{t("review.by", { who: field.reviewed_by })}</span>}
                </div>
              )}
              {editing && (
                <FieldEditor
                  field={field}
                  initial={shown}
                  busy={busy}
                  onCancel={() => setEditing(false)}
                  onSave={(v) => act(field.agent_value === null || field.agent_value === undefined ? "answer" : "edit", v)}
                />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}
