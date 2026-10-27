import { motion, useReducedMotion } from "framer-motion";
import { Fragment, useEffect, useMemo, useRef } from "react";
import { dateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { CaseDocument, Evidence } from "@/lib/types";
import { motion as m } from "@/theme/tokens";
import { codePointToUnit, segments, toOriginal, type Mark } from "./highlight";
import s from "./DocumentPane.module.css";

export type View = "original" | "pseudo";

export interface Focus {
  key: string;
  evidence: Evidence[];
  counter: Evidence[];
}

function spanOf(e: Evidence, doc: CaseDocument, view: View): [number, number] | null {
  if (e.start < 0) return null;
  if (view === "pseudo") return [e.start, e.end];
  if (e.orig_start !== undefined && e.orig_end !== undefined) return [e.orig_start, e.orig_end];
  return toOriginal(e.start, e.end, doc.replacements);
}

export function marksFor(doc: CaseDocument, view: View, focus: Focus | null): Mark[] {
  const text = view === "original" ? doc.text : doc.pseudo;
  const unit = codePointToUnit(text);
  const out: Mark[] = [];
  const push = (a: number, b: number, kind: Mark["kind"], extra: Partial<Mark> = {}) =>
    out.push({ start: unit(a), end: unit(b), kind, ...extra });
  for (const r of doc.replacements) {
    if (view === "pseudo") push(r.out_start, r.out_end, "tag", { title: r.kind });
    else push(r.start, r.end, "tag", { title: r.tag });
  }
  for (const [a, b] of doc.injection_spans) {
    const [x, y] = view === "pseudo" ? [a, b] : toOriginal(a, b, doc.replacements);
    push(x, y, "injection");
  }
  if (focus) {
    focus.counter.filter((e) => e.doc_id === doc.id).forEach((e, i) => {
      const sp = spanOf(e, doc, view);
      if (sp) push(sp[0], sp[1], "counter", { id: `c${i}` });
    });
    focus.evidence.filter((e) => e.doc_id === doc.id).forEach((e, i) => {
      const sp = spanOf(e, doc, view);
      if (sp) push(sp[0], sp[1], "evidence", { id: `e${i}` });
    });
  }
  return out;
}

export function DocumentPane({
  docs,
  activeId,
  onSelect,
  view,
  onView,
  focus,
}: {
  docs: CaseDocument[];
  activeId: string;
  onSelect: (id: string) => void;
  view: View;
  onView: (v: View) => void;
  focus: Focus | null;
}) {
  const { t, lang } = useI18n();
  const doc = docs.find((d) => d.id === activeId) ?? docs[0];
  const reduce = useReducedMotion();
  const firstMark = useRef<HTMLElement | null>(null);
  const withEvidence = useMemo(
    () => new Set([...(focus?.evidence ?? []), ...(focus?.counter ?? [])].map((e) => e.doc_id)),
    [focus],
  );

  const segs = useMemo(() => {
    if (!doc) return [];
    return segments(view === "original" ? doc.text : doc.pseudo, marksFor(doc, view, focus));
  }, [doc, view, focus]);

  useEffect(() => {
    firstMark.current?.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  }, [focus?.key, activeId, view, reduce]);

  if (!doc) return null;
  firstMark.current = null;
  let firstSet = false;

  return (
    <section className={s.pane} aria-label={t("review.sources")}>
      <div className={s.toolbar}>
        <div className={s.tabs} role="tablist" aria-label={t("review.sources")}>
          {docs.map((d) => (
            <button
              key={d.id}
              role="tab"
              aria-selected={d.id === doc.id}
              className={s.tab}
              onClick={() => onSelect(d.id)}
            >
              <span className={s.tabTitle}>
                {d.title}
                {withEvidence.has(d.id) && <span className={s.dot} aria-label={t("review.evidence")} />}
              </span>
              <span className={s.tabMeta}>{dateTime(d.authored_at, lang)}</span>
            </button>
          ))}
        </div>
        <div className={s.views} role="radiogroup" aria-label={t("review.view.pseudo")}>
          {(["original", "pseudo"] as const).map((v) => (
            <button key={v} role="radio" aria-checked={view === v} className={s.view} onClick={() => onView(v)}>
              {t(v === "original" ? "review.view.original" : "review.view.pseudo")}
            </button>
          ))}
        </div>
      </div>

      {view === "pseudo" && <p className={s.hint}>{t("review.view.hint")}</p>}
      {doc.blocked && (
        <p className={s.blocked} role="note">
          {t("review.blockeddoc")}
        </p>
      )}

      <article className={s.paper} role="tabpanel" lang="de">
        <header className={s.docHead}>
          <span>{doc.title}</span>
          <span>
            {doc.author_role ? `${doc.author_role}, ` : ""}
            {dateTime(doc.authored_at, lang)}
          </span>
        </header>
        <div className={s.text}>
          {segs.map((seg) => {
            const kinds = new Set(seg.marks.map((x) => x.kind));
            const isEvidence = kinds.has("evidence");
            const cls = [
              kinds.has("tag") && s.tag,
              kinds.has("injection") && s.injection,
              kinds.has("counter") && s.counter,
            ]
              .filter(Boolean)
              .join(" ");
            const title = seg.marks.find((x) => x.title)?.title;
            const injectionTitle = kinds.has("injection") ? t("review.injection") : undefined;
            const refFor = (el: HTMLElement | null) => {
              if (el && !firstSet && (isEvidence || kinds.has("counter"))) {
                firstMark.current = el;
                firstSet = true;
              }
            };
            if (isEvidence) {
              return (
                <motion.mark
                  key={`${focus?.key}-${seg.start}-${view}`}
                  ref={refFor}
                  className={`${s.marker} ${cls}`}
                  title={title ?? injectionTitle}
                  initial={{ backgroundSize: "0% 100%" }}
                  animate={{ backgroundSize: "100% 100%" }}
                  transition={{ duration: m.marker.duration, delay: m.marker.delay, ease: m.ease }}
                >
                  {seg.text}
                </motion.mark>
              );
            }
            if (cls) {
              return (
                <span key={seg.start} ref={refFor} className={cls} title={title ?? injectionTitle}>
                  {seg.text}
                </span>
              );
            }
            return <Fragment key={seg.start}>{seg.text}</Fragment>;
          })}
        </div>
      </article>
    </section>
  );
}
