import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/Button";
import { SkeletonLines } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/States";
import { useI18n } from "@/lib/i18n";
import { limits, motion as m } from "@/theme/tokens";
import { useAsk, useChat, useFeedback } from "./api";
import s from "./ChatDrawer.module.css";

export function ChatDrawer({ caseId, open, onClose }: { caseId: string; open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const chat = useChat(caseId, open);
  const ask = useAsk(caseId);
  const feedback = useFeedback(caseId);
  const [message, setMessage] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [chat.data?.length, ask.isPending]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = message.trim();
    if (!q) return;
    ask.mutate(q, { onSuccess: () => setMessage("") });
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          className={s.drawer}
          role="dialog"
          aria-modal="false"
          aria-labelledby="chat-title"
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
          transition={{ duration: m.drawer.duration, ease: m.ease }}
        >
          <header className={s.head}>
            <div>
              <h2 id="chat-title">{t("chat.title")}</h2>
              <p className={s.lead}>{t("chat.lead")}</p>
            </div>
            <button className={s.close} onClick={onClose} aria-label={t("review.cancel")}>
              <svg viewBox="0 0 20 20" aria-hidden>
                <path d="M5 5l10 10M15 5L5 15" />
              </svg>
            </button>
          </header>

          <div className={s.log} aria-live="polite">
            {chat.isPending && <SkeletonLines lines={4} label={t("state.loading")} />}
            {chat.isError && <ErrorState error={chat.error} onRetry={() => void chat.refetch()} compact />}
            {chat.data?.length === 0 && !ask.isPending && <EmptyState title={t("chat.empty")} body={t("chat.lead")} />}
            {chat.data?.map((msg) => (
              <div key={msg.id} className={msg.role === "user" ? s.user : s.assistant}>
                <p className={s.text}>{msg.text}</p>
                {msg.role === "assistant" && msg.citations.length > 0 && (
                  <ul className={s.cites}>
                    {msg.citations.map((c, i) => (
                      <li key={i} className={c.found === false ? s.missing : undefined}>
                        {c.quote}
                      </li>
                    ))}
                  </ul>
                )}
                {msg.role === "assistant" && msg.status === "unverified" && (
                  <p className={s.warn}>{t("chat.unverified")}</p>
                )}
                {msg.role === "assistant" && msg.status !== "refused" && (
                  <div className={s.fb}>
                    {(["helpful", "wrong"] as const).map((f) => (
                      <button
                        key={f}
                        className={s.fbBtn}
                        aria-pressed={msg.feedback === f}
                        onClick={() => feedback.mutate({ id: msg.id, feedback: f })}
                      >
                        {t(f === "helpful" ? "chat.helpful" : "chat.wrong")}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {ask.isPending && (
              <div className={s.assistant}>
                <SkeletonLines lines={2} label={t("state.loading")} />
              </div>
            )}
            {ask.isError && <ErrorState error={ask.error} compact />}
            <div ref={end} />
          </div>

          <form className={s.form} onSubmit={submit}>
            <label htmlFor="chat-input" className="visually-hidden">
              {t("chat.title")}
            </label>
            <textarea
              id="chat-input"
              ref={input}
              rows={2}
              maxLength={limits.chatMessageChars}
              placeholder={t("chat.placeholder")}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) submit(e);
              }}
            />
            <Button variant="primary" type="submit" busy={ask.isPending} disabled={!message.trim()}>
              {t("chat.send")}
            </Button>
          </form>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
