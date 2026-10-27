import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { OnlineMetrics, PromptTable, Reports, Run } from "@/lib/types";
import { limits } from "@/theme/tokens";

export const useReports = () => useQuery({ queryKey: ["reports"], queryFn: () => api<Reports>("/api/quality/reports") });
export const useOnline = () => useQuery({ queryKey: ["online"], queryFn: () => api<OnlineMetrics>("/api/quality/online") });
export const usePrompts = () => useQuery({ queryKey: ["prompts"], queryFn: () => api<PromptTable>("/api/prompts") });
export const useRuns = () =>
  useQuery({ queryKey: ["runs"], queryFn: () => api<Run[]>(`/api/runs?limit=${limits.recentRuns}`) });

export interface DeployInput {
  prompt: string;
  version: string;
  model: string;
  share: number;
}

export function useDeploy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (d: DeployInput) => api("/api/prompts/deploy", { body: { ...d } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts"] }),
  });
}

export function useWithdraw() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (d: { prompt: string; version: string }) => api("/api/prompts/withdraw", { body: d }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts"] }),
  });
}
