import { mockApi } from "@/test/fixtures";
import { api, ApiError } from "./api";
import { session } from "./session";

describe("api", () => {
  it("sends the bearer token and returns JSON", async () => {
    session.set("abc");
    let auth = "";
    mockApi({ "GET /api/me": (init: RequestInit | undefined) => ((auth = (init?.headers as Record<string, string>).Authorization ?? ""), { body: { ok: true } }) });
    expect(await api("/api/me")).toEqual({ ok: true });
    expect(auth).toBe("Bearer abc");
  });

  it("raises the server's explanation", async () => {
    mockApi({ "POST /api/drafts/x/release": () => ({ status: 409, body: { detail: "not ready: oxygen (needs a decision)" } }) });
    const err = await api("/api/drafts/x/release", { method: "POST" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe("not ready: oxygen (needs a decision)");
    expect((err as ApiError).retryable).toBe(false);
  });

  it("forgets the token when the server no longer accepts it", async () => {
    session.set("old");
    mockApi({ "GET /api/me": () => ({ status: 401, body: { detail: "sign in" } }) });
    await expect(api("/api/me")).rejects.toThrow("sign in");
    expect(session.token()).toBeNull();
  });
});
