import { session } from "./session";

/** An API error with the server's own explanation, which the UI shows as is. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly kind?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get retryable(): boolean {
    return this.status === 0 || this.status === 502 || this.status === 503 || this.status === 504;
  }
}

type Body = Record<string, unknown> | unknown[] | undefined;

export async function api<T>(path: string, init: { method?: string; body?: Body; raw?: BodyInit } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = session.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined = init.raw;
  if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.body);
  }
  let res: Response;
  try {
    res = await fetch(path, { method: init.method ?? (body ? "POST" : "GET"), headers, body });
  } catch {
    throw new ApiError(0, "The server cannot be reached. Check the connection and try again.");
  }
  if (res.status === 401) session.clear();
  if (!res.ok) {
    let detail = res.statusText;
    let kind: string | undefined;
    try {
      const j = (await res.json()) as { detail?: unknown; kind?: string };
      if (typeof j.detail === "string") detail = j.detail;
      else if (Array.isArray(j.detail)) detail = j.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
      kind = j.kind;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail, kind);
  }
  return (await res.json()) as T;
}
