import type { Replacement } from "@/lib/types";

/** Offsets from the server count Unicode code points (Python); JavaScript strings count UTF-16 units. */
export function codePointToUnit(text: string): (cp: number) => number {
  if (!/[\uD800-\uDFFF]/.test(text)) return (cp) => cp;
  const units: number[] = [];
  let u = 0;
  for (const ch of text) {
    units.push(u);
    u += ch.length;
  }
  units.push(u);
  return (cp) => units[Math.max(0, Math.min(cp, units.length - 1))] ?? u;
}

/** Map a span in the pseudonymised text to the original text (mirrors cta.gateway.to_original_span). */
export function toOriginal(start: number, end: number, replacements: Replacement[]): [number, number] {
  const reps = [...replacements].sort((a, b) => a.out_start - b.out_start);
  const one = (p: number, isEnd: boolean): number => {
    let shift = 0;
    for (const r of reps) {
      if (p >= r.out_end) {
        shift += r.end - r.start - (r.out_end - r.out_start);
        continue;
      }
      if (r.out_start < p && p < r.out_end) return isEnd ? r.end : r.start;
      break;
    }
    return p + shift;
  };
  return [one(start, false), one(end, true)];
}

export type MarkKind = "evidence" | "counter" | "tag" | "injection";

export interface Mark {
  start: number;
  end: number;
  kind: MarkKind;
  /** a stable id so the view can scroll to the first evidence mark */
  id?: string;
  title?: string;
}

export interface Segment {
  text: string;
  start: number;
  marks: Mark[];
}

/** Cut a text into segments so that each segment carries every mark that covers it. Marks may overlap. */
export function segments(text: string, marks: Mark[]): Segment[] {
  const valid = marks.filter((m) => m.end > m.start && m.start >= 0 && m.start < text.length);
  const cuts = new Set<number>([0, text.length]);
  for (const m of valid) {
    cuts.add(m.start);
    cuts.add(Math.min(m.end, text.length));
  }
  const points = [...cuts].sort((a, b) => a - b);
  const out: Segment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i]!;
    const b = points[i + 1]!;
    if (b <= a) continue;
    out.push({ text: text.slice(a, b), start: a, marks: valid.filter((m) => m.start <= a && m.end >= b) });
  }
  return out;
}
