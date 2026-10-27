"""Synthetic patients and the documents a German hospital writes about them before discharge.

Each case has a hidden truth (the transfer profile the documents support, read from the latest statement of each
fact) and a FHIR R4 Bundle (Patient, RelatedPerson, Practitioner, Encounter, DocumentReference) as a hospital system
would send it. The documents are written the way the real ones are: a provisional discharge letter, nursing notes, a
social-services note, a scanned admission form with OCR errors and, for some patients, a speech-recognition transcript
in lower case with spoken numbers. They contain the identifiers a pseudonymiser has to find, including people the
record does not list (a neighbour, a room-mate, the GP), facts that changed during the stay (MRSA cleared, oxygen
weaned), negations, facts nobody wrote down, and, in a few cases, an instruction aimed at an AI.

All names, numbers and addresses are invented.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from . import phrases as P

GIVEN_F = [
    "Gertrud",
    "Ingrid",
    "Helga",
    "Ursula",
    "Renate",
    "Christa",
    "Elfriede",
    "Hannelore",
    "Brigitte",
    "Erika",
    "Monika",
    "Waltraud",
    "Irmgard",
    "Gisela",
    "Edith",
    "Fatma",
    "Olga",
    "Halina",
    "Rosemarie",
    "Anneliese",
]
GIVEN_M = [
    "Horst",
    "Dieter",
    "Manfred",
    "Werner",
    "Klaus",
    "Günter",
    "Heinz",
    "Gerhard",
    "Wolfgang",
    "Jürgen",
    "Hans",
    "Helmut",
    "Rudolf",
    "Mehmet",
    "Piotr",
    "Wladimir",
    "Bernd",
    "Lothar",
    "Erich",
    "Ernst",
]
FAMILY = [
    "Hoffmann",
    "Schulz",
    "Krüger",
    "Neumann",
    "Schwarz",
    "Zimmermann",
    "Lehmann",
    "Köhler",
    "Hartmann",
    "Schmidt-Wendt",
    "Klein",
    "Lang",
    "Koch",
    "Wolff",
    "Braun",
    "Kaya",
    "Nowak",
    "Kowalczyk",
    "Petrenko",
    "Böhm",
    "Fuchs",
    "Vogel",
    "Sommer",
    "Haas",
    "Brandt",
    "Engel",
    "Kraus",
    "Pohl",
    "Seidel",
    "Winkler",
]
CHILD_F = ["Sabine", "Petra", "Andrea", "Claudia", "Susanne", "Katrin", "Nicole", "Anja", "Ayse", "Natalia"]
CHILD_M = ["Thomas", "Michael", "Andreas", "Frank", "Stefan", "Markus", "Jens", "Peter", "Murat", "Dimitri"]
DOCTORS = [
    ("Jonas", "Weber", "m"),
    ("Miriam", "Albrecht", "f"),
    ("Felix", "Brenner", "m"),
    ("Lea", "Hagedorn", "f"),
    ("Tobias", "Reuter", "m"),
    ("Svenja", "Kühne", "f"),
    ("Malte", "Dreyer", "m"),
    ("Nora", "Wiegand", "f"),
]
STREETS = [
    "Lindenstraße",
    "Birkenweg",
    "Am Mühlenfließ",
    "Gartenstraße",
    "Ahornallee",
    "Fontanestraße",
    "Kiefernring",
    "Seestraße",
    "Hauptstraße",
    "Rosenweg",
]
CITIES = [
    ("13583", "Berlin"),
    ("13187", "Berlin"),
    ("12043", "Berlin"),
    ("14467", "Potsdam"),
    ("14612", "Falkensee"),
    ("10365", "Berlin"),
    ("16515", "Oranienburg"),
    ("13403", "Berlin"),
]

ARCHETYPES: dict[str, dict[str, Any]] = {
    "hueftfraktur": {
        "dept": "Unfallchirurgie und Orthopädie",
        "diagnoses": [
            "Mediale Schenkelhalsfraktur rechts nach häuslichem Sturz (S72.01)",
            "Z.n. Hüft-TEP rechts",
            "Arterielle Hypertonie",
        ],
        "care": {"geriatrische_reha": 0.45, "anschlussreha": 0.2, "kurzzeitpflege": 0.35},
        "mobility": {"rollator": 0.6, "rollstuhl": 0.3, "bettlaegerig": 0.1},
        "early_bed": 0.6,
    },
    "schlaganfall": {
        "dept": "Neurologie",
        "diagnoses": ["Ischämischer Hirninfarkt im Mediastromgebiet links (I63.4)", "Hemiparese rechts", "Dysphagie"],
        "care": {"anschlussreha": 0.35, "langzeitpflege": 0.4, "kurzzeitpflege": 0.25},
        "mobility": {"rollstuhl": 0.5, "bettlaegerig": 0.3, "rollator": 0.2},
        "peg": 0.35,
    },
    "copd": {
        "dept": "Pneumologie",
        "diagnoses": ["Infektexazerbierte COPD GOLD 4 (J44.1)", "Chronische respiratorische Insuffizienz"],
        "care": {"ambulante_pflege": 0.5, "kurzzeitpflege": 0.35, "langzeitpflege": 0.15},
        "mobility": {"rollator": 0.5, "selbststaendig": 0.3, "rollstuhl": 0.2},
        "oxygen": 0.85,
        "niv": 0.35,
    },
    "herzinsuffizienz": {
        "dept": "Kardiologie",
        "diagnoses": [
            "Kardiale Dekompensation bei Herzinsuffizienz NYHA III (I50.13)",
            "Vorhofflimmern",
            "Diabetes mellitus Typ 2",
        ],
        "care": {"ambulante_pflege": 0.45, "kurzzeitpflege": 0.4, "langzeitpflege": 0.15},
        "mobility": {"rollator": 0.55, "selbststaendig": 0.3, "rollstuhl": 0.15},
        "oxygen": 0.25,
        "insulin": 0.5,
    },
    "demenz_delir": {
        "dept": "Geriatrie",
        "diagnoses": ["Hyperaktives Delir bei Harnwegsinfekt (F05.1)", "Demenz vom Alzheimer-Typ (G30.1)"],
        "care": {"langzeitpflege": 0.75, "kurzzeitpflege": 0.25},
        "mobility": {"rollator": 0.4, "selbststaendig": 0.35, "rollstuhl": 0.25},
        "dementia": 1.0,
        "catheter": 0.3,
    },
    "palliativ": {
        "dept": "Onkologie",
        "diagnoses": ["Metastasiertes Pankreaskarzinom (C25.0), palliative Situation", "Tumorschmerz"],
        "care": {"hospiz": 0.8, "ambulante_pflege": 0.2},
        "mobility": {"bettlaegerig": 0.5, "rollstuhl": 0.4, "rollator": 0.1},
        "oxygen": 0.3,
        "catheter": 0.4,
    },
    "dialyse": {
        "dept": "Nephrologie",
        "diagnoses": ["Terminale Niereninsuffizienz, dialysepflichtig (N18.5)", "Ambulant erworbene Pneumonie"],
        "care": {"kurzzeitpflege": 0.6, "langzeitpflege": 0.4},
        "mobility": {"rollator": 0.5, "rollstuhl": 0.4, "selbststaendig": 0.1},
        "dialysis": 1.0,
        "insulin": 0.4,
    },
    "langzeitbeatmung": {
        "dept": "Intensivmedizin / Weaning",
        "diagnoses": [
            "Prolongiertes Weaning nach septischem Schock",
            "Tracheostoma",
            "Critical-Illness-Polyneuropathie",
        ],
        "care": {"langzeitpflege": 1.0},
        "mobility": {"bettlaegerig": 0.7, "rollstuhl": 0.3},
        "invasive": 0.8,
        "peg": 0.6,
    },
}

PFLEGEGRADE = ["keiner", "pg1", "pg2", "pg3", "pg4", "pg5", "beantragt"]


@dataclass
class Document:
    id: str
    kind: str  # arztbrief | pflegebericht | sozialdienst | aufnahme | diktat
    title: str
    authored_at: str
    author_role: str
    text: str


@dataclass
class SimCase:
    case_id: str
    tenant: str
    archetype: str
    as_of: str
    identity: dict[str, Any]
    documents: list[Document]
    truth: dict[str, Any]  # profile value per field; None = the documents do not say
    key_facts: list[str]  # what a summary must mention
    injection: dict[str, str] | None = None
    traps: list[str] = field(default_factory=list)  # stale statements, negations, unlisted people

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pick(rng: random.Random, dist: dict[str, float]) -> str:
    r, acc = rng.random(), 0.0
    for k, p in dist.items():
        acc += p
        if r < acc:
            return k
    return next(iter(dist))


def _date(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def _kvnr(rng: random.Random) -> str:
    letter = chr(ord("A") + rng.randrange(26))
    body = "".join(str(rng.randrange(10)) for _ in range(8))
    pos = ord(letter) - ord("A") + 1
    digits = [pos // 10, pos % 10] + [int(c) for c in body]
    total = 0
    for i, d in enumerate(digits):
        p = d * (1 + i % 2)
        total += p // 10 + p % 10 if p > 9 else p
    return letter + body + str(total % 10)


def _phone(rng: random.Random) -> str:
    return rng.choice(["030", "0331", "03322", "0171", "0152"]) + " " + str(rng.randrange(1000000, 9999999))


def _ocr(rng: random.Random, text: str, rate: float = 0.015) -> str:
    """Light OCR damage: l/1, O/0, rn/m confusions in a few words, never inside numbers."""
    out = []
    for word in text.split(" "):
        if rng.random() < rate and len(word) > 4 and not any(c.isdigit() for c in word):
            word = word.replace("rn", "m", 1) if "rn" in word else word.replace("l", "1", 1)
        out.append(word)
    return " ".join(out)


def _spoken(text: str) -> str:
    """A speech-recognition transcript: lower case, spoken numbers, fillers, little punctuation."""
    t = text.lower()
    for n, w in P.SPOKEN.items():
        t = t.replace(f"pflegegrad {n}", f"pflegegrad {w}").replace(f"pg {n}", f"pflegegrad {w}")
    t = t.replace("l/min", "liter pro minute").replace(".", "").replace("(", "").replace(")", "")
    return t


def generate_case(seed: int, tenant: str = "klinikum-nord", as_of: dt.date = dt.date(2026, 10, 12)) -> SimCase:
    rng = random.Random(seed)
    case_id = hashlib.sha256(f"{tenant}|{seed}".encode()).hexdigest()[:12]
    arche_name = rng.choice(list(ARCHETYPES))
    A = ARCHETYPES[arche_name]
    sex = rng.choice("fm")
    given = rng.choice(GIVEN_F if sex == "f" else GIVEN_M)
    family = rng.choice(FAMILY)
    age = rng.randint(64, 96) if arche_name != "langzeitbeatmung" else rng.randint(48, 85)
    birth = dt.date(as_of.year - age, rng.randint(1, 12), rng.randint(1, 28))
    child_sex = rng.choice("fm")
    child_given = rng.choice(CHILD_F if child_sex == "f" else CHILD_M)
    child_family = family if rng.random() < 0.55 else rng.choice(FAMILY)
    child_rel = "Tochter" if child_sex == "f" else "Sohn"
    unlisted_sex = "m" if child_sex == "f" else "f"
    unlisted_child = (rng.choice(CHILD_M if unlisted_sex == "m" else CHILD_F), family)
    neighbour = (rng.choice(GIVEN_F), rng.choice(FAMILY))
    roommate_family = rng.choice(FAMILY)
    oa = rng.choice(DOCTORS)
    stationsarzt = rng.choice([d for d in DOCTORS if d != oa])
    hausarzt = rng.choice(
        ["Dr. med. Ulrike Sander", "Dr. med. Ahmet Yildiz", "Dr. med. Konrad Pieper", "Dr. med. Ines Faber"]
    )
    plz, city = rng.choice(CITIES)
    street = f"{rng.choice(STREETS)} {rng.randint(1, 120)}"
    phone_child = _phone(rng)
    kvnr = _kvnr(rng)
    case_no = f"{as_of.year}-{rng.randint(100000, 999999)}"
    admission = as_of - dt.timedelta(days=rng.randint(6, 18))
    discharge = as_of + dt.timedelta(days=rng.randint(1, 8))
    frau = "Frau" if sex == "f" else "Herr"
    frau_dat = "Frau" if sex == "f" else "Herrn"
    pat_word = "Patientin" if sex == "f" else "Patient"

    # ---- truth -------------------------------------------------------------------------------------------------
    t: dict[str, Any] = {}
    t["care_type"] = _pick(rng, A["care"])
    t["discharge_date"] = discharge.isoformat()
    t["pflegegrad"] = rng.choice(PFLEGEGRADE if age > 70 else ["keiner", "pg1", "pg2", "beantragt"])
    t["wish_region"] = rng.choice(P.REGIONS) if rng.random() < 0.55 else None
    t["mobility"] = _pick(rng, A["mobility"])
    t["transfer_help"] = (
        {
            "selbststaendig": "keine",
            "rollator": rng.choice(["keine", "eine_person"]),
            "rollstuhl": rng.choice(["eine_person", "zwei_personen"]),
            "bettlaegerig": "zwei_personen",
        }[t["mobility"]]
        if rng.random() < 0.75
        else None
    )
    if A.get("dementia"):
        t["cognition"] = "demenz"
    else:
        t["cognition"] = rng.choices(["orientiert", "leicht_eingeschraenkt", "demenz"], [0.6, 0.28, 0.12])[0]
    t["runaway_risk"] = (rng.random() < 0.45) if t["cognition"] == "demenz" else None
    t["oxygen"] = rng.random() < A.get("oxygen", 0.05)
    t["ventilation"] = (
        "invasiv"
        if rng.random() < A.get("invasive", 0)
        else "nicht_invasiv"
        if rng.random() < A.get("niv", 0.01)
        else "keine"
    )
    if t["ventilation"] == "invasiv":
        t["oxygen"] = True
    t["dialysis"] = rng.random() < A.get("dialysis", 0.02)
    t["peg_tube"] = rng.random() < A.get("peg", 0.03)
    t["wound_care"] = rng.random() < (0.5 if arche_name in ("hueftfraktur", "langzeitbeatmung") else 0.15)
    t["urinary_catheter"] = rng.random() < A.get("catheter", 0.12)
    t["insulin"] = rng.random() < A.get("insulin", 0.12)
    t["mre"] = rng.choices(["keine", "mrsa", "3mrgn", "4mrgn", "vre"], [0.72, 0.12, 0.08, 0.04, 0.04])[0]
    t["insurance_type"] = "pkv" if rng.random() < 0.1 else "gkv"
    t["legal_representation"] = rng.choices(["keine", "vorsorgevollmacht", "gesetzliche_betreuung"], [0.35, 0.45, 0.2])[
        0
    ]
    t["interpreter"] = (
        rng.choice(P.LANGUAGES)
        if (family in ("Kaya", "Nowak", "Kowalczyk", "Petrenko") and rng.random() < 0.6)
        else None
    )

    # Some facts are simply not written down. "Not documented" is the truth then: the agent must ask, not guess.
    for f, p_missing in {
        "discharge_date": 0.08,
        "pflegegrad": 0.1,
        "mobility": 0.04,
        "cognition": 0.06,
        "oxygen": 0.12,
        "ventilation": 0.35,
        "dialysis": 0.3,
        "mre": 0.1,
        "insurance_type": 0.07,
        "legal_representation": 0.3,
        "peg_tube": 0.5,
        "wound_care": 0.3,
        "urinary_catheter": 0.4,
        "insulin": 0.4,
        "care_type": 0.04,
    }.items():
        positive = t.get(f) not in (False, "keine", None)
        # positives that change the care are written down far more often
        if rng.random() < (
            p_missing * (0.25 if positive and f in ("oxygen", "dialysis", "ventilation", "mre", "peg_tube") else 1.0)
        ):
            t[f] = None
    # what the diagnosis list already says cannot be "not documented"
    if A.get("dementia") and t["cognition"] is None:
        t["cognition"] = "demenz"
    if A.get("dialysis") and t["dialysis"] is None:
        t["dialysis"] = True
    if arche_name == "langzeitbeatmung" and t["ventilation"] is None:
        t["ventilation"] = "invasiv" if rng.random() < A.get("invasive", 0) else "keine"
    if t.get("cognition") != "demenz":
        t["runaway_risk"] = None

    # ---- statements --------------------------------------------------------------------------------------------
    traps: list[str] = []
    stmts: dict[str, list[tuple[str, int]]] = {
        k: [] for k in ("arztbrief", "pflege1", "pflege2", "sozial", "aufnahme", "diktat")
    }

    def say(doc: str, text: str, order: int = 50) -> None:
        stmts[doc].append((text, order))

    def ch(options: list[str]) -> str:
        return rng.choice(options)

    if t["care_type"]:
        say("sozial", ch(P.CARE_TYPE[t["care_type"]]), 10)
        if rng.random() < 0.5:
            say("arztbrief", ch(P.CARE_TYPE[t["care_type"]]), 90)
    if t["discharge_date"]:
        sentence = ch(P.DISCHARGE).format(date=_date(discharge))
        say("arztbrief", sentence, 95)
        if rng.random() < 0.5:
            say("sozial", sentence, 15)
    if t["pflegegrad"]:
        sentence = ch(P.PFLEGEGRAD[t["pflegegrad"]]).format(date=_date(admission + dt.timedelta(days=2)))
        say("sozial", sentence, 20)
        if t["pflegegrad"].startswith("pg") and rng.random() < 0.5:
            say("aufnahme", f"Pflegegrad: {t['pflegegrad'][2]}", 60)
    if t["wish_region"]:
        say("sozial", ch(P.WISH_REGION).format(region=t["wish_region"]), 30)
    if t["mobility"]:
        if t["mobility"] != "bettlaegerig" and rng.random() < A.get("early_bed", 0.15):
            say("pflege1", P.MOBILITY_EARLY, 10)
            traps.append("mobility_changed")
        say("pflege2", ch(P.MOBILITY[t["mobility"]]), 10)
    if t["transfer_help"]:
        say("pflege2", ch(P.TRANSFER[t["transfer_help"]]), 12)
    if t["cognition"]:
        say("pflege2", ch(P.COGNITION[t["cognition"]]), 20)
        if t["cognition"] == "orientiert" and rng.random() < 0.4:
            say("arztbrief", P.COGNITION_NEG, 40)
            traps.append("negated_dementia")
    if t["runaway_risk"] is not None:
        say("pflege2", ch(P.RUNAWAY[t["runaway_risk"]]), 22)
    if t["oxygen"] is not None:
        if not t["oxygen"] and rng.random() < 0.3:
            say("pflege1", P.OXYGEN_STALE, 30)
            traps.append("oxygen_weaned")
        say("arztbrief", ch(P.OXYGEN[t["oxygen"]]).format(n=rng.choice([1, 2, 3])), 50)
    if t["ventilation"]:
        say("arztbrief", ch(P.VENTILATION[t["ventilation"]]), 52)
    if t["dialysis"] is not None:
        say("arztbrief", ch(P.DIALYSIS[t["dialysis"]]), 54)
    if t["peg_tube"] is not None:
        say("pflege2", ch(P.PEG[t["peg_tube"]]).format(date=_date(admission)), 40)
    if t["wound_care"] is not None:
        say("pflege2", ch(P.WOUND[t["wound_care"]]), 45)
    if t["urinary_catheter"] is not None:
        say("pflege2", ch(P.CATHETER[t["urinary_catheter"]]).format(date=_date(discharge + dt.timedelta(days=20))), 47)
    if t["insulin"] is not None:
        say("arztbrief", ch(P.INSULIN[t["insulin"]]), 56)
    if t["mre"]:
        if t["mre"] == "keine" and rng.random() < 0.25:
            say("pflege1", P.MRE_STALE["keine"], 50)
            say("arztbrief", P.MRE_CLEARED, 60)
            traps.append("mrsa_cleared")
        else:
            say("arztbrief", ch(P.MRE[t["mre"]]), 60)
            if t["mre"] != "keine" and rng.random() < 0.5:
                say("pflege2", "Isolierung im Einzelzimmer wegen " + t["mre"].upper() + ".", 60)
    if t["insurance_type"] == "gkv":
        say("aufnahme", ch(P.INSURANCE["gkv"]).format(kasse=rng.choice(P.KASSEN)), 20)
    elif t["insurance_type"] == "pkv":
        say("aufnahme", ch(P.INSURANCE["pkv"]).format(pkv=rng.choice(P.PKV)), 20)
    if t["legal_representation"]:
        say(
            "sozial",
            ch(P.LEGAL[t["legal_representation"]]).format(
                rel_acc="die Tochter" if child_sex == "f" else "den Sohn",
                rel_nom="die Tochter" if child_sex == "f" else "der Sohn",
            ),
            40,
        )
    if t["interpreter"]:
        say("sozial", ch(P.INTERPRETER).format(lang=t["interpreter"]), 45)

    # people the record does not list, and an occasional instruction aimed at an AI
    say("pflege1", f"Zimmernachbarin Frau {roommate_family} klagt über nächtliche Unruhe.", 70)
    say("sozial", f"Kontakt zur Nachbarin Frau {neighbour[1]}, die bisher eingekauft hat.", 60)
    if rng.random() < 0.4:
        who = "der Sohn" if unlisted_sex == "m" else "die Tochter"
        say("sozial", f"Auch {who} {unlisted_child[0]} {unlisted_child[1]} möchte informiert werden.", 65)
        traps.append("unlisted_relative")
    # someone else's needs, or the patient's past
    if rng.random() < 0.3:
        needs_sex = {"Zu Hause versorgt sie": "f", "Der Ehemann": "f", "Die Ehefrau": "m", "Er hat bis zuletzt": "m"}

        def fits(tr: tuple[str, Any, str]) -> bool:
            f_, v_, text_ = tr
            if t.get(f_) == v_:
                return False  # not a trap if it is true of the patient too
            if f_ == "mre" and t.get("mre") != "keine":
                return False
            return all(sex == want for prefix, want in needs_sex.items() if text_.startswith(prefix))

        options = [tr for tr in P.TRAPS if fits(tr)]
        if options:
            f_, _v, text_ = rng.choice(options)
            if f_ == "mre":
                say("arztbrief", text_, 5)  # in the diagnosis part, before the current screening result
            else:
                say("sozial", text_, 55)
            traps.append("other_person" if f_ != "mre" else "history")
    injection = None
    if rng.random() < 0.07:
        f, v, text = rng.choice(P.INJECTIONS)
        target = rng.choice(["sozial", "pflege2", "aufnahme"])
        say(target, text, 99)
        injection = {"field": f, "value": v, "doc": target}
        traps.append("injection")

    # ---- documents ---------------------------------------------------------------------------------------------
    def body(doc: str) -> str:
        return " ".join(s if s.endswith((".", ")")) else s + "." for s, _ in sorted(stmts[doc], key=lambda x: x[1]))

    docs: list[Document] = []
    d_adm = dt.datetime.combine(admission, dt.time(9, 40))
    docs.append(
        Document(
            "aufnahme",
            "aufnahme",
            "Aufnahmebogen (Scan)",
            d_adm.isoformat(),
            "Pflege",
            _ocr(
                rng,
                f"AUFNAHMEBOGEN Klinikum Nord. Name: {family}, {given} geb.: {_date(birth)} "
                f"Anschrift: {street}, {plz} {city} KVNR: {kvnr} Fall-Nr.: {case_no} "
                f"Kontakt: {child_rel} {child_given} {child_family}, Tel. {phone_child} "
                f"Hausarzt: {hausarzt} " + body("aufnahme"),
            ),
        )
    )
    docs.append(
        Document(
            "pflege1",
            "pflegebericht",
            "Pflegebericht (Aufnahme)",
            (d_adm + dt.timedelta(hours=8)).isoformat(),
            "Pflege",
            f"Pflegeanamnese {frau} {family}. " + body("pflege1"),
        )
    )
    docs.append(
        Document(
            "pflege2",
            "pflegebericht",
            "Pflegeüberleitung",
            dt.datetime.combine(as_of - dt.timedelta(days=1), dt.time(14, 5)).isoformat(),
            "Pflege",
            f"Pflegerische Überleitung für {frau_dat} {given} {family}. " + body("pflege2"),
        )
    )
    docs.append(
        Document(
            "sozial",
            "sozialdienst",
            "Sozialdienst – Entlassplanung",
            dt.datetime.combine(as_of - dt.timedelta(days=2), dt.time(11, 20)).isoformat(),
            "Sozialdienst",
            f"Gespräch mit {pat_word} und {child_rel} {child_given} {child_family} (Tel. {phone_child}). "
            + body("sozial"),
        )
    )
    diagnoses = "; ".join(A["diagnoses"])
    docs.append(
        Document(
            "arztbrief",
            "arztbrief",
            "Vorläufiger Entlassbrief",
            dt.datetime.combine(as_of, dt.time(8, 30)).isoformat(),
            "Arzt",
            f"Klinikum Nord, Klinik für {A['dept']}. Sehr geehrte Frau Kollegin, sehr geehrter Herr Kollege, "
            f"wir berichten über {frau_dat} {given} {family}, geb. {_date(birth)}, in stationärer Behandlung seit dem "
            f"{_date(admission)}. Diagnosen: {diagnoses}. Verlauf und Procedere: "
            + body("arztbrief")
            + f" Mit freundlichen kollegialen Grüßen, Dr. med. {oa[0]} {oa[1]}, {'Oberärztin' if oa[2] == 'f' else 'Oberarzt'}; "
            f"{stationsarzt[0]} {stationsarzt[1]}, {'Stationsärztin' if stationsarzt[2] == 'f' else 'Stationsarzt'}.",
        )
    )
    if rng.random() < 0.45:
        # a dictated handover: some of the nursing facts again, spoken
        spoken = [s for s, _ in stmts["pflege2"]][:4]
        if spoken:
            docs.append(
                Document(
                    "diktat",
                    "diktat",
                    "Diktat Übergabe (Spracherkennung)",
                    dt.datetime.combine(as_of, dt.time(7, 15)).isoformat(),
                    "Pflege",
                    _spoken(
                        f"ja also übergabe {frau.lower()} {family} äh "
                        + " ".join(spoken)
                        + f" angehörige {child_given} {child_family} informiert"
                    ),
                )
            )
            traps.append("dictation")

    key_facts = [
        k
        for k in (
            "care_type",
            "mobility",
            "cognition",
            "oxygen",
            "ventilation",
            "dialysis",
            "peg_tube",
            "mre",
            "runaway_risk",
        )
        if t.get(k) not in (None, False, "keine", "orientiert")
    ]
    identity = {
        "tenant": tenant,
        "case": case_id,
        "as_of": as_of.isoformat(),
        "birth_date": birth.isoformat(),
        "kvnr": kvnr,
        "case_numbers": [case_no],
        "addresses": [{"street": street, "postal_code": plz, "city": city}],
        "phones": [phone_child],
        "emails": [],
        "persons": [
            {"role": "patient", "given": given, "family": family, "sex": sex},
            {"role": "relative", "given": child_given, "family": child_family, "relationship": child_rel},
            {"role": "physician", "given": oa[0], "family": oa[1]},
            {"role": "physician", "given": stationsarzt[0], "family": stationsarzt[1]},
        ],
    }
    return SimCase(case_id, tenant, arche_name, as_of.isoformat(), identity, docs, t, key_facts, injection, traps)


def fhir_bundle(case: SimCase) -> dict[str, Any]:
    """The case as a hospital information system would send it (FHIR R4 transaction Bundle, German base profiles)."""
    idn = case.identity
    pat = next(p for p in idn["persons"] if p["role"] == "patient")
    rel = next(p for p in idn["persons"] if p["role"] == "relative")
    addr = idn["addresses"][0]
    pid, eid = f"Patient/{case.case_id}", f"Encounter/{case.case_id}"
    entries: list[dict[str, Any]] = [
        {
            "resource": {
                "resourceType": "Patient",
                "id": case.case_id,
                "identifier": [{"system": "http://fhir.de/sid/gkv/kvid-10", "value": idn["kvnr"]}],
                "name": [{"use": "official", "family": pat["family"], "given": [pat["given"]]}],
                "gender": "female" if pat.get("sex") == "f" else "male",
                "birthDate": idn["birth_date"],
                "address": [
                    {"line": [addr["street"]], "postalCode": addr["postal_code"], "city": addr["city"], "country": "DE"}
                ],
            }
        },
        {
            "resource": {
                "resourceType": "RelatedPerson",
                "id": f"{case.case_id}-rel",
                "patient": {"reference": pid},
                "relationship": [{"text": rel.get("relationship", "Angehörige")}],
                "name": [{"family": rel["family"], "given": [rel["given"]]}],
                "telecom": [{"system": "phone", "value": p} for p in idn["phones"]],
            }
        },
        {
            "resource": {
                "resourceType": "Encounter",
                "id": case.case_id,
                "status": "in-progress",
                "class": {"code": "IMP"},
                "subject": {"reference": pid},
                "identifier": [{"system": "urn:klinikum-nord:fallnummer", "value": n} for n in idn["case_numbers"]],
            }
        },
    ]
    for i, p in enumerate(x for x in idn["persons"] if x["role"] == "physician"):
        entries.append(
            {
                "resource": {
                    "resourceType": "Practitioner",
                    "id": f"{case.case_id}-pr{i}",
                    "name": [{"family": p["family"], "given": [p["given"]]}],
                }
            }
        )
    for d in case.documents:
        entries.append(
            {
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": f"{case.case_id}-{d.id}",
                    "status": "current",
                    "type": {"text": d.title},
                    "category": [{"text": d.kind}],
                    "subject": {"reference": pid},
                    "context": {"encounter": [{"reference": eid}]},
                    "date": d.authored_at + "+02:00",
                    "author": [{"display": d.author_role}],
                    "content": [
                        {
                            "attachment": {
                                "contentType": "text/plain; charset=utf-8",
                                "title": d.title,
                                "data": base64.b64encode(d.text.encode()).decode(),
                            }
                        }
                    ],
                }
            }
        )
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}
