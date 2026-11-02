"""Browser OAuth, secure token storage, and non-secret CLI workspace context."""

from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import webbrowser

from . import portable


SERVICE = "ai.openpush.scan"
DEFAULT_SERVER = "https://app.openpush.ai"
INSTALL_SPEC = "git+https://github.com/SuperTuned/openpush-skills"
KEYRING_MISSING = (
    "Signing in and sharing need the keyring package, which this copy of openpush-scan "
    "does not have. Scanning and review work without it. To sign in or share, run the "
    f'full tool: uvx --from "{INSTALL_SPEC}" openpush-scan <command>, or '
    f'pipx run --spec "{INSTALL_SPEC}" openpush-scan <command>.'
)


class AuthError(RuntimeError):
    pass


def config_path(environ=None, windows: bool | None = None) -> Path:
    """%APPDATA%\\openpush-scan on Windows; $XDG_CONFIG_HOME or ~/.config elsewhere."""
    environ = os.environ if environ is None else environ
    windows = os.name == "nt" if windows is None else windows
    if windows:
        root = Path(environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        root = Path(environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "openpush-scan" / "config.json"


class Session:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path()
        self.config = self._load()

    @property
    def server(self) -> str:
        return str(self.config.get("server") or DEFAULT_SERVER).rstrip("/")

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        portable.write_text(self.path, json.dumps(self.config, indent=2, sort_keys=True) + "\n")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def account_name(self, server: str | None = None) -> str:
        return f"{(server or self.server).rstrip('/')}|discovery"

    def app_name(self, app: str, server: str | None = None) -> str:
        return f"{(server or self.server).rstrip('/')}|app|{app}"

    def _backend(self):
        try:
            import keyring
        except ImportError:
            raise AuthError(KEYRING_MISSING) from None
        backend = keyring.get_keyring()
        module = type(backend).__module__.lower()
        if getattr(backend, "priority", 0) <= 0 or "plaintext" in module or "keyrings.alt" in module:
            raise AuthError("No secure OS credential store is available. Plaintext token storage is not supported.")
        return keyring

    def require_secure_store(self) -> None:
        """Fail before any browser step when tokens could not be stored."""
        self._backend()

    def token_bundle(self, account: str) -> dict[str, Any] | None:
        raw = self._backend().get_password(SERVICE, account)
        if not raw:
            return None
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    def put_bundle(self, account: str, bundle: dict[str, Any]) -> None:
        self._backend().set_password(SERVICE, account, json.dumps(bundle, separators=(",", ":")))

    def delete_bundle(self, account: str) -> None:
        keyring = self._backend()
        try:
            keyring.delete_password(SERVICE, account)
        except keyring.errors.PasswordDeleteError:
            pass

    def remember_grant(self, app: str) -> None:
        grants = set(self.config.get("app_grants") or [])
        grants.add(app)
        self.config["app_grants"] = sorted(grants)
        self.save()


def _json_request(url: str, *, method: str = "GET", body: dict | None = None,
                  form: dict | None = None, bearer: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "openpush-scan/0.1"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=15) as response:
            value = json.loads(response.read().decode())
            return value if isinstance(value, dict) else {}
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        raise AuthError(detail or f"OpenPush returned HTTP {exc.code}") from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise AuthError(f"Could not reach OpenPush: {exc}") from exc


class OAuthClient:
    def __init__(self, session: Session):
        self.session = session

    def authorize(self, resource_path: str, scope: str, *, app_hint: str | None = None) -> dict:
        server = self.session.server
        result: dict[str, str] = {}
        expected_state = secrets.token_urlsafe(24)

        class Callback(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                query = parse_qs(urlparse(self.path).query)
                result.update({key: values[0] for key, values in query.items() if values})
                ok = result.get("state") == expected_state and bool(result.get("code"))
                message = "OpenPush authorization complete. You may close this window." if ok else "OpenPush authorization was not completed."
                payload = message.encode()
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        listener = HTTPServer(("127.0.0.1", 0), Callback)
        listener.timeout = 300
        redirect_uri = f"http://127.0.0.1:{listener.server_port}/callback"
        client_id = (self.session.config.get("oauth_clients") or {}).get(server)
        if not client_id:
            registered = _json_request(server + "/oauth/register", method="POST", body={
                "client_name": "OpenPush Scan CLI", "redirect_uris": [redirect_uri],
                "token_endpoint_auth_method": "none",
            })
            client_id = registered.get("client_id")
            if not client_id:
                raise AuthError("OpenPush did not return an OAuth client ID.")
            self.session.config.setdefault("oauth_clients", {})[server] = client_id
            self.session.save()
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        resource = server + resource_path
        params = {
            "response_type": "code", "client_id": client_id,
            "redirect_uri": redirect_uri, "scope": scope, "state": expected_state,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "resource": resource,
        }
        if app_hint:
            params["app_hint"] = app_hint
        print("Opening OpenPush in your browser…")
        if not webbrowser.open(server + "/oauth/authorize?" + urlencode(params)):
            raise AuthError("Could not open the browser for OpenPush authorization.")
        listener.handle_request()
        listener.server_close()
        if result.get("state") != expected_state:
            raise AuthError("OAuth state did not match; authorization was cancelled.")
        if result.get("error"):
            raise AuthError("OpenPush authorization was declined.")
        if not result.get("code"):
            raise AuthError("Timed out waiting for OpenPush authorization.")
        bundle = _json_request(server + "/oauth/token", method="POST", form={
            "grant_type": "authorization_code", "client_id": client_id,
            "redirect_uri": redirect_uri, "code": result["code"],
            "code_verifier": verifier, "resource": resource,
        })
        bundle.update({"client_id": client_id, "resource": resource,
                       "obtained_at": int(time.time())})
        return bundle

    def access_token(self, account: str) -> str:
        bundle = self.session.token_bundle(account)
        if not bundle:
            raise AuthError("Not signed in. Run `openpush-scan login` first.")
        if int(bundle.get("obtained_at", 0)) + int(bundle.get("expires_in", 0)) <= time.time() + 30:
            refreshed = _json_request(self.session.server + "/oauth/token", method="POST", form={
                "grant_type": "refresh_token", "client_id": bundle["client_id"],
                "refresh_token": bundle["refresh_token"], "resource": bundle["resource"],
            })
            refreshed.update({"client_id": bundle["client_id"], "resource": bundle["resource"],
                              "obtained_at": int(time.time())})
            self.session.put_bundle(account, refreshed)
            bundle = refreshed
        token = bundle.get("access_token")
        if not token:
            raise AuthError("Stored OpenPush login is incomplete; run login again.")
        return str(token)

    def catalog(self) -> dict:
        token = self.access_token(self.session.account_name())
        return _json_request(self.session.server + "/cli/v1/catalog", bearer=token)

    def login(self) -> dict:
        self.session.require_secure_store()
        bundle = self.authorize("/cli", "discover")
        self.session.put_bundle(self.session.account_name(), bundle)
        catalog = self.catalog()
        self.session.config["server"] = self.session.server
        self.session.config["account"] = catalog.get("account", {})
        self.session.save()
        return catalog

    def app_token(self, app: str) -> str:
        self.session.require_secure_store()
        account = self.session.app_name(app)
        try:
            return self.access_token(account)
        except AuthError:
            bundle = self.authorize("/mcp", "read write", app_hint=app)
            if bundle.get("app") != app:
                raise AuthError(f"OpenPush authorized {bundle.get('app') or 'no app'}, not {app}.")
            self.session.put_bundle(account, bundle)
            self.session.remember_grant(app)
            return str(bundle["access_token"])

    def revoke(self, account: str) -> None:
        bundle = self.session.token_bundle(account)
        if bundle:
            for name in ("access_token", "refresh_token"):
                if bundle.get(name):
                    try:
                        _json_request(self.session.server + "/oauth/revoke", method="POST",
                                      form={"token": bundle[name]})
                    except AuthError:
                        pass
        self.session.delete_bundle(account)
