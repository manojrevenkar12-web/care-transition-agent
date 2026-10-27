import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/Button";
import { useI18n } from "@/lib/i18n";
import type { DraftField } from "@/lib/types";
import s from "./FieldEditor.module.css";

/** Enter or change a value in the field's own type. The server validates again (cta.profile.normalize). */
export function FieldEditor({
  field,
  initial,
  busy,
  onSave,
  onCancel,
}: {
  field: DraftField;
  initial: unknown;
  busy: boolean;
  onSave: (value: unknown) => void;
  onCancel: () => void;
}) {
  const { t, lang } = useI18n();
  const id = useId();
  const [value, setValue] = useState<string>(
    initial === null || initial === undefined ? "" : typeof initial === "boolean" ? String(initial) : String(initial),
  );
  const label = field.label[lang];

  function submit(e: FormEvent) {
    e.preventDefault();
    if (value === "") return;
    onSave(field.type === "boolean" ? value === "true" : value);
  }

  let input;
  if (field.type === "enum") {
    input = (
      <select id={id} value={value} onChange={(e) => setValue(e.target.value)} autoFocus>
        <option value="">{t("review.choose")}</option>
        {field.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  } else if (field.type === "boolean") {
    input = (
      <div className={s.radios} role="radiogroup" aria-labelledby={`${id}-l`}>
        {(["true", "false"] as const).map((v) => (
          <label key={v} className={s.radio}>
            <input type="radio" name={id} value={v} checked={value === v} onChange={() => setValue(v)} />
            {v === "true" ? t("review.yes") : t("review.no")}
          </label>
        ))}
      </div>
    );
  } else if (field.type === "date") {
    input = <input id={id} type="date" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />;
  } else if (field.type === "summary") {
    input = (
      <textarea id={id} rows={5} maxLength={600} value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
    );
  } else {
    input = <input id={id} type="text" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />;
  }

  return (
    <form className={s.editor} onSubmit={submit}>
      <label id={`${id}-l`} htmlFor={id} className="visually-hidden">
        {label}
      </label>
      {input}
      <div className={s.actions}>
        <Button type="submit" variant="primary" busy={busy} disabled={value === ""}>
          {t("review.save")}
        </Button>
        <Button type="button" variant="quiet" onClick={onCancel}>
          {t("review.cancel")}
        </Button>
      </div>
    </form>
  );
}
