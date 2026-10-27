import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { caseSummary, me, mockApi } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { CasesPage } from "./CasesPage";

describe("cases", () => {
  it("lists cases with their draft state", async () => {
    mockApi({ "GET /api/me": me, "GET /api/cases": [caseSummary, { ...caseSummary, id: "c2", external_ref: "FALL-0002", draft_id: null, draft_status: null }] });
    renderAt("/", "/", <CasesPage />);
    expect(await screen.findByRole("link", { name: "FALL-0001" })).toHaveAttribute("href", "/cases/c1");
    expect(screen.getByText("1 markiert")).toBeInTheDocument();
    expect(screen.getByText("Kein Entwurf")).toBeInTheDocument();
  });

  it("explains where cases come from when there are none", async () => {
    mockApi({ "GET /api/me": me, "GET /api/cases": [] });
    renderAt("/", "/", <CasesPage />);
    expect(await screen.findByText("Noch keine Fälle")).toBeInTheDocument();
  });

  it("offers a retry when the list fails", async () => {
    let n = 0;
    mockApi({ "GET /api/me": me, "GET /api/cases": () => (n++ === 0 ? { status: 502, body: { detail: "model gateway: gateway_unreachable" } } : { body: [caseSummary] }) });
    const user = userEvent.setup();
    renderAt("/", "/", <CasesPage />);
    expect(await screen.findByText(/gateway_unreachable/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(await screen.findByRole("link", { name: "FALL-0001" })).toBeInTheDocument();
  });
});
