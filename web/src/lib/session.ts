/** The bearer token for this browser tab. In production the hospital's identity provider issues it at the ingress;
 * in development a demo token is entered on the sign-in screen. Kept in sessionStorage so it ends with the tab. */

const KEY = "cta.token";
const listeners = new Set<() => void>();
let memory: string | null = null;

function read(): string | null {
  try {
    return sessionStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

export const session = {
  token: read,
  set(token: string): void {
    memory = token;
    try {
      sessionStorage.setItem(KEY, token);
    } catch {
      /* storage blocked: the in-memory token still works for this page */
    }
    listeners.forEach((l) => l());
  },
  clear(): void {
    memory = null;
    try {
      sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};
