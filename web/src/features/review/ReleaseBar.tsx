import { motion } from "framer-motion";
import { Button } from "@/components/Button";
import { ErrorState } from "@/components/States";
import { dateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { Draft } from "@/lib/types";
import { motion as m } from "@/theme/tokens";
import s from "./ReleaseBar.module.css";

/** Release is the clinician's signature. The bar says what still stands in the way, and nothing else. */
export function ReleaseBar({
  draft,
  canRelease,
  onRelease,
  releasing,
  error,
  onJump,
}: {
  draft: Draft;
  canRelease: boolean;
  onRelease: () => void;
  releasing: boolean;
  error: unknown;
  onJump: (field: string) => void;
}) {
  const { t, lang } = useI18n();
  const released = draft.status === "released";
  const open = draft.blocking.filter((b) => b.field);
  const next = open[0]?.field;

  return (
    <motion.div
      className={`${s.bar} ${released ? s.released : ""}`}
      initial={{ y: "100%" }}
      animate={{ y: 0 }}
      transition={{ duration: m.drawer.duration, ease: m.ease }}
    >
      <div className={s.inner}>
        {released ? (
          <p className={s.status}>
            <svg viewBox="0 0 20 20" className={s.check} aria-hidden>
              <path d="M4 10.5l4 4 8-9" />
            </svg>
            {t("review.released", { date: dateTime(draft.released_at, lang), who: draft.released_by ?? "" })}
          </p>
        ) : (
          <>
            <div className={s.status} aria-live="polite">
              <span className={s.count}>{open.length}</span>
              <span>{open.length ? t("review.release.blocked", { n: open.length }) : t("review.release.ready")}</span>
              {next && (
                <Button variant="quiet" onClick={() => onJump(next)}>
                  {t("review.jump")}
                </Button>
              )}
            </div>
            <div className={s.actions}>
              {error ? <ErrorState error={error} compact /> : null}
              {!canRelease && <span className={s.note}>{t("review.release.onlyclinician")}</span>}
              <Button variant="primary" onClick={onRelease} busy={releasing} disabled={!canRelease || open.length > 0}>
                {releasing ? t("review.releasing") : t("review.release")}
              </Button>
            </div>
          </>
        )}
      </div>
    </motion.div>
  );
}
