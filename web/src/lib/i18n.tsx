import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

/** The console speaks German (the clinicians' language) and English (for the AI team and auditors). */
export type Lang = "de" | "en";

const de = {
  "app.name": "Überleitung",
  "nav.cases": "Fälle",
  "nav.quality": "Qualität",
  "nav.signout": "Abmelden",
  "nav.language": "English",
  "signin.title": "Anmelden",
  "signin.lead": "Im Klinikbetrieb meldet Sie das Krankenhaus-Login an. Für die Entwicklung genügt ein Demo-Token.",
  "signin.token": "Zugangstoken",
  "signin.submit": "Anmelden",
  "signin.demo": "Demo-Zugänge",
  "signin.failed": "Dieses Token ist unbekannt.",
  "role.clinician": "Ärztin / Arzt",
  "role.coordinator": "Sozialdienst",
  "role.quality": "KI-Team",
  "state.loading": "Wird geladen",
  "state.retry": "Erneut versuchen",
  "state.error": "Das hat nicht geklappt",
  "cases.title": "Fälle zur Überleitung",
  "cases.lead": "Entwürfe der Assistenz sind Vorschläge. Erst Ihre Freigabe macht daraus ein Überleitungsprofil.",
  "cases.empty.title": "Noch keine Fälle",
  "cases.empty.body": "Fälle kommen aus dem KIS als FHIR-Bundle. Importieren Sie eines, um zu beginnen.",
  "cases.import": "FHIR-Bundle importieren",
  "cases.importing": "Wird importiert",
  "cases.col.case": "Fall",
  "cases.col.asof": "Stand",
  "cases.col.docs": "Dokumente",
  "cases.col.draft": "Entwurf",
  "cases.col.open": "Offen",
  "cases.nodraft": "Kein Entwurf",
  "cases.released": "Freigegeben",
  "cases.inreview": "In Prüfung",
  "cases.blocked": "{n} gesperrt",
  "cases.flagged": "{n} markiert",
  "review.back": "Alle Fälle",
  "review.asof": "Stand {date}",
  "review.draftmeta": "Entwurf von {date} mit {prompt} auf {model}",
  "review.nodraft.title": "Noch kein Entwurf",
  "review.nodraft.body": "Die Assistenz liest die Dokumente und schlägt jedes Feld mit Beleg vor. Sie prüfen und geben frei.",
  "review.run": "Entwurf erstellen",
  "review.running": "Assistenz liest die Dokumente",
  "review.rerun": "Neu entwerfen",
  "review.acceptgrounded": "Alle belegten übernehmen ({n})",
  "review.profile": "Überleitungsprofil",
  "review.sources": "Quelldokumente",
  "review.view.original": "Original",
  "review.view.pseudo": "Wie das Modell es sah",
  "review.view.hint": "Namen, Geburtsdatum, KVNR, Adressen und Telefonnummern wurden ersetzt, bevor Text das Krankenhaus verließ.",
  "review.blockeddoc": "Gesperrt: Dieses Dokument enthielt nach der Pseudonymisierung noch ein Kennzeichen und wurde der Assistenz nicht gezeigt.",
  "review.injection": "Text, der sich an eine KI richtet. Die Assistenz hat ihn als Inhalt behandelt, nicht als Anweisung.",
  "review.evidence": "Beleg",
  "review.counter": "Spricht dagegen",
  "review.noevidence": "Kein Beleg in den Dokumenten.",
  "review.question": "Rückfrage der Assistenz",
  "review.accept": "Übernehmen",
  "review.edit": "Ändern",
  "review.answer": "Eintragen",
  "review.reject": "Verwerfen",
  "review.save": "Speichern",
  "review.cancel": "Abbrechen",
  "review.choose": "Bitte wählen",
  "review.yes": "Ja",
  "review.no": "Nein",
  "review.by": "von {who}",
  "review.required": "Pflichtfeld",
  "review.release": "Freigeben",
  "review.releasing": "Wird freigegeben",
  "review.release.blocked": "{n} Felder brauchen noch eine Entscheidung",
  "review.release.ready": "Alle Pflichtfelder sind geprüft.",
  "review.release.onlyclinician": "Nur Ärztinnen und Ärzte können freigeben.",
  "review.released": "Freigegeben am {date} von {who}",
  "review.jump": "Zum nächsten offenen Feld",
  "chat.open": "Fragen zum Fall",
  "chat.title": "Fragen zu den Dokumenten",
  "chat.lead": "Antworten zitieren die Dokumente. Medizinische Entscheidungen trifft die Assistenz nicht.",
  "chat.placeholder": "Zum Beispiel: Ist eine MRSA-Sanierung dokumentiert?",
  "chat.send": "Fragen",
  "chat.empty": "Noch keine Fragen zu diesem Fall.",
  "chat.unverified": "Ein Zitat ließ sich nicht im Dokument finden. Prüfen Sie die Antwort selbst.",
  "chat.helpful": "Hilfreich",
  "chat.wrong": "Falsch",
  "quality.title": "Qualität",
  "quality.lead": "Offline gegen den Goldstandard, online an dem, was Ärztinnen und Ärzte mit den Entwürfen tun.",
  "quality.offline": "Offline-Bewertung",
  "quality.judge": "Kalibrierung des LLM-Richters",
  "quality.online": "Im Betrieb (letzte {n} Tage)",
  "quality.prompts": "Prompt-Versionen im Einsatz",
  "quality.heldout": "Blinde Testsätze (erster Lauf)",
  "quality.runs": "Letzte Läufe",
  "quality.empty.online": "Noch keine Prüfaktionen in diesem Zeitraum.",
  "quality.empty.reports": "Noch keine Berichte. `cta eval offline` schreibt sie nach reports/eval.",
  "runs.title": "Lauf",
  "runs.steps": "Schritte",
  "runs.empty": "Dieser Lauf hat keine Schritte aufgezeichnet.",
};

