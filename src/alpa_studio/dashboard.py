from __future__ import annotations

import html
import json
import mimetypes
import secrets
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .doctor import health_report
from .project import approval_decide, require_install, state_path
from .util import read_json
from . import session as studio_session


def snapshot(project: Path) -> dict[str, Any]:
    config = require_install(project)
    asset_root = project / "docs/studio/assets"
    assets = []
    if asset_root.is_dir():
        for path in sorted(asset_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                assets.append({"name": path.name, "relative": str(path.relative_to(asset_root))})
    return {
        "config": config,
        "health": health_report(project),
        "approvals": read_json(state_path(project, "approvals.json"), {"items": []})["items"],
        "tasks": read_json(state_path(project, "tasks.json"), {"items": []})["items"],
        "qa": read_json(state_path(project, "qa.json"), {"reviews": []})["reviews"],
        "evidence": read_json(state_path(project, "evidence.json"), {"sources": []})["sources"],
        "assets": assets,
        "session": _session_status(project),
    }


def _session_status(project: Path) -> dict[str, Any]:
    try:
        return studio_session.status(project)
    except Exception as exc:  # Mission Control must render even if session state is unreadable
        return {"error": f"{type(exc).__name__}: {exc}"}


def _session_panel(info: dict[str, Any]) -> str:
    if info.get("error"):
        return f'<p class="empty">Session state could not be read: {html.escape(info["error"])}</p>'
    runner = info.get("runner") or {}
    lock = runner.get("lock") or {}
    current = info.get("current_task") or {}
    counts = info.get("counts") or {}
    rows = [
        f"Mode: {html.escape(str((info.get('execution') or {}).get('policy')))}",
        "Runner: " + ("paused" if runner.get("paused") else ("running (pid %s)" % lock.get("pid") if lock.get("alive") else "idle")),
        "Active task: " + (html.escape(f"{current.get('task_id')} — {current.get('title') or ''}") if current else "none"),
        "Eligible: %s · Waiting for approval: %s · Waiting on dependencies: %s · Done: %s" % (
            counts.get("eligible", 0), counts.get("waiting_approval", 0), counts.get("blocked_dependency", 0), counts.get("done", 0)),
    ]
    return "<article>" + "".join(f"<p>{r}</p>" for r in rows) + "</article>"


def _cards(items: list[dict[str, Any]], empty: str, kind: str) -> str:
    if not items:
        return f'<p class="empty">{html.escape(empty)}</p>'
    rows = []
    for item in items:
        status = item.get("status", "recorded")
        body = html.escape(item.get("details") or item.get("title") or item.get("stage") or "")
        actions = ""
        if kind == "approval" and status == "pending":
            item_id = html.escape(item["id"])
            actions = (f'<form method="post" action="/approval"><input type="hidden" name="id" value="{item_id}">'
                       '<button name="decision" value="approved">Approve</button>'
                       '<button class="danger" name="decision" value="rejected">Reject</button></form>')
        rows.append(f'<article><div><b>{html.escape(item.get("id", ""))}</b><span class="tag {status}">{html.escape(status)}</span></div><p>{body}</p>{actions}</article>')
    return "".join(rows)


def page(project: Path, token: str) -> bytes:
    data = snapshot(project)
    pending = [x for x in data["approvals"] if x["status"] == "pending"]
    queued = [x for x in data["tasks"] if x["status"] in {"queued", "running"}]
    passed = [x for x in data["qa"] if x.get("passed")]
    health = data["health"]
    profile = data["config"]["profile"]
    gallery = ''.join(
        f'<figure><img src="/assets/{urllib.parse.quote(item["relative"])}" alt="{html.escape(item["name"])}"><figcaption>{html.escape(item["name"])}</figcaption></figure>'
        for item in data["assets"]
    ) or '<p class="empty">No gallery assets yet.</p>'
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Alpa Studio · Mission Control</title>
<style>
:root{{--bg:#090d18;--panel:#12192b;--line:#263251;--text:#edf2ff;--muted:#91a0bd;--cyan:#4bd7e8;--gold:#f2c14e;--green:#4fd18b;--red:#ff6b75}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#152545,var(--bg) 38%);color:var(--text);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1220px;margin:auto;padding:34px 22px 80px}}header{{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:28px}}h1{{margin:0;font-size:34px}}h1 em{{color:var(--cyan);font-style:normal}}.sub{{color:var(--muted)}}.pill{{border:1px solid var(--line);padding:8px 12px;border-radius:999px;color:var(--gold)}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}}.metric,.panel{{background:rgba(18,25,43,.91);border:1px solid var(--line);border-radius:15px;box-shadow:0 12px 40px #0005}}.metric{{padding:18px}}.metric strong{{display:block;font-size:28px}}.metric span{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.panel{{padding:18px;min-height:210px}}h2{{font-size:17px;margin:0 0 14px;color:var(--cyan)}}article{{padding:12px 0;border-top:1px solid var(--line)}}article:first-of-type{{border-top:0}}article div{{display:flex;justify-content:space-between;gap:10px}}article p{{color:var(--muted);margin:6px 0}}.tag{{font-size:11px;text-transform:uppercase;padding:2px 8px;border-radius:20px;background:#29334c}}.approved,.completed,.passed{{color:var(--green)}}.rejected,.failed{{color:var(--red)}}.pending,.queued{{color:var(--gold)}}
.gallery{{grid-column:1/-1}}.gallery-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}figure{{margin:0;background:#0b1120;border-radius:10px;overflow:hidden}}figure img{{display:block;width:100%;height:150px;object-fit:contain;background:#050812}}figcaption{{padding:8px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
button{{background:var(--cyan);border:0;padding:7px 11px;border-radius:7px;margin-right:7px;font-weight:700}}button.danger{{background:var(--red)}}.empty{{color:var(--muted)}}footer{{color:var(--muted);margin-top:20px}}
@media(max-width:760px){{.metrics{{grid-template-columns:1fr 1fr}}.grid{{grid-template-columns:1fr}}header{{display:block}}}}
</style></head><body><main><header><div><div class="sub">LOCAL · 127.0.0.1</div><h1>Mission <em>Control</em></h1><div class="sub">{html.escape(str(project))}</div></div><div class="pill">{html.escape(profile['name'])} · v{html.escape(data['config']['framework_version'])}</div></header>
<section class="metrics"><div class="metric"><strong>{len(pending)}</strong><span>Pending approvals</span></div><div class="metric"><strong>{len(queued)}</strong><span>Active tasks</span></div><div class="metric"><strong>{len(passed)}</strong><span>95+ QA passes</span></div><div class="metric"><strong>{'READY' if health['core_ready'] else 'DEGRADED'}</strong><span>Core health</span></div></section>
<section class="grid"><div class="panel"><h2>Approval queue</h2>{_cards(data['approvals'], 'No decisions waiting for approval.', 'approval')}</div>
<div class="panel"><h2>Tasks</h2>{_cards(data['tasks'], 'No tasks yet.', 'task')}</div>
<div class="panel"><h2>Independent Visual QA</h2>{_cards(data['qa'], 'No QA evidence yet.', 'qa')}</div>
<div class="panel"><h2>Session / Runner</h2>{_session_panel(data['session'])}</div>
<div class="panel"><h2>Capability health</h2><article><p>Android: {html.escape('ready' if health['android']['healthy'] else health['android']['reason'])}</p><p>iOS: {html.escape('ready' if health['ios']['healthy'] else health['ios']['reason'])}</p><p>Unity: {len(health['unity'])} installation(s)</p></article></div></section>
<section class="panel gallery" style="margin-top:18px"><h2>Asset gallery</h2><div class="gallery-grid">{gallery}</div></section>
<footer>Paid services and publishing never proceed without owner approval. This dashboard runs on localhost only.</footer>
<script>for(const f of document.forms){{const i=document.createElement('input');i.type='hidden';i.name='csrf';i.value='{token}';f.appendChild(i)}}</script></main></body></html>"""
    return body.encode("utf-8")


def make_handler(project: Path, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, content: bytes, content_type: str = "text/html; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self._send(200, page(project, token))
                return
            if parsed.path == "/api/status":
                self._send(200, json.dumps(snapshot(project), ensure_ascii=False).encode(), "application/json")
                return
            if parsed.path.startswith("/assets/"):
                rel = urllib.parse.unquote(parsed.path[len("/assets/"):])
                candidate = (project / "docs/studio/assets" / rel).resolve()
                root = (project / "docs/studio/assets").resolve()
                if root not in candidate.parents or not candidate.is_file():
                    self._send(404, b"not found", "text/plain")
                    return
                self._send(200, candidate.read_bytes(), mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            if self.path != "/approval":
                self._send(404, b"not found", "text/plain")
                return
            length = min(int(self.headers.get("Content-Length", "0")), 16384)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            if form.get("csrf", [""])[0] != token:
                self._send(HTTPStatus.FORBIDDEN, b"invalid csrf", "text/plain")
                return
            try:
                approval_decide(project, form["id"][0], form["decision"][0], "Mission Control")
            except Exception as exc:
                self._send(400, str(exc).encode(), "text/plain")
                return
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            return
    return Handler


def serve(project: Path, port: int = 8765) -> None:
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(project, token))
    print(f"Mission Control: http://127.0.0.1:{server.server_port}/")
    print("Local-only server. Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

