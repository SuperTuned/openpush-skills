"""Small stdlib-only REST client for manifest operations."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request


class ClientError(RuntimeError):
    pass


class Client:
    def __init__(self, server: str, api_key: str):
        self.server = server.rstrip("/")
        self.api_key = api_key

    def schema(self) -> dict[str, Any]:
        return self._request("GET", "/v1/manifest-schema")

    def put_manifest(self, app: str, doc: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/v1/apps/{parse.quote(app, safe='')}/manifest", doc)

    def diff_manifest(self, app: str, doc: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/v1/apps/{parse.quote(app, safe='')}/manifest/diff", doc)

    def latest_version(self, app: str) -> str | None:
        try:
            response = self._request("GET", f"/v1/apps/{parse.quote(app, safe='')}/manifest")
        except ClientError as exc:
            if getattr(exc, "status", None) == 404:
                return None
            raise
        manifest = response.get("manifest", response)
        return manifest.get("app_version") if isinstance(manifest, dict) else None

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json", "X-OP-API-Key": self.api_key}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = request.Request(self.server + path, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=10) as response:
                payload = response.read()
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = {"detail": raw or exc.reason}
            message = str(detail.get("detail") or detail.get("error") or exc.reason)
            if exc.code == 403 and "read-only" in message.lower():
                message = "This API key is read-only. Sharing a manifest needs a full-scope key."
            elif exc.code == 422 and isinstance(detail.get("issues"), list):
                message = "\n".join(str(issue) for issue in detail["issues"])
            failure = ClientError(message)
            failure.status = exc.code
            raise failure from exc
        except (error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ClientError(f"Could not reach {self.server}: {reason}") from exc
        if not payload:
            return {}
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ClientError(f"Could not read response from {self.server}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ClientError(f"Could not read response from {self.server}: expected an object")
        return value


class OAuthManifestClient:
    """App-bound OAuth client for the scanner's two-step upload routes."""

    def __init__(self, server: str, access_token: str):
        self.server = server.rstrip("/")
        self.access_token = access_token

    def prepare(self, app: str, doc: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"manifest": doc}
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request(app, "prepare", body)

    def confirm(self, app: str, confirm_token: str) -> dict[str, Any]:
        return self._request(app, "confirm", {"confirm_token": confirm_token})

    def discard(self, app: str, confirm_token: str) -> dict[str, Any]:
        return self._request(app, "discard", {"confirm_token": confirm_token})

    def _request(self, app: str, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        path = f"/cli/v1/apps/{parse.quote(app, safe='')}/manifest/{operation}"
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        req = request.Request(
            self.server + path,
            data=data,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                payload = response.read()
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                problem = json.loads(raw)
            except json.JSONDecodeError:
                problem = {"detail": raw or exc.reason}
            detail = problem.get("detail") or problem.get("error") or exc.reason
            if isinstance(detail, dict):
                detail = "; ".join(str(item) for item in detail.get("issues", [])) or detail.get("code")
            failure = ClientError(str(detail))
            failure.status = exc.code
            raise failure from exc
        except (error.URLError, OSError) as exc:
            raise ClientError(f"Could not reach {self.server}: {getattr(exc, 'reason', exc)}") from exc
        try:
            value = json.loads(payload) if payload else {}
        except json.JSONDecodeError as exc:
            raise ClientError(f"Could not read response from {self.server}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ClientError(f"Could not read response from {self.server}: expected an object")
        return value
