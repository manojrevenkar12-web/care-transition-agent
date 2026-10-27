import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "@/components/Shell";
import { SkeletonLines } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { CasesPage } from "@/features/cases/CasesPage";
import { QualityPage } from "@/features/quality/QualityPage";
import { ReviewPage } from "@/features/review/ReviewPage";
import { RunPage } from "@/features/runs/RunPage";
import { SignIn } from "@/features/session/SignIn";
import { useMe, useToken } from "@/features/session/useMe";
import { ApiError } from "@/lib/api";
import { I18nProvider, useI18n } from "@/lib/i18n";
import { query } from "@/theme/tokens";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: query.staleMs,
        retry: (n, e) => n < query.retries && (!(e instanceof ApiError) || e.retryable),
        refetchOnWindowFocus: false,
      },
    },
  });
}

function Gate() {
  const token = useToken();
  const me = useMe();
  const { t } = useI18n();
  if (!token) return <SignIn />;
  if (me.isPending) return <div style={{ padding: "var(--s-8)" }}><SkeletonLines label={t("state.loading")} /></div>;
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) return <SignIn />;
    return <div style={{ padding: "var(--s-8)" }}><ErrorState error={me.error} onRetry={() => void me.refetch()} /></div>;
  }
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<CasesPage />} />
        <Route path="/cases/:caseId" element={<ReviewPage />} />
        <Route path="/quality" element={<QualityPage />} />
        <Route path="/runs/:runId" element={<RunPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}

export function App({ client = makeQueryClient() }: { client?: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <I18nProvider>
        <BrowserRouter>
          <Gate />
        </BrowserRouter>
      </I18nProvider>
    </QueryClientProvider>
  );
}
