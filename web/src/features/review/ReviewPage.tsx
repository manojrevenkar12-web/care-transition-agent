import { motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button } from "@/components/Button";
import { Skeleton, SkeletonLines } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/States";
import { useCase, useDocuments } from "@/features/cases/api";
import { useCan } from "@/features/session/useMe";
import { date, dateTime } from "@/lib/format";
import { SECTIONS, useI18n } from "@/lib/i18n";
import type { Draft, Evidence } from "@/lib/types";
import { motion as m } from "@/theme/tokens";
import { useAcceptGrounded, useDraft, useRelease, useReviewField, useRunDraft, type ReviewInput } from "./api";
import { ChatDrawer } from "./ChatDrawer";
import { DocumentPane, type Focus, type View } from "./DocumentPane";
import { FieldRow } from "./FieldRow";
import { ReleaseBar } from "./ReleaseBar";
import s from "./ReviewPage.module.css";

export function ReviewPage() {
  const { caseId = "" } = useParams();
  const { t, lang } = useI18n();
  const kase = useCase(caseId);
  const canDocs = useCan("documents.original");
  const canRun = useCan("drafts.run");
  const canChat = useCan("chat");
  const docs = useDocuments(caseId, canDocs);
  const draftId = kase.data?.drafts.find((d) => d.status === "draft" || d.status === "released")?.id;
  const draft = useDraft(draftId);
  const run = useRunDraft(caseId);
  const [chatOpen, setChatOpen] = useState(false);

  if (kase.isPending) return <ReviewSkeleton />;
  if (kase.isError) return <ErrorState error={kase.error} onRetry={() => void kase.refetch()} />;
  const c = kase.data;

  return (
    <div className={s.page}>
      <header className={s.head}>
        <div>
          <Link to="/" className={s.back}>
            {t("review.back")}
          </Link>
          <h1>
            {t("cases.col.case")} {c.external_ref || c.id}
          </h1>
          <p className={s.meta}>
            {t("review.asof", { date: date(c.as_of, lang) })}
            {draft.data &&
              `, ${t("review.draftmeta", {
                date: dateTime(draft.data.created_at, lang),
                prompt: draft.data.prompt_version,
                model: draft.data.model,
              })}`}
          </p>
        </div>
        <div className={s.headActions}>
          {canChat && (
            <Button variant="secondary" onClick={() => setChatOpen((o) => !o)} aria-expanded={chatOpen}>
              {t("chat.open")}
            </Button>
          )}
          {canRun && draftId && draft.data?.status === "draft" && (
            <Button variant="quiet" busy={run.isPending} onClick={() => run.mutate()}>
              {t("review.rerun")}
            </Button>
          )}
        </div>
      </header>

      {run.isError && <ErrorState error={run.error} onRetry={() => run.mutate()} />}

      {!draftId && !run.isPending && (
        <EmptyState
          title={t("review.nodraft.title")}
          body={t("review.nodraft.body")}
          action={
            canRun ? (
              <Button variant="primary" onClick={() => run.mutate()}>
                {t("review.run")}
              </Button>
            ) : undefined
          }
        />
      )}
      {run.isPending && <Running />}
      {draftId && !run.isPending && draft.isPending && <ReviewSkeleton inline />}
      {draft.isError && <ErrorState error={draft.error} onRetry={() => void draft.refetch()} />}
      {draft.data && !run.isPending && (
        <Workspace
          key={draft.data.id}
          draft={draft.data}
          caseId={caseId}
          docs={docs.data}
          docsError={docs.error}
          docsPending={canDocs && docs.isPending}
          onRetryDocs={() => void docs.refetch()}
        />
      )}
      {canChat && <ChatDrawer caseId={caseId} open={chatOpen} onClose={() => setChatOpen(false)} />}
    </div>
  );
}

