import { motion } from "framer-motion";
import { useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { Skeleton } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/States";
import { Chip } from "@/components/StatusChip";
import { useCan } from "@/features/session/useMe";
import { date } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { CaseSummary } from "@/lib/types";
import { motion as m } from "@/theme/tokens";
import { useCases, useImportCase } from "./api";
import s from "./CasesPage.module.css";

export function CasesPage() {
  const { t } = useI18n();
  const cases = useCases();
  const canImport = useCan("cases.import");
  const imp = useImportCase();
  const navigate = useNavigate();
  const file = useRef<HTMLInputElement>(null);

  const importButton = canImport && (
    <>
      <input
        ref={file}
        type="file"
        accept="application/json,application/fhir+json,.json"
        className="visually-hidden"
        aria-label={t("cases.import")}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) imp.mutate(f, { onSuccess: (r) => navigate(`/cases/${r.case_id}`) });
          e.target.value = "";
        }}
      />
      <Button variant="secondary" busy={imp.isPending} onClick={() => file.current?.click()}>
        {imp.isPending ? t("cases.importing") : t("cases.import")}
      </Button>
    </>
  );

  return (
    <div className={s.page}>
      <header className={s.head}>
        <div>
          <h1>{t("cases.title")}</h1>
          <p className={s.lead}>{t("cases.lead")}</p>
        </div>
        {importButton}
      </header>
      {imp.isError && <ErrorState error={imp.error} compact />}

      {cases.isPending && <CasesSkeleton />}
      {cases.isError && <ErrorState error={cases.error} onRetry={() => void cases.refetch()} />}
      {cases.data?.length === 0 && <EmptyState title={t("cases.empty.title")} body={t("cases.empty.body")} />}
      {cases.data && cases.data.length > 0 && <CaseTable rows={cases.data} />}
    </div>
  );
}

function CaseTable({ rows }: { rows: CaseSummary[] }) {
  const { t, lang } = useI18n();
  return (
    <table className={s.table}>
      <thead>
        <tr>
          <th scope="col">{t("cases.col.case")}</th>
          <th scope="col">{t("cases.col.asof")}</th>
          <th scope="col" className={s.num}>
            {t("cases.col.docs")}
          </th>
          <th scope="col">{t("cases.col.draft")}</th>
          <th scope="col" className={s.num}>
            {t("cases.col.open")}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c, i) => (
          <motion.tr
            key={c.id}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: m.reveal.duration, delay: Math.min(i, 12) * m.reveal.stagger, ease: m.ease }}
          >
            <th scope="row">
              <Link to={`/cases/${c.id}`} className={s.caseLink}>
                {c.external_ref ?? c.id}
              </Link>
            </th>
            <td>{date(c.as_of, lang)}</td>
            <td className={s.num}>
              {c.documents}
              {c.blocked > 0 && (
                <span className={s.blocked}>
                  {" "}
                  <Chip tone="alert">{t("cases.blocked", { n: c.blocked })}</Chip>
                </span>
              )}
            </td>
            <td>
              {!c.draft_id && <span className={s.muted}>{t("cases.nodraft")}</span>}
              {c.draft_status === "released" && <Chip tone="ready">{t("cases.released")}</Chip>}
              {c.draft_status === "draft" && (
                <span className={s.draftCell}>
                  <Chip tone="neutral">{t("cases.inreview")}</Chip>
                  {(c.flagged ?? 0) > 0 && <Chip tone="review">{t("cases.flagged", { n: c.flagged ?? 0 })}</Chip>}
                </span>
              )}
            </td>
            <td className={s.num}>{c.draft_status === "draft" ? c.pending : ""}</td>
          </motion.tr>
        ))}
      </tbody>
    </table>
  );
}

function CasesSkeleton() {
  const { t } = useI18n();
  return (
    <div className={s.skeleton} role="status" aria-label={t("state.loading")}>
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className={s.skelRow}>
          <Skeleton width="9rem" />
          <Skeleton width="5rem" />
          <Skeleton width="2rem" />
          <Skeleton width="7rem" height="1.25em" radius="999px" />
          <Skeleton width="2rem" />
        </div>
      ))}
    </div>
  );
}
