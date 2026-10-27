import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Button } from "./Button";
import s from "./States.module.css";

/** What went wrong, in the server's words, and a way to try again when trying again can help. */
export function ErrorState({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const { t } = useI18n();
  const message = error instanceof Error ? error.message : String(error);
  const status = error instanceof ApiError ? error.status : undefined;
  return (
    <div className={compact ? s.compact : s.box} role="alert">
      <div>
        <p className={s.title}>{t("state.error")}</p>
        <p className={s.body}>
          {message}
          {status ? <span className={s.code}> ({status})</span> : null}
        </p>
      </div>
      {onRetry && (
        <Button onClick={onRetry} variant="secondary">
          {t("state.retry")}
        </Button>
      )}
    </div>
  );
}

/** An empty screen says what belongs here and how to get it there. */
export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className={s.empty}>
      <svg className={s.mark} viewBox="0 0 48 48" aria-hidden>
        <rect x="9" y="6" width="30" height="36" rx="3" />
        <path d="M15 16h18M15 23h18M15 30h10" />
      </svg>
      <p className={s.title}>{title}</p>
      <p className={s.body}>{body}</p>
      {action}
    </div>
  );
}
