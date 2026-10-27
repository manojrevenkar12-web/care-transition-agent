import { STATUS, useI18n, type Tone } from "@/lib/i18n";
import s from "./StatusChip.module.css";

export function Chip({ tone, children }: { tone: Tone; children: string }) {
  return <span className={`${s.chip} ${s[tone]}`}>{children}</span>;
}

/** The verifier's verdict on a field, in words; colour only repeats what the words say. */
export function StatusChip({ status }: { status: string }) {
  const { lang } = useI18n();
  const st = STATUS[status] ?? { de: status, en: status, tone: "neutral" as Tone };
  return <Chip tone={st.tone}>{st[lang]}</Chip>;
}
