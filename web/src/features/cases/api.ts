import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CaseDetail, CaseDocument, CaseSummary } from "@/lib/types";

export const caseKeys = {
  all: ["cases"] as const,
  one: (id: string) => ["cases", id] as const,
  documents: (id: string) => ["cases", id, "documents"] as const,
};

export const useCases = () => useQuery({ queryKey: caseKeys.all, queryFn: () => api<CaseSummary[]>("/api/cases") });

export const useCase = (id: string) =>
  useQuery({ queryKey: caseKeys.one(id), queryFn: () => api<CaseDetail>(`/api/cases/${encodeURIComponent(id)}`) });

export const useDocuments = (id: string, enabled = true) =>
  useQuery({
    queryKey: caseKeys.documents(id),
    queryFn: () => api<CaseDocument[]>(`/api/cases/${encodeURIComponent(id)}/documents`),
    enabled,
    staleTime: Infinity,
  });

export function useImportCase() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => file.text().then((raw) => api<{ case_id: string }>("/api/cases", { method: "POST", raw })),
    onSuccess: () => qc.invalidateQueries({ queryKey: caseKeys.all }),
  });
}
