import { motion } from "framer-motion";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/Button";
import { api, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { session } from "@/lib/session";
import type { Me } from "@/lib/types";
import { motion as m } from "@/theme/tokens";
import s from "./SignIn.module.css";

interface Demo {
  token: string;
  label: string;
}

/** Demo tokens are injected at build time for development only (VITE_DEMO_TOKENS). */
function demoTokens(): Demo[] {
  try {
    return JSON.parse(import.meta.env.VITE_DEMO_TOKENS ?? "[]") as Demo[];
  } catch {
    return [];
  }
}

export function SignIn() {
  const { t, lang, setLang } = useI18n();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const demos = demoTokens();

  async function signIn(value: string) {
    setBusy(true);
    setError(null);
    session.set(value.trim());
    try {
      await api<Me>("/api/me");
    } catch (e) {
      session.clear();
      setError(e instanceof ApiError && e.status === 401 ? t("signin.failed") : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (token.trim()) void signIn(token);
  }

  return (
    <div className={s.page}>
      <motion.section
        className={s.card}
        initial={{ opacity: 0, y: m.reveal.distance }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: m.reveal.duration, ease: m.ease }}
      >
        <div className={s.head}>
          <h1>{t("signin.title")}</h1>
          <button className={s.lang} onClick={() => setLang(lang === "de" ? "en" : "de")}>
            {t("nav.language")}
          </button>
        </div>
        <p className={s.lead}>{t("signin.lead")}</p>
        <form onSubmit={submit} className={s.form}>
          <label htmlFor="token">{t("signin.token")}</label>
          <input
            id="token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            aria-invalid={!!error}
            aria-describedby={error ? "signin-error" : undefined}
          />
          {error && (
            <p id="signin-error" className={s.error} role="alert">
              {error}
            </p>
          )}
          <Button variant="primary" type="submit" busy={busy} disabled={!token.trim()}>
            {t("signin.submit")}
          </Button>
        </form>
        {demos.length > 0 && (
          <div className={s.demos}>
            <p className={s.demoTitle}>{t("signin.demo")}</p>
            {demos.map((d) => (
              <button key={d.token} className={s.demo} onClick={() => void signIn(d.token)} disabled={busy}>
                {d.label}
              </button>
            ))}
          </div>
        )}
      </motion.section>
    </div>
  );
}
