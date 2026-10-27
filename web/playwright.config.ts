import { defineConfig } from "@playwright/test";

// The e2e suite runs against the real stack: `cta serve --local-stack` (API, Go gateway, simulated model) serving the
// built console, with demo cases seeded by `ctasim seed`. scripts/e2e.sh starts it and sets CTA_E2E_URL.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.CTA_E2E_URL ?? "http://127.0.0.1:8000",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
  },
});
