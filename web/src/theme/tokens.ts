/** Motion and layout constants used from TypeScript. Colours, type and spacing live in tokens.css. */

export const motion = {
  /** the one page-load moment: profile sections settle in */
  reveal: { duration: 0.42, stagger: 0.05, distance: 10 },
  /** a field opening to show its evidence */
  expand: { duration: 0.22 },
  /** the highlighter stroke across a quote */
  marker: { duration: 0.55, delay: 0.12 },
  /** drawers and the release bar */
  drawer: { duration: 0.28 },
  ease: [0.22, 0.8, 0.24, 1] as const,
} as const;

export const query = {
  /** how long list data stays fresh before a background refetch */
  staleMs: 15_000,
  retries: 2,
} as const;

export const limits = {
  chatMessageChars: 2000,
  recentRuns: 50,
} as const;

/** contrast pairs that must meet WCAG AA (4.5:1 for text), checked in contrast.test.ts */
export const contrastPairs: Array<[fg: string, bg: string, use: string]> = [
  ["#17302f", "#f4f6f3", "ink on paper"],
  ["#4f605d", "#ffffff", "muted ink on surface"],
  ["#4f605d", "#f4f6f3", "muted ink on paper"],
  ["#ffffff", "#0f5c5a", "button text on petrol"],
  ["#23704d", "#dcefe4", "ready chip"],
  ["#8f540c", "#f7e9d2", "review chip"],
  ["#a8283d", "#f7dfe2", "alert chip"],
  ["#55626e", "#e6eaee", "neutral chip"],
  ["#17302f", "#f3dd6b", "ink on marker"],
  ["#e3ece9", "#0e1918", "dark: ink on paper"],
  ["#a3b4b0", "#142322", "dark: muted on surface"],
  ["#07201e", "#6cc0b9", "dark: button text on petrol"],
  ["#7fd0a4", "#173a2a", "dark: ready chip"],
  ["#f0b867", "#45321a", "dark: review chip"],
  ["#f2909e", "#4a1f27", "dark: alert chip"],
  ["#e3ece9", "#6b5a12", "dark: ink on marker"],
];
