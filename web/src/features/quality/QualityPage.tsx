import { motion } from "framer-motion";
import { SkeletonLines } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/States";
import { useI18n } from "@/lib/i18n";
import type { JudgeCriterion, OfflineReport } from "@/lib/types";
import { motion as m } from "@/theme/tokens";
import { useReports } from "./api";
import { HeldoutPanel } from "./HeldoutPanel";
import { JudgePanel } from "./JudgePanel";
import { OfflinePanel } from "./OfflinePanel";
import { OnlinePanel } from "./OnlinePanel";
import { PromptsPanel } from "./PromptsPanel";
import { RunsPanel } from "./RunsPanel";
import s from "./Quality.module.css";

export function QualityPage() {
  const { t } = useI18n();
  const reports = useReports();
  const offline = Object.entries(reports.data?.eval ?? {}).filter((e): e is [string, OfflineReport] => "metrics" in e[1]);
  const judge = Object.values(reports.data?.eval ?? {}).find((r): r is { judge: Record<string, JudgeCriterion> } => "judge" in r);

  return (
    <motion.div
      className={s.page}
      initial={{ opacity: 0, y: m.reveal.distance }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: m.reveal.duration, ease: m.ease }}
    >
      <header>
        <h1>{t("quality.title")}</h1>
        <p className={s.lead}>{t("quality.lead")}</p>
      </header>
      <div className={s.grid}>
        <OnlinePanel />
        <PromptsPanel />
      </div>
      <h2 className={s.section}>{t("quality.offline")}</h2>
      {reports.isPending && <SkeletonLines lines={8} label={t("state.loading")} />}
      {reports.isError && <ErrorState error={reports.error} onRetry={() => void reports.refetch()} />}
      {reports.data && offline.length === 0 && <EmptyState title={t("quality.offline")} body={t("quality.empty.reports")} />}
      <div className={s.grid}>
        {offline.map(([name, r]) => (
          <OfflinePanel key={name} name={name} report={r} />
        ))}
      </div>
      <div className={s.grid}>{judge && <JudgePanel judge={judge.judge} />}</div>
      {reports.data && Object.keys(reports.data.heldout).length > 0 && <HeldoutPanel runs={reports.data.heldout} />}
      <RunsPanel />
    </motion.div>
  );
}
