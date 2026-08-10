from __future__ import annotations

import errno
import json
import sys
import threading
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import serve_kb_browser
from kb_browser_lib import browser_url
from repo_paths import initialize_test_workspace
from serve_kb_browser import BrowserHTTPServer, create_handler


class _Coordinator:
    pass


class _TerminalManager:
    def open(self, *, mode: str, force: bool = False) -> dict[str, object]:
        return {"ok": True, "mode": mode, "force": force}

    def write(self, session_id: str, data: str) -> dict[str, object]:
        return {"ok": True, "session_id": session_id, "data": data}

    def resize(self, session_id: str, cols: int, rows: int) -> dict[str, object]:
        return {"ok": True, "session_id": session_id, "cols": cols, "rows": rows}

    def poll(self, session_id: str, cursor: int) -> dict[str, object]:
        return {"ok": True, "session_id": session_id, "cursor": cursor}


@contextmanager
def _running_server(project_root: Path, token: str = "test-token", *, terminal_enabled: bool = False):
    try:
        server = BrowserHTTPServer(
            ("127.0.0.1", 0),
            create_handler(project_root=project_root),
            project_root=project_root,
            coordinator=_Coordinator(),
            terminal_manager=_TerminalManager() if terminal_enabled else None,
            terminal_enabled=terminal_enabled,
            auth_token=token,
        )
    except OSError as exc:
        if exc.errno in {errno.EPERM, errno.EACCES, errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT}:
            pytest.skip("Loopback server bind is unavailable in this environment")
        raise
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", token
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    request = Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_data_requests_require_token(tmp_path: Path, method: str) -> None:
    with _running_server(tmp_path) as (base, token):
        status, body, _ = _request(f"{base}/api/unsupported", method=method)
        assert status == 401
        assert json.loads(body) == {"ok": False, "error": "unauthorized"}
        assert _request(f"{base}/api/unsupported?token=wrong", method=method)[0] == 401

        status, _, _ = _request(f"{base}/api/unsupported?token={token}", method=method)
        assert status == 404


def test_static_get_requires_token_and_healthz_is_exempt(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    static_file = tmp_path / "index.html"
    static_file.write_text("ready", encoding="utf-8")

    with _running_server(tmp_path) as (base, token):
        assert _request(f"{base}/index.html")[0] == 401
        status, body, headers = _request(f"{base}/index.html?token={token}")
        assert status == 200
        assert body == b"ready"
        assert _request(f"{base}/api/healthz")[0] == 200
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        assert _request(f"{base}/index.html", headers={"Cookie": cookie})[0] == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"X-KB-Token": "test-token"},
        {"Authorization": "Bearer test-token"},
    ],
)
def test_auth_headers_are_accepted(tmp_path: Path, headers: dict[str, str]) -> None:
    (tmp_path / "index.html").write_text("ready", encoding="utf-8")

    with _running_server(tmp_path) as (base, _):
        assert _request(f"{base}/index.html", headers=headers)[0] == 200


def test_browser_url_includes_token_without_changing_health_urls(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    url = browser_url("127.0.0.1", 8765, tmp_path, token="one-time-token")

    assert url.endswith("/user/kb/index.html?token=one-time-token")


def test_access_log_redacts_token(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "index.html").write_text("ready", encoding="utf-8")

    with _running_server(tmp_path, token="secret-value") as (base, token):
        assert _request(f"{base}/index.html?token={token}")[0] == 200

    assert "secret-value" not in capsys.readouterr().err


def test_browser_token_is_not_printed_to_noninteractive_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    output = StringIO()
    monkeypatch.setattr(serve_kb_browser.sys, "stdout", output)

    serve_kb_browser._print_browser_url("http://127.0.0.1:8765/index.html?token=secret-value")

    assert "secret-value" not in output.getvalue()


def test_terminal_flag_defaults_off_and_can_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["serve_kb_browser.py"])
    assert serve_kb_browser.parse_args().enable_terminal is False

    monkeypatch.setattr(sys, "argv", ["serve_kb_browser.py", "--enable-terminal"])
    assert serve_kb_browser.parse_args().enable_terminal is True


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/terminal/open"),
        ("POST", "/api/terminal/input"),
        ("POST", "/api/terminal/resize"),
        ("GET", "/api/terminal/poll"),
        ("POST", "/api/system-terminal/open"),
    ],
)
def test_terminal_endpoints_refuse_when_disabled(tmp_path: Path, method: str, path: str) -> None:
    with _running_server(tmp_path) as (base, token):
        status, body, _ = _request(f"{base}{path}?token={token}", method=method)

    assert status == 403
    assert json.loads(body) == {"ok": False, "error": "终端功能未启用"}


def test_terminal_routes_are_reachable_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        serve_kb_browser,
        "open_system_terminal",
        lambda project_root, *, mode, target: {"ok": True, "mode": mode, "target": target},
    )
    body = json.dumps({}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    with _running_server(tmp_path, terminal_enabled=True) as (base, token):
        assert _request(
            f"{base}/api/terminal/open?token={token}", method="POST", headers=headers, body=body
        )[0] == 200
        input_body = json.dumps({"session_id": "session", "data": "hello"}).encode("utf-8")
        assert _request(
            f"{base}/api/terminal/input?token={token}", method="POST", headers=headers, body=input_body
        )[0] == 200
        resize_body = json.dumps({"session_id": "session", "cols": 80, "rows": 24}).encode("utf-8")
        assert _request(
            f"{base}/api/terminal/resize?token={token}", method="POST", headers=headers, body=resize_body
        )[0] == 200
        assert _request(f"{base}/api/terminal/poll?token={token}")[0] == 200
        assert _request(
            f"{base}/api/system-terminal/open?token={token}", method="POST", headers=headers, body=body
        )[0] == 200
