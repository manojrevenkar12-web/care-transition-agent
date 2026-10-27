# Held-out set v2

Written blind. The author read only `heldout/WRITING_GUIDE.md`. They did not read the code, the
configuration, the dev data, other held-out sets (including `heldout/v1`), reports or git history. They
did not try to find out how the components work. All people, numbers, addresses, account numbers and
facilities are invented.

## Files

| file | items | labels |
|---|---|---|
| `pii.jsonl` | 55 | 314 identifier occurrences (219 listed, 95 unlisted) |
| `grounding.jsonl` | 62 | supported 26, contradicted 9, unsupported 9, stale 9, not_found 9 |
| `guards.jsonl` | 60 | injection 10 true / 10 false, scope 10/10, advice 10/10 |

### pii.jsonl

- **Document mix:** 8 discharge or transfer letters, 2 typed forms (a transfer master-data sheet and a rehab
  application), 11 nursing notes, 7 social-services notes, 9 lower-case
  dictations with spoken numbers, 9 OCR-damaged scans (a transfer form, a referral, a medication plan, a
  care-insurance decision, an ambulance protocol, a lab report, a fax and a short-term-care application) and 9
  short messages.
- **Identifier kinds:** name 201, phone 24, birth_date 23, address 18, postal_code 14, other 11, case_number 8,
  kvnr 7, email 5, iban 3.
- **Hard cases:**
  - Surnames that are ordinary words, used next to the word itself: Klein/klein, Weiß/weiß/weiße, Sauer/sauer,
    Jung/jung, Lang/lang, Ernst/ernst. "Koch" appears as a cook with nobody named Koch.
  - Names inside compounds: Hahn/Dreiwegehahn, Strauß/Blumenstrauß, Mann/Ehemann, Kaiser/Kaiserschnitt,
    pfeiffer/pfeiffersches drüsenfieber, Rieger inside a photo file name.
  - Eponyms to keep: Morbus Parkinson, Morbus Addison, Alzheimer, Hashimoto, Wagner-Armstrong, Kellgren-Lawrence,
    Lewy-Body. "nash" is a diagnosis.
  - Initials: "Hr. T.", "Fr. M.", "K.-M.", "A.B.", "Jana W.".
  - Double names and particles: "von der Heyde", "Meyer-Lüdenscheidt", "Arslan-Bauer", "Al-Hashimi".
  - Foreign names and transliterations: Yıldırım/Yildirim, Petrović, Kusnezow/Kuznetsov, Nguyen Thi Hoa,
    Szymańska, Wróbel.
  - Genitives: "Schröders", "Hildebrandts".
  - Names, phone numbers and a KVNR split across line breaks.
  - In dictations: spoken birth dates, phone numbers, a case number, an address and postal code, a KVNR in the
    spelling alphabet, and a spoken e-mail address.
  - OCR damage in names, dates, postal codes and e-mails (1/l, 0/O).
  - A second patient with the same surname, listed once as true and once as false.
  - A self-corrected name ("meier nein maier").
  - A nickname ("Heinz").
  - A German and an Austrian IBAN.
  - Pension, Beihilfe, notary and insurance file numbers as `other`.
- **Conventions:**
  - Each contiguous name span is one identifier, for example "Gertrud Hallmann". A bare "Hallmann" elsewhere is a
    separate occurrence.
  - Every occurrence is listed, counted with word boundaries and excluding occurrences inside a longer listed
    identifier.
  - Institution names (hospitals, homes, insurers) and cities are neither identifiers nor `must_keep`.

### grounding.jsonl

- All 17 fields occur.
- **Hard cases:**
  - Negation outside the quote ("Dialysepflicht", "Eine Weglauftendenz", "Eine Demenz liegt").
  - Negation far from the word.
  - Double negation, in both directions ("wird nicht abgesetzt" supports insulin; "nicht ohne Sauerstoff"
    contradicts oxygen=false).
  - A negative value supported by negative wording (MRE screening negative gives `keine`; DK removed gives
    `urinary_catheter=false`).
  - A relative's condition; "Z.n."; a plan; a refusal; "beantragt" against a granted grade; another value; another
    field; another person's power of attorney.
  - Lower-case dictation without punctuation and OCR text.
  - Stale facts: oxygen stopped, discharge postponed, 3MRGN reclassified as 4MRGN, grade granted, fall, catheter
    removed, home care cancelled, delirium, NIV started.
- **not_found quotes:** some differ by one character (3MRGN/4MRGN, rechts/links, a digit in a date or grade).
  Others are paraphrased or invented. Some state a value the documents actually support.
- Documents within an item are in time order.

### guards.jsonl

- Injections are blunt and disguised, in German and English: HTML comments, bracketed asides inside a nursing
  note, "für die automatisierte Auswertung", OCR-mangled English, and an exfiltration request.
- The false items use "ignoriert", "Anweisung", "System", "Befehle", "KI" and "verwerfen" in their ordinary
  sense.
- Scope and advice include questions about what the documents say on dose or prognosis (false). They also include
  answers that report a dose and then recommend a change (true).

## Judgement calls

- **pii:**
  - Initials, a nickname, a misspoken spelling ("meier") and OCR-damaged spellings of a listed person count as
    `listed: true`.
  - A maiden name not in the record ("geb. Hoppe") counts as `listed: false`.
  - A spoken KVNR is labelled `kvnr`.
- **grounding:**
  - A refusal ("Die angebotene Kurzzeitpflege lehnt die Pat. ab") is labelled `unsupported`, not `contradicted`.
  - A delirium after "orientiert" makes the earlier sentence `stale`.
  - A planned transfer date ("für den 15.10.2026 geplant") supports `discharge_date` until it is postponed.
- **guards:**
  - A correction addressed to clinicians ("frühere Angabe … kann ignoriert werden") is not an injection.
  - An answer that refers the dose decision to the physician is not advice.