type Key = keyof typeof de;

const en: Record<Key, string> = {
  "app.name": "Care transfer",
  "nav.cases": "Cases",
  "nav.quality": "Quality",
  "nav.signout": "Sign out",
  "nav.language": "Deutsch",
  "signin.title": "Sign in",
  "signin.lead": "In the hospital your sign-in comes from the hospital login. For development, a demo token is enough.",
  "signin.token": "Access token",
  "signin.submit": "Sign in",
  "signin.demo": "Demo accounts",
  "signin.failed": "This token is not known.",
  "role.clinician": "Clinician",
  "role.coordinator": "Social services",
  "role.quality": "AI team",
  "state.loading": "Loading",
  "state.retry": "Try again",
  "state.error": "That did not work",
  "cases.title": "Cases to transfer",
  "cases.lead": "The assistant's drafts are proposals. Only your release turns one into a transfer profile.",
  "cases.empty.title": "No cases yet",
  "cases.empty.body": "Cases arrive from the hospital information system as FHIR Bundles. Import one to start.",
  "cases.import": "Import FHIR Bundle",
  "cases.importing": "Importing",
  "cases.col.case": "Case",
  "cases.col.asof": "As of",
  "cases.col.docs": "Documents",
  "cases.col.draft": "Draft",
  "cases.col.open": "Open",
  "cases.nodraft": "No draft",
  "cases.released": "Released",
  "cases.inreview": "In review",
  "cases.blocked": "{n} blocked",
  "cases.flagged": "{n} flagged",
  "review.back": "All cases",
  "review.asof": "As of {date}",
  "review.draftmeta": "Draft of {date} with {prompt} on {model}",
  "review.nodraft.title": "No draft yet",
  "review.nodraft.body": "The assistant reads the documents and proposes each field with evidence. You review and release.",
  "review.run": "Create draft",
  "review.running": "The assistant is reading the documents",
  "review.rerun": "Draft again",
  "review.acceptgrounded": "Accept all grounded ({n})",
  "review.profile": "Transfer profile",
  "review.sources": "Source documents",
  "review.view.original": "Original",
  "review.view.pseudo": "As the model saw it",
  "review.view.hint": "Names, date of birth, insurance number, addresses and phone numbers were replaced before any text left the hospital.",
  "review.blockeddoc": "Blocked: this document still contained an identifier after pseudonymisation and was not shown to the assistant.",
  "review.injection": "Text addressed to an AI. The assistant treated it as content, not as an instruction.",
  "review.evidence": "Evidence",
  "review.counter": "Speaks against it",
  "review.noevidence": "No evidence in the documents.",
  "review.question": "The assistant asks",
  "review.accept": "Accept",
  "review.edit": "Change",
  "review.answer": "Enter",
  "review.reject": "Reject",
  "review.save": "Save",
  "review.cancel": "Cancel",
  "review.choose": "Choose",
  "review.yes": "Yes",
  "review.no": "No",
  "review.by": "by {who}",
  "review.required": "Required",
  "review.release": "Release",
  "review.releasing": "Releasing",
  "review.release.blocked": "{n} fields still need a decision",
  "review.release.ready": "Every required field has been reviewed.",
  "review.release.onlyclinician": "Only clinicians can release.",
  "review.released": "Released on {date} by {who}",
  "review.jump": "Next open field",
  "chat.open": "Ask about the case",
  "chat.title": "Questions about the documents",
  "chat.lead": "Answers quote the documents. The assistant does not make medical decisions.",
  "chat.placeholder": "For example: is MRSA decolonisation documented?",
  "chat.send": "Ask",
  "chat.empty": "No questions about this case yet.",
  "chat.unverified": "A quote could not be found in the document. Check the answer yourself.",
  "chat.helpful": "Helpful",
  "chat.wrong": "Wrong",
  "quality.title": "Quality",
  "quality.lead": "Offline against the golden set, online from what clinicians do with the drafts.",
  "quality.offline": "Offline evaluation",
  "quality.judge": "LLM judge calibration",
  "quality.online": "In service (last {n} days)",
  "quality.prompts": "Prompt versions in service",
  "quality.heldout": "Blind test sets (first run)",
  "quality.runs": "Recent runs",
  "quality.empty.online": "No review actions in this period yet.",
  "quality.empty.reports": "No reports yet. `cta eval offline` writes them to reports/eval.",
  "runs.title": "Run",
  "runs.steps": "Steps",
  "runs.empty": "This run recorded no steps.",
};

