import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { caseKeys } from "@/features/cases/api";
import { api } from "@/lib/api";
import type { ChatMessage, ChatReply, Draft, DraftRun } from "@/lib/types";

export const draftKey = (id: string) => ["drafts", id] as const;
export const chatKey = (caseId: string) => ["chat", caseId] as const;

export const useDraft = (id: string | null | undefined) =>
  useQuery({ queryKey: draftKey(id ?? ""), queryFn: () => api<Draft>(`/api/drafts/${id}`), enabled: !!id });

export function useRunDraft(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<DraftRun>(`/api/cases/${encodeURIComponent(caseId)}/drafts`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: caseKeys.one(caseId) });
      void qc.invalidateQueries({ queryKey: caseKeys.all });
    },
  });
}

export interface ReviewInput {
  field: string;
  action: "accept" | "edit" | "answer" | "reject";
  value?: unknown;
  seconds?: number;
}

export function useReviewField(draftId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (r: ReviewInput) =>
      api<{ field: string; review: string; final_value: unknown }>(
        `/api/drafts/${draftId}/fields/${encodeURIComponent(r.field)}`,
        { body: { action: r.action, value: r.value ?? null, seconds: r.seconds ?? null } },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: draftKey(draftId) }),
  });
}

export function useAcceptGrounded(draftId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ accepted: number }>(`/api/drafts/${draftId}/accept-grounded`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: draftKey(draftId) }),
  });
}

export function useRelease(draftId: string, caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<Record<string, unknown>>(`/api/drafts/${draftId}/release`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: draftKey(draftId) });
      void qc.invalidateQueries({ queryKey: caseKeys.one(caseId) });
      void qc.invalidateQueries({ queryKey: caseKeys.all });
    },
  });
}

export const useChat = (caseId: string, enabled: boolean) =>
  useQuery({
    queryKey: chatKey(caseId),
    queryFn: () => api<ChatMessage[]>(`/api/cases/${encodeURIComponent(caseId)}/chat`),
    enabled,
  });

export function useAsk(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) =>
      api<ChatReply>(`/api/cases/${encodeURIComponent(caseId)}/chat`, { body: { message } }),
    onSettled: () => qc.invalidateQueries({ queryKey: chatKey(caseId) }),
  });
}

export function useFeedback(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, feedback }: { id: number; feedback: "helpful" | "wrong" }) =>
      api(`/api/chat/${id}/feedback`, { body: { feedback } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: chatKey(caseId) }),
  });
}
