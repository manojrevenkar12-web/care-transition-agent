"""The transfer profile schema (config/profile.yaml): fields, value validation, and the FHIR Questionnaire it implies."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from . import config


@dataclass(frozen=True)
class Field:
    id: str
    section: str
    label_de: str
    label_en: str
    type: str  # enum | boolean | date | text | summary
    options: tuple[str, ...] = ()
    required: bool = False
    required_if: dict[str, Any] | None = None
    severity: str = "minor"
    search: bool = False
    max_chars: int = 0
    option_labels: dict[str, dict[str, str]] = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class Profile:
    version: int
    sections: tuple[dict[str, Any], ...]
    fields: tuple[Field, ...]

    def get(self, field_id: str) -> Field:
        for f in self.fields:
            if f.id == field_id:
                return f
        raise KeyError(field_id)

    @property
    def ids(self) -> list[str]:
        return [f.id for f in self.fields]

    def is_required(self, f: Field, values: dict[str, Any]) -> bool:
        if f.required:
            return True
        if f.required_if:
            return values.get(f.required_if["field"]) == f.required_if["equals"]
        return False


def load() -> Profile:
    raw = config.load("profile")
    labels = raw.get("option_labels", {})
    fields = tuple(
        Field(
            id=f["id"],
            section=f["section"],
            label_de=f["label"]["de"],
            label_en=f["label"]["en"],
            type=f["type"],
            options=tuple(str(o) for o in f.get("options", [])),
            required=bool(f.get("required")),
            required_if=f.get("required_if"),
            severity=f.get("severity", "minor"),
            search=bool(f.get("search")),
            max_chars=int(f.get("max_chars", 0)),
            option_labels=labels.get(f["id"], {}),
        )
        for f in raw["fields"]
    )
    return Profile(version=int(raw["version"]), sections=tuple(raw["sections"]), fields=fields)


class InvalidValue(ValueError):
    pass


def normalize(f: Field, value: Any) -> Any:
    """Coerce a value to the field's type, or raise InvalidValue (the model is told why, and may try again)."""
    if f.type == "enum":
        v = str(value).strip().lower()
        if v not in f.options:
            raise InvalidValue(f"{f.id} must be one of {', '.join(f.options)}")
        return v
    if f.type == "boolean":
        if isinstance(value, bool):
            return value
        v = str(value).strip().lower()
        if v in ("true", "ja", "yes", "1"):
            return True
        if v in ("false", "nein", "no", "0"):
            return False
        raise InvalidValue(f"{f.id} must be true or false")
    if f.type == "date":
        v = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return dt.datetime.strptime(v, fmt).date().isoformat()
            except ValueError:
                pass
        raise InvalidValue(f"{f.id} must be a date (YYYY-MM-DD)")
    if f.type in ("text", "summary"):
        v = " ".join(str(value).split())
        if not v:
            raise InvalidValue(f"{f.id} must not be empty")
        if f.max_chars and len(v) > f.max_chars:
            raise InvalidValue(f"{f.id} is limited to {f.max_chars} characters")
        return v
    raise InvalidValue(f"unknown field type {f.type}")


def label(f: Field, value: Any, lang: str = "de") -> str:
    if value is None:
        return ""
    if f.type == "boolean":
        return ("Ja" if value else "Nein") if lang == "de" else ("Yes" if value else "No")
    if f.type == "enum":
        return f.option_labels.get(str(value), {}).get(lang, str(value))
    return str(value)


def questionnaire(p: Profile | None = None) -> dict[str, Any]:
    """The profile as a FHIR R4 Questionnaire: one group per section, one item per field."""
    p = p or load()
    type_map = {"enum": "choice", "boolean": "boolean", "date": "date", "text": "string", "summary": "text"}
    items = []
    for s in p.sections:
        group: dict[str, Any] = {"linkId": s["id"], "text": s["label"]["de"], "type": "group", "item": []}
        for f in (x for x in p.fields if x.section == s["id"]):
            item: dict[str, Any] = {
                "linkId": f.id,
                "text": f.label_de,
                "type": type_map[f.type],
                "required": f.required,
            }
            if f.type == "enum":
                item["answerOption"] = [{"valueCoding": {"code": o, "display": label(f, o)}} for o in f.options]
            if f.required_if:
                item["enableWhen"] = [
                    {
                        "question": f.required_if["field"],
                        "operator": "=",
                        "answerCoding": {"code": f.required_if["equals"]},
                    }
                ]
            if f.max_chars:
                item["maxLength"] = f.max_chars
            group["item"].append(item)
        items.append(group)
    return {
        "resourceType": "Questionnaire",
        "id": f"transfer-profile-v{p.version}",
        "url": "https://care-transition-agent.example/fhir/Questionnaire/transfer-profile",
        "version": str(p.version),
        "status": "active",
        "title": "Überleitungsprofil",
        "item": items,
    }