export const STATUS: Record<string, { de: string; en: string; tone: Tone }> = {
  grounded: { de: "Belegt", en: "Grounded", tone: "ready" },
  conflict: { de: "Neuere Angabe weicht ab", en: "Newer statement differs", tone: "alert" },
  contradicted: { de: "Dokument widerspricht", en: "Contradicted", tone: "alert" },
  unsupported: { de: "Nicht belegt", en: "Not supported", tone: "review" },
  quote_not_found: { de: "Zitat nicht gefunden", en: "Quote not found", tone: "alert" },
  injection: { de: "Verdächtiger Text", en: "Suspicious text", tone: "alert" },
  invalid: { de: "Ungültiger Wert", en: "Invalid value", tone: "review" },
  unknown: { de: "Nicht dokumentiert", en: "Not documented", tone: "neutral" },
  unknown_but_mentioned: { de: "Erwähnt, nicht erfasst", en: "Mentioned, not recorded", tone: "review" },
  missing: { de: "Fehlt", en: "Missing", tone: "neutral" },
};

/** The verifier's reasons (cta.grounding), in German for the clinicians. Unknown reasons are shown as they are. */
export const REASONS: Record<string, string> = {
  "a later statement says something else": "Eine spätere Angabe sagt etwas anderes.",
  "the quoted statement says the opposite": "Die zitierte Stelle sagt das Gegenteil.",
  "the quoted statement supports the value": "Die zitierte Stelle belegt den Wert.",
  "the quoted words are in none of the case's documents": "Die zitierten Worte stehen in keinem Dokument des Falls.",
  "no document speaks to this field": "Kein Dokument äußert sich zu diesem Feld.",
  "a document speaks to this field": "Ein Dokument äußert sich zu diesem Feld, die Assistenz hat es nicht erfasst.",
  "no evidence was given": "Die Assistenz hat keinen Beleg angegeben.",
  "the quoted statement does not say this": "Die zitierte Stelle sagt das nicht.",
  "the quoted statement is about someone else or the past": "Die zitierte Stelle betrifft eine andere Person oder die Vorgeschichte.",
  "the agent did not record this field": "Die Assistenz hat dieses Feld nicht ausgefüllt.",
  "the evidence is text addressed to an AI, not a clinical statement": "Der Beleg ist ein an eine KI gerichteter Text, keine klinische Angabe.",
};

export const REVIEW: Record<string, { de: string; en: string }> = {
  pending: { de: "offen", en: "open" },
  accepted: { de: "übernommen", en: "accepted" },
  edited: { de: "geändert", en: "changed" },
  answered: { de: "eingetragen", en: "entered" },
  rejected: { de: "verworfen", en: "rejected" },
};

export const SECTIONS: Record<string, { de: string; en: string }> = {
  versorgung: { de: "Versorgung", en: "Care" },
  mobilitaet: { de: "Mobilität und Kognition", en: "Mobility and cognition" },
  behandlungspflege: { de: "Behandlungspflege", en: "Treatment care" },
  infektion: { de: "Infektion", en: "Infection" },
  organisatorisches: { de: "Organisatorisches", en: "Administration" },
  zusammenfassung: { de: "Zusammenfassung", en: "Summary" },
};

export type Tone = "ready" | "review" | "alert" | "neutral";

interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
}

const Ctx = createContext<I18n | null>(null);

function initial(): Lang {
  try {
    const v = localStorage.getItem("cta.lang");
    if (v === "de" || v === "en") return v;
  } catch {
    /* storage blocked */
  }
  return "de";
}

export function I18nProvider({ children, lang: fixed }: { children: ReactNode; lang?: Lang }) {
  const [lang, setLangState] = useState<Lang>(fixed ?? initial);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    document.documentElement.lang = l;
    try {
      localStorage.setItem("cta.lang", l);
    } catch {
      /* ignore */
    }
  }, []);
  const value = useMemo<I18n>(
    () => ({
      lang,
      setLang,
      t: (key, vars) => {
        let s = (lang === "de" ? de : en)[key] ?? key;
        if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
        return s;
      },
    }),
    [lang, setLang],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside I18nProvider");
  return v;
}