function Workspace({
  draft,
  caseId,
  docs,
  docsError,
  docsPending,
  onRetryDocs,
}: {
  draft: Draft;
  caseId: string;
  docs: ReturnType<typeof useDocuments>["data"];
  docsError: unknown;
  docsPending: boolean;
  onRetryDocs: () => void;
}) {
  const { t, lang } = useI18n();
  const canReview = useCan("drafts.review");
  const canRelease = useCan("drafts.release");
  const review = useReviewField(draft.id);
  const acceptAll = useAcceptGrounded(draft.id);
  const release = useRelease(draft.id, caseId);
  // open the field that most needs a person: flagged with a value, then flagged, then anything still blocking
  const blockingFields = draft.fields.filter((f) => draft.blocking.some((b) => b.field === f.field));
  const firstFlagged = (
    blockingFields.find((f) => f.agent_status !== "grounded" && f.agent_value !== null) ??
    blockingFields.find((f) => f.agent_status !== "grounded") ??
    blockingFields[0]
  )?.field;
  const [openField, setOpenField] = useState<string | null>(firstFlagged ?? draft.fields[0]?.field ?? null);
  const [view, setView] = useState<View>("original");
  const [activeDoc, setActiveDoc] = useState<string>("");
  const [pendingField, setPendingField] = useState<string | null>(null);
  const readOnly = draft.status !== "draft";

  const sections = useMemo(() => {
    const out: Array<[string, Draft["fields"]]> = [];
    for (const f of draft.fields) {
      const last = out[out.length - 1];
      if (last && last[0] === f.section) last[1].push(f);
      else out.push([f.section, [f]]);
    }
    return out;
  }, [draft.fields]);

  const field = draft.fields.find((f) => f.field === openField);
  const focus: Focus | null = field ? { key: field.field, evidence: field.evidence, counter: field.counter } : null;

  // follow the open field's evidence to its document
  useEffect(() => {
    const first = field?.evidence.find((e) => e.start >= 0) ?? field?.counter.find((e) => e.start >= 0);
    if (first) setActiveDoc(first.doc_id);
  }, [field]);
  useEffect(() => {
    if (!activeDoc && docs?.[0]) setActiveDoc(docs[0].id);
  }, [docs, activeDoc]);

  const showEvidence = useCallback((e: Evidence) => setActiveDoc(e.doc_id), []);
  const jump = useCallback((f: string) => {
    setOpenField(f);
    document.querySelector(`[data-field="${f}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);
  const onReview = (r: ReviewInput) => {
    setPendingField(r.field);
    review.mutate(r, {
      onSuccess: () => {
        const next = draft.fields.find(
          (f) => f.field !== r.field && f.review === "pending" && draft.blocking.some((b) => b.field === f.field),
        );
        if (next) setOpenField(next.field);
      },
    });
  };
  const groundedPending = draft.fields.filter(
    (f) => f.review === "pending" && f.agent_status === "grounded" && f.agent_value !== null,
  ).length;

  return (
    <>
      <div className={s.workspace}>
        <section className={s.form} aria-label={t("review.profile")}>
          <div className={s.formHead}>
            <h2>{t("review.profile")}</h2>
            {canReview && !readOnly && groundedPending > 0 && (
              <Button variant="secondary" busy={acceptAll.isPending} onClick={() => acceptAll.mutate()}>
                {t("review.acceptgrounded", { n: groundedPending })}
              </Button>
            )}
          </div>
          {acceptAll.isError && <ErrorState error={acceptAll.error} compact />}
          {sections.map(([sec, fields], i) => (
            <motion.div
              key={sec}
              className={s.section}
              initial={{ opacity: 0, y: m.reveal.distance }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: m.reveal.duration, delay: i * m.reveal.stagger, ease: m.ease }}
            >
              <h3 className={s.sectionTitle}>{SECTIONS[sec]?.[lang] ?? sec}</h3>
              <ul className={s.fields}>
                {fields.map((f) => (
                  <FieldRow
                    key={f.field}
                    field={f}
                    open={openField === f.field}
                    onToggle={() => setOpenField(openField === f.field ? null : f.field)}
                    onShowEvidence={showEvidence}
                    docs={docs}
                    canReview={canReview}
                    readOnly={readOnly}
                    onReview={onReview}
                    busy={review.isPending && pendingField === f.field}
                    error={review.isError && pendingField === f.field ? review.error : null}
                  />
                ))}
              </ul>
            </motion.div>
          ))}
        </section>

        <div className={s.sources}>
          {docsPending && (
            <div className={s.docSkeleton}>
              <Skeleton width="60%" height="2.5rem" />
              <SkeletonLines lines={10} label={t("state.loading")} />
            </div>
          )}
          {docsError ? <ErrorState error={docsError} onRetry={onRetryDocs} /> : null}
          {docs && docs.length > 0 && (
            <DocumentPane
              docs={docs}
              activeId={activeDoc}
              onSelect={setActiveDoc}
              view={view}
              onView={setView}
              focus={focus}
            />
          )}
        </div>
      </div>
      <ReleaseBar
        draft={draft}
        canRelease={canRelease}
        onRelease={() => release.mutate()}
        releasing={release.isPending}
        error={release.error}
        onJump={jump}
      />
    </>
  );
}

function Running() {
  const { t } = useI18n();
  return (
    <div className={s.running} role="status">
      <span className={s.pulse} aria-hidden />
      <p>{t("review.running")}</p>
    </div>
  );
}

function ReviewSkeleton({ inline = false }: { inline?: boolean }) {
  const { t } = useI18n();
  return (
    <div className={inline ? s.workspace : s.page} role="status" aria-label={t("state.loading")}>
      {!inline && <Skeleton width="18rem" height="2rem" />}
      <div className={s.workspace}>
        <div className={s.form}>
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className={s.skelRow}>
              <Skeleton width="40%" />
              <Skeleton width="30%" />
              <Skeleton width="5rem" height="1.25em" radius="999px" />
            </div>
          ))}
        </div>
        <div className={s.docSkeleton}>
          <Skeleton width="60%" height="2.5rem" />
          <SkeletonLines lines={10} label={t("state.loading")} />
        </div>
      </div>
    </div>
  );
}
