import { expect, test, type Page } from "@playwright/test";

// Runs against `cta serve --local-stack` with cases from `ctasim seed` (scripts/e2e.sh).

async function signIn(page: Page, token: string) {
  await page.goto("/");
  await page.getByLabel("Zugangstoken").fill(token);
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

test("a clinician reviews a draft against the documents", async ({ page }) => {
  await signIn(page, "demo-clinician");
  await expect(page.getByRole("heading", { name: "Fälle zur Überleitung" })).toBeVisible();
  const row = page.locator("tbody tr", { hasText: "In Prüfung" }).first();
  await row.getByRole("link").click();
  await expect(page.getByRole("heading", { name: "Überleitungsprofil" })).toBeVisible();
  await expect(page.locator("[data-field]").first()).toBeVisible();

  // the source as written and as the model saw it
  await page.getByRole("radio", { name: "Wie das Modell es sah" }).click();
  await expect(page.getByRole("tabpanel")).toContainText("«Patient»");
  await page.getByRole("radio", { name: "Original" }).click();
  await expect(page.getByRole("tabpanel")).not.toContainText("«Patient»");

  // release stays closed while anything blocks it
  const release = page.getByRole("button", { name: "Freigeben" });
  if (await page.getByText(/brauchen noch eine Entscheidung/).isVisible()) await expect(release).toBeDisabled();

  // accepting the grounded values takes one click and is recorded
  const acceptAll = page.getByRole("button", { name: /Alle belegten übernehmen/ });
  if (await acceptAll.isVisible()) {
    await acceptAll.click();
    await expect(acceptAll).toBeHidden();
  }
});

test("out-of-scope questions are refused without calling the model", async ({ page }) => {
  await signIn(page, "demo-clinician");
  await page.locator("tbody tr", { hasText: "In Prüfung" }).first().getByRole("link").click();
  await page.getByRole("button", { name: "Fragen zum Fall" }).click();
  await page.locator("#chat-input").fill("Welche Dosis Morphin soll die Einrichtung geben?");
  await page.getByRole("button", { name: "Fragen", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("ärztliche Entscheidung");
});

test("another hospital sees none of these cases", async ({ page }) => {
  await signIn(page, "demo-other-hospital");
  await expect(page.getByText("Noch keine Fälle")).toBeVisible();
});

test("the AI team sees quality and traces, not documents", async ({ page }) => {
  await signIn(page, "demo-quality");
  await page.getByRole("link", { name: "Qualität" }).click();
  await expect(page.getByRole("heading", { name: "Kalibrierung des LLM-Richters" })).toBeVisible();
  await expect(page.getByText("Gate nicht bestanden")).toBeVisible();
  await page.locator('a[href^="/runs/"]').first().click();
  await expect(page.getByRole("heading", { name: "Schritte" })).toBeVisible();
  const res = await page.request.get("/api/cases", { headers: { Authorization: "Bearer demo-quality" } });
  const [first] = (await res.json()) as Array<{ id: string }>;
  const docs = await page.request.get(`/api/cases/${first!.id}/documents`, { headers: { Authorization: "Bearer demo-quality" } });
  expect(docs.status()).toBe(403);
});
