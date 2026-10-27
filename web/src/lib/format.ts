import type { Lang } from "./i18n";

const locale = (lang: Lang) => (lang === "de" ? "de-DE" : "en-GB");

export function date(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return d.toLocaleDateString(locale(lang), { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function dateTime(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(locale(lang), {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function percent(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  return `${(x * 100).toFixed(digits)} %`;
}

export function number(x: number | null | undefined, lang: Lang, digits = 0): string {
  if (x === null || x === undefined) return "–";
  return x.toLocaleString(locale(lang), { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function signed(x: number, digits = 3): string {
  return `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(digits)}`;
}

/** A value as the reviewer reads it: option labels for enums, Ja/Nein for booleans. */
export function valueLabel(value: unknown, label: string, lang: Lang): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return date(value, lang);
  if (label) return label;
  if (typeof value === "boolean") return value ? (lang === "de" ? "Ja" : "Yes") : lang === "de" ? "Nein" : "No";
  return String(value);
}
