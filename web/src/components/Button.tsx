import type { ButtonHTMLAttributes, ReactNode } from "react";
import s from "./Button.module.css";

type Variant = "primary" | "secondary" | "quiet" | "danger";

export function Button({
  variant = "secondary",
  busy = false,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean; children: ReactNode }) {
  return (
    <button
      {...rest}
      className={[s.button, s[variant], className].filter(Boolean).join(" ")}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
    >
      {busy && <span className={s.spinner} aria-hidden />}
      {children}
    </button>
  );
}
