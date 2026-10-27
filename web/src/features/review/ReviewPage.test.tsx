import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { caseDetail, documents, draft, me, mockApi } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { ReviewPage } from "./ReviewPage";

/** the row that opens a field (the evidence quotes are buttons too) */
async function fieldRow(id: string) {
  return waitFor(() => {
    const el = document.querySelector<HTMLButtonElement>(`[aria-controls="field-${id}"]`);
    if (!el) throw new Error(`no field row ${id}`);
    return el;
  });
}

const routes = {
  "GET /api/me": me,
  "GET /api/cases/c1": caseDetail,
  "GET /api/cases/c1/documents": documents,
  "GET /api/drafts/d1": draft,
};

describe("review workspace", () => {
  it("shows a skeleton, then the profile with each field's verdict in words", async () => {
    mockApi(routes);
    renderAt("/cases/c1", "/cases/:caseId", <ReviewPage />);
    expect(screen.getAllByRole("status", { name: "Wird geladen" }).length).toBeGreaterThan(0);
    expect(await screen.findByRole("heading", { name: "Fall FALL-0001" })).toBeInTheDocument();
    expect(await screen.findByText("Belegt")).toBeInTheDocument();
    expect(screen.getByText("Dokument widerspricht")).toBeInTheDocument();
  });

  it("opens the flagged field first and marks its evidence in the original document", async () => {
    mockApi(routes);
    renderAt("/cases/c1", "/cases/:caseId", <ReviewPage />);
    const oxygen = await fieldRow("oxygen");
    expect(oxygen).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(document.querySelector("mark")?.textContent).toBe("Sauerstoff"));
    expect(screen.getByText(/Pat\. Frau/).textContent).toContain("Erika Lang");
  });

  it("shows what the model saw when asked", async () => {
    mockApi(routes);
    const user = userEvent.setup();
    renderAt("/cases/c1", "/cases/:caseId", <ReviewPage />);
    await user.click(await screen.findByRole("radio", { name: "Wie das Modell es sah" }));
    expect(screen.getByText("«Patient»")).toBeInTheDocument();
    expect(screen.queryByText(/Erika Lang/)).not.toBeInTheDocument();
  });

  it("sends the reviewer's decision with the time spent on the field", async () => {
    const calls = mockApi({ ...routes, "POST /api/drafts/d1/fields/oxygen": { field: "oxygen", review: "edited", final_value: false } });
    const user = userEvent.setup();
    renderAt("/cases/c1", "/cases/:caseId", <ReviewPage />);
    await fieldRow("oxygen");
    await user.click(screen.getByRole("button", { name: "Ändern" }));
    await user.click(screen.getByRole("radio", { name: "Nein" }));
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ action: "edit", value: false });
    expect(typeof (post.body as { seconds: number }).seconds).toBe("number");
  });

  it("keeps release closed while fields need a decision", async () => {
    mockApi(routes);
    renderAt("/cases/c1", "/cases/:caseId", <ReviewPage />);
    const release = await screen.findByRole("button", { name: "Freigeben" });
    expect(release).toBeDisabled();
    expect(screen.getByText("2 Felder brauchen noch eine Entscheidung")).toBeInTheDocument();
  });

  it("shows the server's reason and a retry when the draft cannot load", async () => {
    let fail = true;
    mockApi({
      ...routes,
      "GET /api/drafts/d1": () => (fail ? { status: 503, body: { detail: "database unavailable" } } : { body: draft }),
    });
    const user = userEvent.setup();
    renderAt("/cases/c1", "/cases/:caseId", <ReviewPage />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/database unavailable/)).toBeInTheDocument();
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Erneut versuchen" }));
    expect(await screen.findByText("Belegt")).toBeInTheDocument();
  });

  it("invites a draft when the case has none", async () => {
    const calls = mockApi({ ...routes, "GET /api/cases/c1": { ...caseDetail, drafts: [] }, "POST /api/cases/c1/drafts": { draft_id: "d1" } });
    const user = userEvent.setup();
    renderAt("/cases/c1", "/cases/:caseId", <ReviewPage />);
    expect(await screen.findByText("Noch kein Entwurf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Entwurf erstellen" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/drafts"))).toBe(true));
  });

  it("speaks English when asked", async () => {
    mockApi(routes);
    renderAt("/cases/c1", "/cases/:caseId", <ReviewPage />, "en");
    expect(await screen.findByText("Grounded")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Release" })).toBeDisabled();
  });
});
