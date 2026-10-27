"""Client for the Go egress gateway. The platform never calls a model provider directly: every model call goes through
`Gateway.messages`, which the gateway pseudonymises, checks, routes and meters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


class GatewayError(RuntimeError):
    def __init__(self, status: int, kind: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(f"{kind}: {message}")
        self.status, self.kind, self.detail = status, kind, detail or {}


@dataclass
class Pseudonymized:
    text: str
    replacements: list[dict[str, Any]]
    leaks: list[str]


class Gateway:
    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ):
        self.url = (url or os.environ.get("CTA_GATEWAY_URL", "http://127.0.0.1:8070")).rstrip("/")
        self.token = token or os.environ.get("CTA_GATEWAY_TOKEN", "")
        self.http = client or httpx.Client(timeout=timeout)

    def _post(self, path: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
        h = {"Authorization": f"Bearer {self.token}", **(headers or {})}
        try:
            r = self.http.post(self.url + path, json=body, headers=h)
        except httpx.HTTPError as e:
            raise GatewayError(503, "gateway_unreachable", str(e)) from e
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {}
            raise GatewayError(r.status_code, err.get("type", "error"), err.get("message", r.text[:200]), err)
        return r

    def health(self) -> None:
        try:
            r = self.http.get(self.url + "/readyz", timeout=3)
        except httpx.HTTPError as e:
            raise GatewayError(503, "gateway_unreachable", str(e)) from e
        if r.status_code != 200:
            raise GatewayError(r.status_code, "gateway_not_ready", r.text[:200])

    def seal(self, identity: dict[str, Any]) -> str:
        return str(self._post("/v1/identity/seal", identity).json()["token"])

    def pseudonymize(self, tenant: str, case: str, token: str, texts: list[str]) -> list[Pseudonymized]:
        out = self._post(
            "/v1/pseudonymize", {"tenant": tenant, "case": case, "identity_token": token, "texts": texts}
        ).json()
        return [
            Pseudonymized(r["text"], r.get("replacements") or [], leaks or [])
            for r, leaks in zip(out["results"], out["leaks"], strict=True)
        ]

    def reidentify(self, tenant: str, case: str, token: str, texts: list[str]) -> list[str]:
        if not texts:
            return []
        return list(
            self._post(
                "/v1/reidentify", {"tenant": tenant, "case": case, "identity_token": token, "texts": texts}
            ).json()["texts"]
        )

    def messages(
        self,
        tenant: str,
        case: str,
        token: str,
        body: dict[str, Any],
        *,
        run_id: str = "",
        upstream: str = "",
        reidentify: bool = False,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        headers = {"X-CTA-Tenant": tenant, "X-CTA-Case": case, "X-CTA-Identity": token, "X-CTA-Run": run_id}
        if upstream:
            headers["X-CTA-Upstream"] = upstream
        if reidentify:
            headers["X-CTA-Reidentify"] = "true"
        r = self._post("/v1/messages", body, headers)
        return r.json(), {
            "upstream": r.headers.get("X-CTA-Upstream", ""),
            "processor": r.headers.get("X-CTA-Processor", ""),
        }

    def policy(self, tenant: str) -> dict[str, Any]:
        r = self.http.get(f"{self.url}/v1/policy/{tenant}", headers={"Authorization": f"Bearer {self.token}"})
        r.raise_for_status()
        return dict(r.json())


def to_original_span(start: int, end: int, replacements: list[dict[str, Any]]) -> tuple[int, int]:
    """Map a span in pseudonymised text back to the original text (for highlighting what a clinician reads)."""

    reps = sorted(replacements, key=lambda r: r["out_start"])

    def one(p: int, is_end: bool) -> int:
        shift = 0
        for r in reps:
            if p >= r["out_end"]:
                shift += (r["end"] - r["start"]) - (r["out_end"] - r["out_start"])
                continue
            if r["out_start"] < p < r["out_end"]:
                return int(r["end"] if is_end else r["start"])  # inside a tag: snap to the replaced span
            break
        return p + shift

    return one(start, False), one(end, True)
