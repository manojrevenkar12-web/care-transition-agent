import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { session } from "@/lib/session";
import type { Me } from "@/lib/types";

export function useToken(): string | null {
  return useSyncExternalStore(session.subscribe, session.token, () => null);
}

export function useMe() {
  const token = useToken();
  return useQuery({ queryKey: ["me", token], queryFn: () => api<Me>("/api/me"), enabled: !!token, retry: false });
}

export function useCan(permission: string): boolean {
  return !!useMe().data?.permissions.includes(permission);
}

export function useSignOut() {
  const qc = useQueryClient();
  return useCallback(() => {
    session.clear();
    qc.clear();
  }, [qc]);
}
