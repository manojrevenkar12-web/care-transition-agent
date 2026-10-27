import type { ReactNode } from "react";
import s from "./Panel.module.css";

export function Panel({ title, aside, children, id }: { title: string; aside?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className={s.panel} aria-labelledby={id}>
      <header className={s.head}>
        <h2 id={id}>{title}</h2>
        {aside}
      </header>
      <div className={s.body}>{children}</div>
    </section>
  );
}

/** A labelled value bar: magnitude in one hue, the number always printed beside it. */
export function Bar({
  value,
  max,
  label,
  display,
  tone = "primary",
  marker,
}: {
  value: number;
  max: number;
  label: string;
  display: string;
  tone?: "primary" | "muted";
  marker?: { at: number; label: string };
}) {
  const pct = max > 0 ? Math.max(0, Math.min(1, value / max)) * 100 : 0;
  return (
    <div className={s.barRow}>
      <span className={s.barLabel}>{label}</span>
      <span className={s.track} role="img" aria-label={`${label}: ${display}`}>
        <span className={`${s.fill} ${tone === "muted" ? s.muted : ""}`} style={{ width: `${pct}%` }} />
        {marker && (
          <span className={s.marker} style={{ left: `${(marker.at / max) * 100}%` }} title={marker.label} aria-hidden />
        )}
      </span>
      <span className={s.barValue}>{display}</span>
    </div>
  );
}
