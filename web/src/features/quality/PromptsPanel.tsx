import { useState, type FormEvent } from "react";
import { Button } from "@/components/Button";
import { Panel } from "@/components/Panel";
import { SkeletonLines } from "@/components/Skeleton";
import { ErrorState } from "@/components/States";
import { useCan } from "@/features/session/useMe";
import { dateTime, percent } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useDeploy, usePrompts, useWithdraw } from "./api";
import s from "./Quality.module.css";

/** Which prompt version serves whom. A canary gets a stable share of cases; its online numbers sit beside production's. */
export function PromptsPanel() {
  const { t, lang } = useI18n();
  const q = usePrompts();
  const canDeploy = useCan("prompts.deploy");
  const deploy = useDeploy();
  const withdraw = useWithdraw();
  const [form, setForm] = useState({ prompt: "profile_drafter", version: "", model: "sim-careful", share: "0.2" });

  function submit(e: FormEvent) {
    e.preventDefault();
    deploy.mutate({ ...form, share: Number(form.share) });
  }

  return (
    <Panel id="prompts" title={t("quality.prompts")}>
      {q.isPending && <SkeletonLines lines={4} label={t("state.loading")} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />}
      {q.data && (
        <>
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">Prompt</th>
                <th scope="col">{lang === "de" ? "Version und Modell" : "Version and model"}</th>
                <th scope="col" className={s.num}>{lang === "de" ? "Anteil" : "Share"}</th>
                <th scope="col">{lang === "de" ? "Seit" : "Since"}</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {Object.entries(q.data.defaults).map(([name, d]) => {
                const deps = q.data.deployments.filter((x) => x.prompt === name);
                if (deps.length === 0) {
                  return (
                    <tr key={name}>
                      <th scope="row">{name}</th>
                      <td>{`${d.version}@${d.model}`}</td>
                      <td className={s.num}>{percent(1, 0)}</td>
                      <td className={s.muted}>{lang === "de" ? "Voreinstellung" : "default"}</td>
                      <td />
                    </tr>
                  );
                }
                return deps.map((x) => (
                  <tr key={`${name}-${x.version}-${x.tenant_id}`}>
                    <th scope="row">{name}</th>
                    <td>
                      {`${x.version}@${x.model}`} {x.tenant_id === "*" && <span className={s.muted}>({lang === "de" ? "alle Häuser" : "all hospitals"})</span>}
                    </td>
                    <td className={s.num}>{percent(x.share, 0)}</td>
                    <td>{dateTime(x.since, lang)}</td>
                    <td>
                      {canDeploy && (
                        <Button variant="quiet" busy={withdraw.isPending} onClick={() => withdraw.mutate({ prompt: x.prompt, version: x.version })}>
                          {lang === "de" ? "Zurückziehen" : "Withdraw"}
                        </Button>
                      )}
                    </td>
                  </tr>
                ));
              })}
            </tbody>
          </table>
          {canDeploy && (
            <form className={s.deploy} onSubmit={submit}>
              <label>
                Prompt
                <select value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value, version: "" })}>
                  {Object.keys(q.data.files).map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
              <label>
                Version
                <select value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} required>
                  <option value="">{t("review.choose")}</option>
                  {q.data.files[form.prompt]?.map((v) => (
                    <option key={v.version} value={v.version}>
                      {v.version} ({v.sha})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {lang === "de" ? "Modell" : "Model"}
                <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} required />
              </label>
              <label>
                {lang === "de" ? "Anteil" : "Share"}
                <input type="number" min="0.05" max="1" step="0.05" value={form.share} onChange={(e) => setForm({ ...form, share: e.target.value })} />
              </label>
              <Button type="submit" variant="primary" busy={deploy.isPending} disabled={!form.version}>
                {Number(form.share) < 1 ? (lang === "de" ? "Als Canary ausrollen" : "Roll out as canary") : lang === "de" ? "Ausrollen" : "Roll out"}
              </Button>
            </form>
          )}
          {deploy.isError && <ErrorState error={deploy.error} compact />}
          {withdraw.isError && <ErrorState error={withdraw.error} compact />}
        </>
      )}
    </Panel>
  );
}
