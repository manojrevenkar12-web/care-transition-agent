import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useMe, useSignOut } from "@/features/session/useMe";
import { useI18n } from "@/lib/i18n";
import s from "./Shell.module.css";

export function Shell({ children }: { children: ReactNode }) {
  const { t, lang, setLang } = useI18n();
  const me = useMe();
  const signOut = useSignOut();
  const canQuality = me.data?.permissions.includes("quality.read");
  return (
    <div className={s.shell}>
      <a className={s.skip} href="#main">
        {lang === "de" ? "Zum Inhalt" : "Skip to content"}
      </a>
      <header className={s.bar}>
        <span className={s.brand}>
          <svg viewBox="0 0 32 32" aria-hidden className={s.logo}>
            <rect width="32" height="32" rx="7" />
            <path d="M9 17l5 5 9-12" />
          </svg>
          {t("app.name")}
        </span>
        <nav className={s.nav} aria-label={lang === "de" ? "Hauptnavigation" : "Main"}>
          <NavLink to="/" end className={({ isActive }) => (isActive ? s.active : undefined)}>
            {t("nav.cases")}
          </NavLink>
          {canQuality && (
            <NavLink to="/quality" className={({ isActive }) => (isActive ? s.active : undefined)}>
              {t("nav.quality")}
            </NavLink>
          )}
        </nav>
        <div className={s.right}>
          {me.data && (
            <span className={s.who}>
              <span>{me.data.user}</span>
              <span className={s.meta}>
                {t(`role.${me.data.role}`)}, {me.data.tenant_name}
              </span>
            </span>
          )}
          <button className={s.link} onClick={() => setLang(lang === "de" ? "en" : "de")} lang={lang === "de" ? "en" : "de"}>
            {t("nav.language")}
          </button>
          <button className={s.link} onClick={signOut}>
            {t("nav.signout")}
          </button>
        </div>
      </header>
      <main id="main" className={s.main}>
        {children}
      </main>
    </div>
  );
}
