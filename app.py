"""Trainly's HTTP API and browser entry point."""

from __future__ import annotations

import asyncio
import json
import hashlib
import logging
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.templating import Jinja2Templates
from datetime import datetime

from data import (
    COOKIE_SECURE, FILES, ROOT, MAX_VIDEO_BYTES, MAX_VIDEO_SECONDS, attempt_snapshot, attempt_state, captions_vtt, db,
    finite_number, generated_draft, module_row, package, password_hash,
    password_matches, published_package, record_event,
)
from providers import ai_status
from data import explanation_link, invalidate_explanation_links

logger = logging.getLogger("trainly")


def handle_loop_exception(loop, context):
    """Ignore Windows sockets reset by a browser cancelling a media range.

    CPython's Proactor transport reports WSAECONNRESET while shutting down a
    socket after the client aborts a 206 response. The request already
    completed; only the transport teardown is noisy. Everything else still goes
    through the loop's normal exception handler.
    """
    error = context.get("exception")
    message = str(context.get("message", ""))
    if (
        isinstance(error, (ConnectionResetError, ConnectionAbortedError))
        and "_ProactorBasePipeTransport._call_connection_lost" in message
    ):
        return
    loop.default_exception_handler(context)


@asynccontextmanager
async def lifespan(_app):
    asyncio.get_running_loop().set_exception_handler(handle_loop_exception)
    yield


app = FastAPI(title="Trainly", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def response_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        # Never log request bodies, video paths, or transcript content here.
        logger.exception("Request failed: %s %s", request.method, request.url.path)
        raise
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@contextmanager
def connection():
    c = db()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


CALL_RING_SECONDS = 45
CALL_ACTIVE_RECONCILE_SECONDS = 4 * 60 * 60


class CallHub:
    """Per-process WebSocket presence and call event delivery.

    The MVP runs one app worker. Multi-worker deployments need a shared
    pub/sub channel instead of this in-memory registry.
    """

    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = {}

    def add(self, user_id: int, socket: WebSocket) -> None:
        self.connections.setdefault(user_id, set()).add(socket)

    def remove(self, user_id: int, socket: WebSocket) -> None:
        sockets = self.connections.get(user_id)
        if sockets:
            sockets.discard(socket)
            if not sockets:
                self.connections.pop(user_id, None)

    def online(self, user_id: int) -> bool:
        return bool(self.connections.get(user_id))

    async def send(self, user_id: int, message: dict, exclude=None) -> None:
        for socket in list(self.connections.get(user_id, ())):
            if socket is exclude:
                continue
            try:
                await socket.send_json(message)
            except Exception:
                self.remove(user_id, socket)


hub = CallHub()


def configured_ice_servers():
    servers = []
    stun_urls = [url.strip() for url in os.environ.get("TRAINLY_STUN_URLS", "stun:stun.l.google.com:19302").split(",") if url.strip()]
    if stun_urls:
        servers.append({"urls": stun_urls})
    turn_urls = [url.strip() for url in os.environ.get("TRAINLY_TURN_URLS", "").split(",") if url.strip()]
    if turn_urls:
        server = {"urls": turn_urls}
        username = os.environ.get("TRAINLY_TURN_USERNAME", "").strip()
        credential = os.environ.get("TRAINLY_TURN_CREDENTIAL", "").strip()
        if username:
            server["username"] = username
        if credential:
            server["credential"] = credential
        servers.append(server)
    return servers


def video_size_label():
    if MAX_VIDEO_BYTES >= 1024 ** 3:
        return f"{MAX_VIDEO_BYTES / (1024 ** 3):g} GiB"
    if MAX_VIDEO_BYTES >= 1024 ** 2:
        return f"{MAX_VIDEO_BYTES / (1024 ** 2):g} MiB"
    return f"{MAX_VIDEO_BYTES} bytes"


@app.exception_handler(HTTPException)
async def api_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)


async def body_json(request: Request):
    try:
        value = await request.json()
    except (ValueError, UnicodeDecodeError):
        fail(400, "Check the saved details.")
    if not isinstance(value, dict):
        fail(400, "Check the saved details.")
    return value


def user_for_session(token):
    if not token:
        return None
    with connection() as c:
        row = c.execute(
            "SELECT users.*, sessions.token, sessions.csrf, sessions.expires, "
            "memberships.workspace_id, memberships.role AS workspace_role "
            "FROM sessions JOIN users ON users.id=sessions.user_id "
            "JOIN memberships ON memberships.user_id=users.id WHERE token=?",
            (token,),
        ).fetchone()
        return dict(row) if row and row["expires"] >= int(time.time()) else None


def current_user(request: Request):
    return user_for_session(request.cookies.get("trainly"))


def require_user(user=Depends(current_user)):
    if not user:
        fail(401, "Sign in to continue.")
    return user


def require_csrf(request: Request, user=Depends(require_user)):
    if request.headers.get("X-CSRF-Token") != user["csrf"]:
        fail(403, "Session expired. Refresh and try again.")
    return user


def creator(user=Depends(require_csrf)):
    if user["workspace_role"] != "creator":
        fail(403, "Creator access is required.")
    return user


def creator_read(user=Depends(require_user)):
    if user["workspace_role"] != "creator":
        fail(403, "Creator access is required.")
    return user


def admin(user=Depends(require_csrf)):
    if user["role"] != "admin" or user["workspace_role"] != "admin":
        fail(403, "Admin access is required.")
    return user


def admin_read(user=Depends(require_user)):
    if user["role"] != "admin" or user["workspace_role"] != "admin":
        fail(403, "Admin access is required.")
    return user


def owned_module(c, mid, user):
    m = module_row(c, mid)
    if not m:
        fail(404, "Module not found.")
    if user["workspace_role"] != "creator" or m["workspace_id"] != user["workspace_id"] or m["owner"] != user["id"]:
        fail(403, "Creator access is required.")
    return m


def valid_check_timestamp(c, mid, m, at):
    """A knowledge check sits inside a lesson or at the end of the video."""
    if at is None or at < 0 or (m["duration"] and at > m["duration"]):
        return False
    lessons = c.execute("SELECT start,end FROM lessons WHERE module_id=? ORDER BY start", (mid,)).fetchall()
    if not lessons:
        return True
    if m["duration"] and at == m["duration"]:
        return True
    return any(lesson["start"] <= at <= lesson["end"] for lesson in lessons)


def can_view(c, m, user):
    if not user or m["workspace_id"] != user["workspace_id"]:
        return False
    if user["workspace_role"] == "creator" and m["owner"] == user["id"]:
        return True
    return bool(
        user["workspace_role"] == "learner" and m["status"] == "published"
        and c.execute("SELECT 1 FROM assignments WHERE module_id=? AND learner=?", (m["id"], user["id"])).fetchone()
    )


CALL_QUERY = """SELECT calls.*, modules.title AS module_title,
    learner.name AS learner_name, learner.email AS learner_email,
    creator.name AS creator_name, creator.email AS creator_email
    FROM calls JOIN modules ON modules.id=calls.module_id
    JOIN users learner ON learner.id=calls.learner
    JOIN users creator ON creator.id=calls.creator"""


def call_row(c, call_id):
    return c.execute(CALL_QUERY + " WHERE calls.id=?", (call_id,)).fetchone()


def public_call(c, row):
    return {
        "id": row["id"],
        "module": {"id": row["module_id"], "title": row["module_title"]},
        "learner": {"id": row["learner"], "name": row["learner_name"], "email": row["learner_email"]},
        "creator": {"id": row["creator"], "name": row["creator_name"], "email": row["creator_email"]},
        "initiated_by": row["initiated_by"],
        "status": row["status"],
        "created_at": row["created_at"],
        "accepted_at": row["accepted_at"],
        "ended_at": row["ended_at"],
        "duration": row["duration"],
        "failure_reason": row["failure_reason"],
        "learner_online": hub.online(row["learner"]),
        "creator_online": hub.online(row["creator"]),
    }


def reconcile_calls(c):
    """Close calls that can no longer be answered or have gone stale."""
    now = int(time.time())
    c.execute(
        "UPDATE calls SET status='missed',updated_at=?,ended_at=COALESCE(ended_at,?),failure_reason='No answer' "
        "WHERE status='ringing' AND created_at<?",
        (now, now, now - CALL_RING_SECONDS),
    )
    c.execute(
        "UPDATE calls SET status='ended',updated_at=?,ended_at=COALESCE(ended_at,?),"
        "duration=COALESCE(duration,?-COALESCE(accepted_at,created_at)) "
        "WHERE status='active' AND updated_at<?",
        (now, now, now, now - CALL_ACTIVE_RECONCILE_SECONDS),
    )


def busy_with_call(c, user_id, exclude=None):
    query = "SELECT 1 FROM calls WHERE status IN ('ringing','active') AND (learner=? OR creator=?)"
    params = [user_id, user_id]
    if exclude:
        query += " AND id<>?"
        params.append(exclude)
    return bool(c.execute(query, params).fetchone())


def call_initiator(row):
    return row["learner"] if row["initiated_by"] == "learner" else row["creator"]


def call_callee(row):
    return row["creator"] if row["initiated_by"] == "learner" else row["learner"]


def finish_call(c, row, status, user_id, reason=None):
    now = int(time.time())
    duration = None
    if status in ("ended", "failed") and row["accepted_at"]:
        duration = max(0, now - row["accepted_at"])
    c.execute(
        "UPDATE calls SET status=?,updated_at=?,ended_at=?,duration=?,ended_by=?,failure_reason=? WHERE id=?",
        (status, now, now, duration, user_id, reason, row["id"]),
    )


templates = Jinja2Templates(directory=str(ROOT / 'templates'))
templates.env.filters['date'] = lambda value: datetime.fromtimestamp(value).strftime('%Y-%m-%d') if value else '\u2014'
templates.env.filters['video_time'] = lambda value: f'{int(value or 0) // 60}:{int(value or 0) % 60:02d}'


def page_context(user, admin_mode=False):
    context = dict(user=user, admin_mode=admin_mode, now=int(time.time()))
    if not user:
        context['page_template'] = 'login.html'
    elif user['workspace_role'] == 'admin':
        context.update(admin_accounts(user))
        context.update(page_template='shell.html', content_template='admin_home.html')
    else:
        context.update(modules=modules(user), page_template='shell.html',
                       content_template='creator_home.html' if user['workspace_role'] == 'creator' else 'learner_home.html')
    return context


@app.get('/', response_class=HTMLResponse)
@app.get('/index.html', response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, 'index.html', page_context(current_user(request)))


@app.get('/admin', response_class=HTMLResponse)
def admin_page(request: Request):
    user = current_user(request)
    if user and (user['role'] != 'admin' or user['workspace_role'] != 'admin'):
        return templates.TemplateResponse(request, 'index.html', {'page_template': 'access_denied.html'}, status_code=403)
    return templates.TemplateResponse(request, 'index.html', page_context(user, admin_mode=True))


@app.get('/setup', response_class=HTMLResponse)
def setup_page(request: Request):
    return templates.TemplateResponse(request, 'index.html', {'page_template': 'setup_pending.html'})


@app.get('/views/login', response_class=HTMLResponse)
def login_view(request: Request, admin_mode: bool = False):
    return templates.TemplateResponse(request, 'login.html', {'admin_mode': admin_mode})


@app.post('/views/invitation', response_class=HTMLResponse)
async def invitation_view(request: Request):
    return templates.TemplateResponse(request, 'invitation.html', {'info': await get_invitation(request)})


@app.post('/views/account-setup', response_class=HTMLResponse)
async def account_setup_view(request: Request):
    return templates.TemplateResponse(request, 'account_setup.html', {'info': await inspect_account_setup(request)})


@app.get('/views/home', response_class=HTMLResponse)
def home_view(request: Request, user=Depends(require_user)):
    context = page_context(user)
    return templates.TemplateResponse(request, 'shell.html', context)


@app.get('/views/modules', response_class=HTMLResponse)
def modules_view(request: Request, user=Depends(creator_read)):
    return templates.TemplateResponse(request, 'modules.html', {'modules': modules(user)})


@app.get('/views/results', response_class=HTMLResponse)
def results_view(request: Request, mid: str | None = None, user=Depends(creator_read)):
    if mid:
        rows = results(mid, user)
        module = get_module(mid, user)
    else:
        module, rows = None, []
        for item in modules(user):
            if item['status'] == 'published':
                rows.extend(dict(row, module_title=item['title']) for row in results(item['id'], user))
    context = {'rows': rows, 'module': module, 'user': user, 'content_template': 'results.html'}
    return templates.TemplateResponse(request, 'shell.html' if mid else 'results.html', context)


@app.get('/views/editor/{mid}', response_class=HTMLResponse)
def editor_view(mid: str, request: Request, user=Depends(creator_read)):
    with connection() as session:
        owned_module(session, mid, user)
        draft = generated_draft(session, mid)
    module = get_module(mid, user)
    module['lessons'] = [lesson for lesson in module['lessons'] if not (
        lesson['title'] == 'Introduction' and lesson['summary'] == 'Add a short overview for learners.'
        and lesson['start'] == 0 and lesson['end'] == 0
    )]
    return templates.TemplateResponse(request, 'shell.html', {
        'user': user, 'content_template': 'editor.html', 'module': module,
        'config': config(), 'draft': draft,
    })


@app.get('/views/player/{mid}', response_class=HTMLResponse)
def player_view(mid: str, request: Request, attempt_id: str, user=Depends(require_user)):
    module = get_module(mid, user)
    with connection() as session:
        attempt = owned_attempt(session, attempt_id, user)
        if attempt['module_id'] != mid:
            fail(404, 'Attempt not found.')
        state = attempt_state(session, attempt)
        module = attempt_snapshot(session, attempt)
        for question in module['questions']:
            question.pop('answer', None)
    initial = next((lesson for lesson in module['lessons'] if lesson['start'] <= state['position'] < lesson['end']),
                   module['lessons'][0] if module['lessons'] else None)
    return templates.TemplateResponse(request, 'shell.html', {
        'user': user, 'content_template': 'player.html', 'module': module,
        'attempt': state, 'initial': initial,
    })


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(ROOT / "static" / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    return FileResponse(ROOT / "static" / "favicon.ico", media_type="image/x-icon")


@app.get("/app.css")
def css():
    return FileResponse(ROOT / "static" / "app.css", media_type="text/css")


@app.get("/app.js")
def javascript():
    return FileResponse(ROOT / "static" / "app.js", media_type="text/javascript")


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"user": {k: user[k] for k in ("id", "name", "email", "role")}, "csrf": user["csrf"]} if user else {"user": None}


@app.get("/api/config")
def config():
    return {
        "max_video_bytes": MAX_VIDEO_BYTES,
        "max_video_seconds": MAX_VIDEO_SECONDS,
        "default_pass_score": 70,
        "ice_servers": configured_ice_servers(),
        "call_ring_seconds": CALL_RING_SECONDS,
        **ai_status(),
    }


@app.post("/api/login")
async def login(request: Request):
    data = await body_json(request)
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str) or not email.strip() or not password:
        fail(400, "Enter your login details.")
    email = email.strip()
    with connection() as c:
        row = c.execute("SELECT users.*, memberships.workspace_id, memberships.role AS workspace_role FROM users JOIN memberships ON memberships.user_id=users.id WHERE email=?", (email.lower(),)).fetchone()
        if not row or not password_matches(password, row["password"]):
            fail(401, "Email or password is incorrect.")
        if not row["password"].startswith("pbkdf2_sha256$"):
            c.execute("UPDATE users SET password=? WHERE id=?", (password_hash(password), row["id"]))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        c.execute("DELETE FROM sessions WHERE expires<?", (int(time.time()),))
        c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token, row["id"], csrf, int(time.time()) + 86400 * 14))
        public_user = {k: row[k] for k in ("id", "name", "email", "role")}
    response = JSONResponse({"user": public_user, "csrf": csrf})
    response.set_cookie("trainly", token, max_age=1209600, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return response


@app.post("/api/logout")
def logout(user=Depends(require_csrf)):
    with connection() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (user["token"],))
    response = JSONResponse({"ok": True})
    response.delete_cookie("trainly", secure=COOKIE_SECURE, samesite="lax")
    return response


EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def valid_email(value):
    return isinstance(value, str) and bool(EMAIL_PATTERN.fullmatch(value.strip()))


def issue_account_setup(c, user_id, now=None):
    """Create a one-time setup token. Only its hash is stored."""
    now = int(time.time()) if now is None else now
    token = secrets.token_urlsafe(32)
    expires = now + 7 * 86400
    c.execute("DELETE FROM account_setups WHERE user_id=? AND accepted IS NULL", (user_id,))
    c.execute(
        "INSERT INTO account_setups(token_hash,user_id,created_at,expires) VALUES(?,?,?,?)",
        (hashlib.sha256(token.encode()).hexdigest(), user_id, now, expires),
    )
    return token, expires


def account_row(c, account_id):
    return c.execute(
        "SELECT users.id,users.name,users.email,users.role,"
        "memberships.workspace_id,memberships.role AS workspace_role,"
        "workspaces.name AS workspace_name,"
        "(SELECT expires FROM account_setups s WHERE s.user_id=users.id AND s.accepted IS NULL ORDER BY s.expires DESC LIMIT 1) AS setup_expires,"
        "(SELECT accepted FROM account_setups s WHERE s.user_id=users.id AND s.accepted IS NOT NULL ORDER BY s.accepted DESC LIMIT 1) AS setup_completed "
        "FROM users JOIN memberships ON memberships.user_id=users.id "
        "JOIN workspaces ON workspaces.id=memberships.workspace_id WHERE users.id=?",
        (account_id,),
    ).fetchone()


def public_account(row):
    if not row:
        return None
    item = dict(row)
    item["setup_pending"] = item["setup_expires"] is not None and not item["setup_completed"]
    return item


@app.get("/api/admin/accounts")
def admin_accounts(user=Depends(admin_read)):
    with connection() as c:
        rows = c.execute(
            "SELECT users.id FROM users JOIN memberships ON memberships.user_id=users.id "
            "JOIN workspaces ON workspaces.id=memberships.workspace_id "
            "ORDER BY workspaces.name,users.name"
        ).fetchall()
        accounts = [public_account(account_row(c, row["id"])) for row in rows]
        workspaces = [dict(row) for row in c.execute("SELECT id,name FROM workspaces ORDER BY name")]
    return {"accounts": accounts, "workspaces": workspaces}


@app.post("/api/admin/accounts", status_code=201)
async def create_admin_account(request: Request, user=Depends(admin)):
    data = await body_json(request)
    name, email, role, workspace_id = data.get("name"), data.get("email"), data.get("role"), data.get("workspace_id")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        fail(400, "Enter the account holder's name.")
    if not valid_email(email):
        fail(400, "Enter a valid email address.")
    if role not in ("creator", "learner"):
        fail(400, "Choose creator or learner access.")
    if not isinstance(workspace_id, str) or not workspace_id:
        fail(400, "Choose a workspace for this account.")
    email = email.strip().lower()
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        if not c.execute("SELECT 1 FROM workspaces WHERE id=?", (workspace_id,)).fetchone():
            fail(400, "Choose an existing workspace for this account.")
        if c.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
            fail(409, "An account already uses that email.")
        cursor = c.execute(
            "INSERT INTO users(email,name,password,role) VALUES(?,?,?,?)",
            (email, name.strip(), password_hash(secrets.token_urlsafe(32)), role),
        )
        account_id = cursor.lastrowid
        c.execute("INSERT INTO memberships(workspace_id,user_id,role) VALUES(?,?,?)", (workspace_id, account_id, role))
        token, expires = issue_account_setup(c, account_id)
        record_event(c, "account_created", workspace_id, user["id"], None, {"account_id": account_id, "role": role})
        account = public_account(account_row(c, account_id))
    return {"account": account, "token": token, "expires": expires}


@app.post("/api/admin/accounts/{account_id}/setup", status_code=201)
def reissue_account_setup(account_id: int, user=Depends(admin)):
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        account = account_row(c, account_id)
        if not account:
            fail(404, "Account not found.")
        completed = c.execute("SELECT 1 FROM account_setups WHERE user_id=? AND accepted IS NOT NULL", (account_id,)).fetchone()
        if completed:
            fail(409, "This account has completed first-time setup. It cannot be reset here.")
        if not c.execute("SELECT 1 FROM account_setups WHERE user_id=?", (account_id,)).fetchone():
            fail(409, "This account did not use an administrator setup link.")
        token, expires = issue_account_setup(c, account_id)
        record_event(c, "account_setup_reissued", account["workspace_id"], user["id"], None, {"account_id": account_id})
    return {"token": token, "expires": expires}


def pending_account_setup(c, token):
    if not isinstance(token, str) or not token or len(token) > 128:
        fail(404, "Setup link not found.")
    setup = c.execute(
        "SELECT account_setups.*,users.name,users.email,users.role,memberships.workspace_id,"
        "memberships.role AS workspace_role,workspaces.name AS workspace_name "
        "FROM account_setups JOIN users ON users.id=account_setups.user_id "
        "JOIN memberships ON memberships.user_id=users.id "
        "JOIN workspaces ON workspaces.id=memberships.workspace_id WHERE token_hash=?",
        (hashlib.sha256(token.encode()).hexdigest(),),
    ).fetchone()
    if not setup:
        fail(404, "Setup link not found.")
    if setup["accepted"] or setup["expires"] < int(time.time()):
        fail(410, "This setup link has expired or was already used.")
    return setup


@app.post("/api/account-setup/inspect")
async def inspect_account_setup(request: Request):
    data = await body_json(request)
    with connection() as c:
        setup = pending_account_setup(c, data.get("token"))
        return {
            "email": setup["email"], "name": setup["name"], "role": setup["role"],
            "workspace": setup["workspace_name"], "expires": setup["expires"],
        }


@app.post("/api/account-setup/complete")
async def complete_account_setup(request: Request):
    data = await body_json(request)
    name, password = data.get("name"), data.get("password")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100 or not isinstance(password, str) or len(password) < 8:
        fail(400, "Enter your name and a password of at least 8 characters.")
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        setup = pending_account_setup(c, data.get("token"))
        if setup["role"] not in ("creator", "learner"):
            fail(403, "This account cannot complete setup here.")
        c.execute("UPDATE users SET name=?,password=? WHERE id=?", (name.strip(), password_hash(password), setup["user_id"]))
        c.execute("UPDATE account_setups SET accepted=? WHERE token_hash=?", (int(time.time()), setup["token_hash"]))
        c.execute("DELETE FROM account_setups WHERE user_id=? AND accepted IS NULL", (setup["user_id"],))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token, setup["user_id"], csrf, int(time.time()) + 86400 * 14))
        public_user = {"id": setup["user_id"], "name": name.strip(), "email": setup["email"], "role": setup["role"]}
        record_event(c, "account_setup_completed", setup["workspace_id"], setup["user_id"], None, {"role": setup["role"]})
    response = JSONResponse({"user": public_user, "csrf": csrf})
    response.set_cookie("trainly", token, max_age=1209600, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return response


@app.get("/api/learners")
def learners(user=Depends(require_user)):
    if user["workspace_role"] != "creator":
        fail(403, "Creator access is required.")
    with connection() as c:
        return [dict(r) for r in c.execute("SELECT users.id,users.name,users.email FROM users JOIN memberships ON memberships.user_id=users.id WHERE memberships.workspace_id=? AND memberships.role='learner' ORDER BY users.name", (user["workspace_id"],))]


@app.get("/api/modules")
def modules(user=Depends(require_user)):
    with connection() as c:
        if user["workspace_role"] == "learner":
            rows = c.execute('SELECT modules.* FROM modules JOIN assignments ON assignments.module_id=modules.id WHERE modules.status="published" AND modules.workspace_id=? AND assignments.learner=? ORDER BY modules.published_at DESC', (user["workspace_id"], user["id"])).fetchall()
        else:
            rows = c.execute('SELECT * FROM modules WHERE workspace_id=? AND owner=? ORDER BY published_at DESC', (user["workspace_id"], user["id"])).fetchall()
        result = []
        for m in rows:
            owned = user["workspace_role"] == "creator" and m["owner"] == user["id"]
            item = package(c, m, True) if owned else published_package(c, m)
            item["completed"] = bool(c.execute("SELECT 1 FROM attempts WHERE module_id=? AND version=? AND learner=? AND completed IS NOT NULL", (m["id"], m["published_version"], user["id"])).fetchone())
            result.append(item)
        return result


@app.post("/api/modules", status_code=201)
async def create_module(request: Request, user=Depends(creator)):
    data = await body_json(request)
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        fail(400, "Add a module title first.")
    mid = uuid.uuid4().hex[:12]
    with connection() as c:
        c.execute("INSERT INTO modules(id,owner,workspace_id,title,description) VALUES(?,?,?,?,?)", (mid, user["id"], user["workspace_id"], title.strip(), data.get("description", "")))
        record_event(c, "module_created", user["workspace_id"], user["id"], mid)
        return package(c, module_row(c, mid), True)


@app.get("/api/modules/{mid}")
def get_module(mid: str, user=Depends(require_user)):
    with connection() as c:
        m = module_row(c, mid)
        if not m:
            fail(404, "Module not found.")
        if not can_view(c, m, user):
            fail(403, "You do not have access to this module.")
        if m["owner"] == user["id"] and user["workspace_role"] == "creator":
            result = package(c, m, True)
            if m["upload_job_id"]:
                job = c.execute("SELECT id,state,stage,retry_count,duration,error,transcript_state,draft_state,provider,message FROM processing_jobs WHERE id=? AND module_id=?", (m["upload_job_id"], mid)).fetchone()
                result["upload_job"] = dict(job) if job else None
            return result
        return published_package(c, m)


@app.delete("/api/modules/{mid}", status_code=204)
def delete_module(mid: str, user=Depends(creator)):
    with connection() as c:
        owned_module(c, mid, user)
        paths = set()
        for row in c.execute("SELECT source_path,playback_path FROM media_assets WHERE module_id=?", (mid,)):
            paths.update(value for value in row if value)
        for row in c.execute("SELECT asset FROM processing_jobs WHERE module_id=?", (mid,)):
            paths.add(row["asset"])
        for row in c.execute("SELECT audio_path FROM processing_jobs WHERE module_id=?", (mid,)):
            paths.add(row["audio_path"])
        c.execute("DELETE FROM invitations WHERE module_id=?", (mid,))
        c.execute("DELETE FROM answers WHERE attempt_id IN (SELECT id FROM attempts WHERE module_id=?)", (mid,))
        c.execute("DELETE FROM attempt_progress WHERE attempt_id IN (SELECT id FROM attempts WHERE module_id=?)", (mid,))
        c.execute("DELETE FROM attempts WHERE module_id=?", (mid,))
        c.execute("DELETE FROM calls WHERE module_id=?", (mid,))
        c.execute("DELETE FROM module_versions WHERE module_id=?", (mid,))
        c.execute("DELETE FROM modules WHERE id=?", (mid,))
        record_event(c, "module_deleted", user["workspace_id"], user["id"], mid)
    for name in paths:
        if name:
            (FILES / Path(name).name).unlink(missing_ok=True)


@app.get("/api/modules/{mid}/results")
def results(mid: str, user=Depends(require_user)):
    with connection() as c:
        m = owned_module(c, mid, user)
        rows = c.execute('''SELECT users.name,users.email,
            (SELECT score FROM attempts x WHERE x.module_id=assignments.module_id AND x.learner=assignments.learner ORDER BY started DESC, x.rowid DESC LIMIT 1) AS score,
            (SELECT started FROM attempts x WHERE x.module_id=assignments.module_id AND x.learner=assignments.learner ORDER BY started DESC, x.rowid DESC LIMIT 1) AS started,
            (SELECT completed FROM attempts x WHERE x.module_id=assignments.module_id AND x.learner=assignments.learner ORDER BY started DESC, x.rowid DESC LIMIT 1) AS completed_at,
            (SELECT COUNT(*) FROM attempts x WHERE x.module_id=assignments.module_id AND x.learner=assignments.learner) AS attempt_count
            FROM assignments JOIN users ON users.id=assignments.learner WHERE assignments.module_id=? ORDER BY users.name''', (mid,)).fetchall()
        result = []
        for r in rows:
            completed = bool(r["completed_at"])
            passed = bool(completed and (r["score"] or 0) >= m["pass_score"])
            result.append(dict(
                name=r["name"], email=r["email"], completed=completed,
                status="completed" if completed else "in_progress" if r["started"] else "not_started",
                outcome="passed" if passed else "not_passed" if completed else "in_progress" if r["started"] else "not_started",
                passed=passed, pass_score=m["pass_score"], score=r["score"], started=r["started"],
                completed_at=r["completed_at"], attempt_count=r["attempt_count"],
            ))
        return result


@app.post("/api/modules/{mid}/assign")
async def assign(mid: str, request: Request, user=Depends(creator)):
    data = await body_json(request)
    email = data.get("email", "")
    with connection() as c:
        m = owned_module(c, mid, user)
        if m["status"] != "published":
            fail(400, "Publish this module before assigning learners.")
        learner = c.execute("SELECT users.id FROM users JOIN memberships ON memberships.user_id=users.id WHERE users.email=? AND memberships.workspace_id=? AND memberships.role='learner'", (email.lower() if isinstance(email, str) else "", user["workspace_id"])).fetchone()
        if not learner:
            fail(404, "No learner account found for that email.")
        c.execute("INSERT OR IGNORE INTO assignments(module_id,learner,assigned_at) VALUES(?,?,?)", (mid, learner["id"], int(time.time())))
        record_event(c, "learner_assigned", user["workspace_id"], user["id"], mid, {"learner_id": learner["id"]})
    return {"ok": True}


@app.post("/api/invitations", status_code=201)
async def create_invitation(request: Request, user=Depends(creator)):
    data = await body_json(request)
    email = data.get("email")
    mid = data.get("module_id")
    if not isinstance(email, str) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()) or not isinstance(mid, str):
        fail(400, "Enter a learner email and choose a module.")
    email = email.strip().lower()
    with connection() as c:
        module = owned_module(c, mid, user)
        if module["status"] != "published":
            fail(400, "Publish this module before inviting learners.")
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            fail(409, "An account already uses that email. Assign an existing learner instead.")
        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + 7 * 86400
        c.execute("INSERT INTO invitations(token_hash,workspace_id,email,role,module_id,created_by,expires) VALUES(?,?,?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["workspace_id"], email, "learner", mid, user["id"], expires))
        record_event(c, "learner_invited", user["workspace_id"], user["id"], mid)
    return {"token": token, "email": email, "expires": expires}


def pending_invitation(c, token):
    if not isinstance(token, str) or len(token) > 128:
        fail(404, "Invitation not found.")
    invite = c.execute("SELECT invitations.*,workspaces.name AS workspace_name,modules.title AS module_title FROM invitations JOIN workspaces ON workspaces.id=invitations.workspace_id LEFT JOIN modules ON modules.id=invitations.module_id WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not invite:
        fail(404, "Invitation not found.")
    if invite["accepted"] or invite["expires"] < int(time.time()):
        fail(410, "This invitation has expired or was already used.")
    return invite


@app.post("/api/invitations/inspect")
async def get_invitation(request: Request):
    data = await body_json(request)
    with connection() as c:
        invite = pending_invitation(c, data.get("token"))
        return {"email": invite["email"], "workspace": invite["workspace_name"], "module": invite["module_title"], "expires": invite["expires"]}


@app.post("/api/invitations/accept")
async def accept_invitation(request: Request):
    data = await body_json(request)
    name, password = data.get("name"), data.get("password")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100 or not isinstance(password, str) or len(password) < 8:
        fail(400, "Enter your name and a password of at least 8 characters.")
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        invite = pending_invitation(c, data.get("token"))
        if c.execute("SELECT 1 FROM users WHERE email=?", (invite["email"],)).fetchone():
            fail(409, "An account already uses this email.")
        cursor = c.execute("INSERT INTO users(email,name,password,role) VALUES(?,?,?,?)", (invite["email"], name.strip(), password_hash(password), invite["role"]))
        user_id = cursor.lastrowid
        c.execute("INSERT INTO memberships(workspace_id,user_id,role) VALUES(?,?,?)", (invite["workspace_id"], user_id, invite["role"]))
        if invite["module_id"]:
            c.execute("INSERT INTO assignments(module_id,learner,assigned_at) VALUES(?,?,?)", (invite["module_id"], user_id, int(time.time())))
        c.execute("UPDATE invitations SET accepted=? WHERE token_hash=?", (int(time.time()), invite["token_hash"]))
        record_event(c, "learner_joined", invite["workspace_id"], user_id, invite["module_id"])
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token, user_id, csrf, int(time.time()) + 86400 * 14))
        public_user = {"id": user_id, "name": name.strip(), "email": invite["email"], "role": invite["role"]}
    response = JSONResponse({"user": public_user, "csrf": csrf})
    response.set_cookie("trainly", token, max_age=1209600, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return response


@app.get("/api/calls")
async def list_calls(user=Depends(require_user)):
    if user["workspace_role"] not in ("creator", "learner"):
        fail(403, "Call access is required.")
    with connection() as c:
        reconcile_calls(c)
        column = "creator" if user["workspace_role"] == "creator" else "learner"
        rows = c.execute(
            CALL_QUERY + f" WHERE calls.{column}=? ORDER BY calls.created_at DESC,calls.id DESC LIMIT 100",
            (user["id"],),
        ).fetchall()
        return [public_call(c, row) for row in rows]


@app.post("/api/calls", status_code=201)
async def start_call(request: Request, user=Depends(require_csrf)):
    data = await body_json(request)
    mid = data.get("module_id")
    if not isinstance(mid, str) or not mid:
        fail(400, "Choose a module to call about.")
    creator_id = None
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        m = module_row(c, mid)
        if not m or not m["owner"] or user["workspace_role"] != "learner" or not can_view(c, m, user):
            fail(404, "Assigned published module not found.")
        creator_id = m["owner"]
        reconcile_calls(c)
        if busy_with_call(c, user["id"]) or busy_with_call(c, creator_id):
            fail(409, "A call is already in progress. Try again when it ends.")
        now = int(time.time())
        call_id = uuid.uuid4().hex
        online = hub.online(creator_id)
        status = "ringing" if online else "missed"
        c.execute(
            "INSERT INTO calls(id,workspace_id,module_id,learner,creator,initiated_by,status,created_at,updated_at,ended_at,failure_reason) "
            "VALUES(?,?,?,?,?,'learner',?,?,?,?,?)",
            (call_id, user["workspace_id"], mid, user["id"], creator_id, status, now, now, None if online else now, None if online else "Creator offline"),
        )
        result = public_call(c, call_row(c, call_id))
        record_event(c, "call_started", user["workspace_id"], user["id"], mid, {"call_id": call_id, "creator_online": online})
    if result["status"] == "ringing":
        await hub.send(creator_id, {"type": "call.incoming", "call": result})
    return result


@app.post("/api/calls/{call_id}/accept")
async def accept_call(call_id: str, user=Depends(require_csrf)):
    initiator_id = None
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        row = call_row(c, call_id)
        if not row or call_callee(row) != user["id"]:
            fail(404, "Call not found.")
        if row["status"] != "ringing":
            fail(409, "This call is no longer ringing.")
        if row["created_at"] < int(time.time()) - CALL_RING_SECONDS:
            fail(410, "This call timed out.")
        if busy_with_call(c, row["learner"], exclude=row["id"]) or busy_with_call(c, row["creator"], exclude=row["id"]):
            fail(409, "A call is already in progress. Try again when it ends.")
        now = int(time.time())
        c.execute("UPDATE calls SET status='active',accepted_at=?,updated_at=?,failure_reason=NULL WHERE id=?", (now, now, call_id))
        result = public_call(c, call_row(c, call_id))
        initiator_id = call_initiator(row)
        record_event(c, "call_accepted", user["workspace_id"], user["id"], row["module_id"], {"call_id": call_id})
    await hub.send(initiator_id, {"type": "call.accepted", "call": result})
    await hub.send(user["id"], {"type": "call.handled", "call": result})
    return result


@app.post("/api/calls/{call_id}/decline")
async def decline_call(call_id: str, user=Depends(require_csrf)):
    initiator_id = None
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        row = call_row(c, call_id)
        if not row or call_callee(row) != user["id"]:
            fail(404, "Call not found.")
        if row["status"] != "ringing":
            fail(409, "This call is no longer ringing.")
        finish_call(c, row, "declined", user["id"], "Declined")
        result = public_call(c, call_row(c, call_id))
        initiator_id = call_initiator(row)
        record_event(c, "call_declined", user["workspace_id"], user["id"], row["module_id"], {"call_id": call_id})
    await hub.send(initiator_id, {"type": "call.declined", "call": result})
    await hub.send(user["id"], {"type": "call.handled", "call": result})
    return result


@app.post("/api/calls/{call_id}/cancel")
async def cancel_call(call_id: str, request: Request, user=Depends(require_csrf)):
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    missed = bool(data.get("missed"))
    callee_id = None
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        row = call_row(c, call_id)
        if not row or call_initiator(row) != user["id"]:
            fail(404, "Call not found.")
        if row["status"] != "ringing":
            fail(409, "This call is no longer ringing.")
        status = "missed" if missed else "cancelled"
        finish_call(c, row, status, user["id"], "No answer" if missed else "Cancelled")
        result = public_call(c, call_row(c, call_id))
        callee_id = call_callee(row)
        record_event(c, "call_missed" if missed else "call_cancelled", user["workspace_id"], user["id"], row["module_id"], {"call_id": call_id})
    await hub.send(callee_id, {"type": "call.missed" if missed else "call.cancelled", "call": result})
    return result


@app.post("/api/calls/{call_id}/end")
async def end_call(call_id: str, request: Request, user=Depends(require_csrf)):
    data = await body_json(request)
    failed = bool(data.get("failed"))
    peer_id = None
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        row = call_row(c, call_id)
        if not row or user["id"] not in (row["learner"], row["creator"]):
            fail(404, "Call not found.")
        if row["status"] != "active":
            fail(409, "This call is no longer active.")
        finish_call(c, row, "failed" if failed else "ended", user["id"], "Connection failed" if failed else None)
        result = public_call(c, call_row(c, call_id))
        peer_id = row["creator"] if user["id"] == row["learner"] else row["learner"]
        record_event(c, "call_ended", user["workspace_id"], user["id"], row["module_id"], {"call_id": call_id, "failed": failed})
    await hub.send(peer_id, {"type": "call.ended", "call": result})
    return result


@app.post("/api/calls/{call_id}/callback", status_code=201)
async def call_back(call_id: str, user=Depends(require_csrf)):
    learner_id = None
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        original = call_row(c, call_id)
        if not original or original["creator"] != user["id"] or user["workspace_role"] != "creator":
            fail(404, "Call not found.")
        module = module_row(c, original["module_id"])
        if not module or module["owner"] != user["id"]:
            fail(404, "Module not found.")
        if not c.execute(
            "SELECT 1 FROM assignments WHERE module_id=? AND learner=?",
            (original["module_id"], original["learner"]),
        ).fetchone():
            fail(409, "This learner is no longer assigned to the module.")
        reconcile_calls(c)
        if busy_with_call(c, original["learner"]) or busy_with_call(c, original["creator"]):
            fail(409, "A call is already in progress. Try again when it ends.")
        now = int(time.time())
        online = hub.online(original["learner"])
        status = "ringing" if online else "missed"
        new_id = uuid.uuid4().hex
        c.execute(
            "INSERT INTO calls(id,workspace_id,module_id,learner,creator,initiated_by,status,created_at,updated_at,ended_at,failure_reason) "
            "VALUES(?,?,?,?,?,'creator',?,?,?,?,?)",
            (new_id, user["workspace_id"], original["module_id"], original["learner"], user["id"], status, now, now, None if online else now, None if online else "Learner offline"),
        )
        result = public_call(c, call_row(c, new_id))
        learner_id = original["learner"]
        record_event(c, "call_callback_started", user["workspace_id"], user["id"], original["module_id"], {"call_id": new_id, "learner_online": online})
    if result["status"] == "ringing":
        await hub.send(learner_id, {"type": "call.incoming", "call": result})
    return result


@app.post("/api/modules/{mid}/upload")
async def upload(mid: str, file: UploadFile | None = File(None), user=Depends(creator)):
    with connection() as c:
        owned_module(c, mid, user)
    if file is None:
        fail(400, "Choose an MP4, MOV, or WebM video.")
    filename = Path(file.filename or "").name
    ext = Path(filename).suffix.lower()
    if ext not in (".mp4", ".mov", ".webm"):
        fail(400, "Choose an MP4, MOV, or WebM video.")
    job_id = uuid.uuid4().hex
    asset = f"{mid}-{job_id[:12]}{ext}"
    target = FILES / asset
    size = 0
    superseded_asset = None
    try:
        with target.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    fail(413, f"This video is larger than the {video_size_label()} limit.")
                stream.write(chunk)
        with connection() as c:
            owned_module(c, mid, user)
            now = int(time.time())
            c.execute("INSERT INTO media_assets(id,module_id,source_path,state,created_at) VALUES(?,?,?,'queued',?)", (job_id, mid, asset, now))
            c.execute("INSERT INTO processing_jobs(id,module_id,workspace_id,asset,filename,extension,stage,state,created_at,updated_at) VALUES(?,?,?,?,?,?,'inspection','queued',?,?)", (job_id, mid, user["workspace_id"], asset, filename, ext, now, now))
            previous = c.execute("SELECT upload_job_id FROM modules WHERE id=?", (mid,)).fetchone()["upload_job_id"]
            c.execute("UPDATE modules SET upload_job_id=? WHERE id=?", (job_id, mid))
            c.execute('UPDATE questions SET explanation_segments=NULL WHERE module_id=?', (mid,))
            if previous:
                old_job = c.execute("SELECT asset,state FROM processing_jobs WHERE id=?", (previous,)).fetchone()
                c.execute("UPDATE processing_jobs SET state='superseded',updated_at=? WHERE id=? AND state IN ('queued','failed')", (now, previous))
                if old_job and old_job["state"] in ("queued", "failed"):
                    superseded_asset = old_job["asset"]
                    c.execute("UPDATE media_assets SET state='superseded' WHERE id=?", (previous,))
            record_event(c, "video_uploaded", user["workspace_id"], user["id"], mid, {"job_id": job_id})
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    if superseded_asset:
        (FILES / Path(superseded_asset).name).unlink(missing_ok=True)
        (FILES / f"{Path(superseded_asset).stem}-playback.mp4").unlink(missing_ok=True)
        (FILES / f"{Path(superseded_asset).stem}-audio.wav").unlink(missing_ok=True)
    return JSONResponse({"ok": True, "job_id": job_id, "state": "queued", "message": "Upload complete. Video inspection is queued."}, status_code=202)


@app.get("/api/modules/{mid}/uploads/{job_id}")
def upload_status(mid: str, job_id: str, user=Depends(creator_read)):
    with connection() as c:
        owned_module(c, mid, user)
        job = c.execute("SELECT state,stage,retry_count,duration,error,filename,transcript_state,draft_state,provider,message FROM processing_jobs WHERE id=? AND module_id=? AND workspace_id=?", (job_id, mid, user["workspace_id"])).fetchone()
        if not job:
            fail(404, "Upload job not found.")
        result = dict(job)
        result["can_retry"] = result["state"] in ("failed", "ready") and bool(result["error"])
        result["has_draft"] = bool(c.execute("SELECT 1 FROM generated_drafts WHERE module_id=?", (mid,)).fetchone())
        return result


@app.post("/api/modules/{mid}/uploads/{job_id}/retry")
def retry_upload(mid: str, job_id: str, user=Depends(creator)):
    with connection() as c:
        owned_module(c, mid, user)
        job = c.execute("SELECT * FROM processing_jobs WHERE id=? AND module_id=? AND workspace_id=?", (job_id, mid, user["workspace_id"])).fetchone()
        if not job:
            fail(404, "Upload job not found.")
        if job["state"] != "failed" and not (job["state"] == "ready" and job["error"]):
            fail(409, "Only a failed video processing job can be retried.")
        current = c.execute("SELECT upload_job_id FROM modules WHERE id=?", (mid,)).fetchone()
        if not current or current["upload_job_id"] != job_id:
            fail(409, "A newer upload has replaced this job. Upload the video again to retry.")
        if not (FILES / Path(job["asset"]).name).is_file():
            fail(410, "The uploaded file is no longer available. Upload it again.")
        now = int(time.time())
        c.execute("UPDATE processing_jobs SET state='queued',stage='inspection',retry_count=retry_count+1,updated_at=?,claimed_at=NULL,error=NULL,message=NULL,transcript_state='pending',draft_state='pending' WHERE id=?", (now, job_id))
        c.execute("UPDATE media_assets SET state='queued' WHERE id=?", (job_id,))
        c.execute("UPDATE modules SET upload_job_id=? WHERE id=?", (job_id, mid))
        record_event(c, "video_retry_queued", user["workspace_id"], user["id"], mid, {"job_id": job_id})
    return {"ok": True, "state": "queued"}


def media_version(c, m, version):
    """Return (video, playback_video, transcript) for a draft or saved version."""
    if version is not None:
        if not str(version).isdigit() or m["status"] != "published":
            fail(404, "Missing media")
        saved = c.execute("SELECT video,playback_video,snapshot FROM module_versions WHERE module_id=? AND version=?", (m["id"], int(version))).fetchone()
        if not saved:
            fail(404, "Missing media")
        return saved["video"], saved["playback_video"], json.loads(saved["snapshot"]).get("transcript", [])
    if m["status"] == "published":
        saved = c.execute("SELECT video,playback_video,snapshot FROM module_versions WHERE module_id=? AND version=?", (m["id"], m["published_version"])).fetchone()
        if saved:
            return saved["video"], saved["playback_video"], json.loads(saved["snapshot"]).get("transcript", [])
    return m["video"], m["playback_video"], package(c, m)["transcript"]


@app.get("/api/modules/{mid}/draft")
def get_module_draft(mid: str, user=Depends(creator_read)):
    with connection() as c:
        owned_module(c, mid, user)
        return {"draft": generated_draft(c, mid)}


@app.delete("/api/modules/{mid}/draft", status_code=204)
def dismiss_module_draft(mid: str, user=Depends(creator)):
    with connection() as c:
        owned_module(c, mid, user)
        c.execute("DELETE FROM generated_drafts WHERE module_id=?", (mid,))


@app.post("/api/modules/{mid}/draft/apply")
async def apply_module_draft(mid: str, request: Request, user=Depends(creator)):
    data = await body_json(request)
    sections = data.get("sections", ["transcript", "lessons", "questions"])
    if not isinstance(sections, list) or any(section not in ("transcript", "lessons", "questions", "details") for section in sections):
        fail(400, "Choose valid draft sections to apply.")
    replace = bool(data.get("replace", False))
    applied, skipped = [], []
    with connection() as c:
        m = owned_module(c, mid, user)
        draft = generated_draft(c, mid)
        if not draft:
            fail(404, "No generated draft is available for this module.")
        now = int(time.time())
        if "details" in sections:
            if draft["title"] or draft["description"]:
                new_title = draft["title"] or m["title"] if replace or not m["title"].strip() else m["title"]
                new_description = draft["description"] or m["description"] if replace or not m["description"].strip() else m["description"]
                if new_title != m["title"] or new_description != m["description"]:
                    c.execute("UPDATE modules SET title=?,description=? WHERE id=?", (new_title, new_description, mid))
                    applied.append("details")
                else:
                    skipped.append("details")
        if "transcript" in sections and draft["transcript"]:
            existing = c.execute("SELECT COUNT(*) FROM transcript_segments WHERE module_id=?", (mid,)).fetchone()[0]
            if existing and not replace:
                skipped.append("transcript")
            else:
                if replace:
                    c.execute("DELETE FROM transcript_segments WHERE module_id=?", (mid,))
                    c.execute('UPDATE questions SET explanation_segments=NULL WHERE module_id=?', (mid,))
                for i, item in enumerate(draft["transcript"]):
                    start, end = finite_number(item.get("start")), finite_number(item.get("end"))
                    text = item.get("text")
                    if start is None or end is None or start < 0 or end <= start or (m["duration"] and end > m["duration"]) or not isinstance(text, str) or not text.strip():
                        fail(409, "The generated transcript does not fit the current video. Upload the matching video and retry draft generation.")
                    c.execute(
                        "INSERT INTO transcript_segments(id,module_id,ord,start,end,text,origin,edited) VALUES(?,?,?,?,?,?,'generated',0)",
                        (uuid.uuid4().hex, mid, i, start, end, text.strip()),
                    )
                applied.append("transcript")
        if "lessons" in sections and draft["lessons"]:
            existing = c.execute("SELECT COUNT(*) FROM lessons WHERE module_id=?", (mid,)).fetchone()[0]
            if existing and not replace:
                skipped.append("lessons")
            else:
                previous_end = -1
                for item in draft["lessons"]:
                    if (
                        item["start"] < previous_end
                        or item["start"] < 0
                        or item["end"] <= item["start"]
                        or (m["duration"] and item["end"] > m["duration"])
                    ):
                        fail(409, "The generated lessons do not fit the current video. Upload the matching video and retry draft generation.")
                    previous_end = item["end"]
                if replace:
                    c.execute("DELETE FROM lessons WHERE module_id=?", (mid,))
                for i, item in enumerate(draft["lessons"]):
                    c.execute(
                        "INSERT INTO lessons VALUES(?,?,?,?,?,?,?,'generated')",
                        (uuid.uuid4().hex, mid, i, item["title"], item["summary"], item["start"], item["end"]),
                    )
                applied.append("lessons")
        if "questions" in sections and draft["questions"]:
            existing = c.execute("SELECT COUNT(*) FROM questions WHERE module_id=?", (mid,)).fetchone()[0]
            if existing and not replace:
                skipped.append("questions")
            else:
                for item in draft["questions"]:
                    if item["at"] < 0 or (m["duration"] and item["at"] > m["duration"]):
                        fail(409, "The generated questions do not fit the current video. Upload the matching video and retry draft generation.")
                if replace:
                    c.execute("DELETE FROM questions WHERE module_id=?", (mid,))
                for i, item in enumerate(draft["questions"]):
                    c.execute(
                        "INSERT INTO questions(id,module_id,ord,prompt,options,answer,explanation,at,origin) VALUES(?,?,?,?,?,?,?,?,'generated')",
                        (uuid.uuid4().hex, mid, i, item["prompt"], json.dumps(item["options"]), item["answer"], item["explanation"], item["at"]),
                    )
                applied.append("questions")
        c.execute("UPDATE generated_drafts SET state='applied' WHERE module_id=?", (mid,))
        record_event(c, "draft_applied", user["workspace_id"], user["id"], mid, {"sections": applied, "replace": replace})
        result = package(c, module_row(c, mid), True)
    return {"ok": True, "applied": applied, "skipped": skipped, "module": result}


@app.get("/media/{mid}/captions.vtt")
def captions(mid: str, request: Request, user=Depends(require_user)):
    with connection() as c:
        m = module_row(c, mid)
        if not m or not can_view(c, m, user):
            fail(403, "Forbidden")
        _video, _playback, transcript = media_version(c, m, request.query_params.get("version"))
    body = captions_vtt(transcript)
    return Response(body, media_type="text/vtt; charset=utf-8", headers={"Content-Language": "en"})


@app.get("/media/{mid}")
def media(mid: str, request: Request, user=Depends(require_user)):
    with connection() as c:
        m = module_row(c, mid)
        if not m or not can_view(c, m, user):
            fail(403, "Forbidden")
        version = request.query_params.get("version")
        if version is not None:
            if not version.isdigit() or m["status"] != "published":
                fail(404, "Missing media")
            saved = c.execute("SELECT video,playback_video FROM module_versions WHERE module_id=? AND version=?", (mid, int(version))).fetchone()
            video = (saved["playback_video"] or saved["video"]) if saved else ""
        else:
            video = m["playback_video"] or m["video"]
        if not video:
            fail(404, "Missing media")
        target = FILES / Path(video).name
    if not target.is_file():
        fail(404, "Missing media")
    return FileResponse(target, media_type={".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}.get(target.suffix.lower(), "application/octet-stream"))


@app.put("/api/modules/{mid}")
async def update_module(mid: str, request: Request, user=Depends(creator)):
    data = await body_json(request)
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        fail(400, "Add a module title first.")
    with connection() as c:
        m = owned_module(c, mid, user)
        pass_score = data.get("pass_score", m["pass_score"])
        if type(pass_score) is not int or pass_score not in range(0, 101):
            fail(400, "Passing score must be a whole number from 0 to 100.")
        c.execute("UPDATE modules SET title=?,description=?,pass_score=? WHERE id=?", (title.strip(), data.get("description", ""), pass_score, mid))
        record_event(c, "module_updated", user["workspace_id"], user["id"], mid)
        return package(c, module_row(c, mid), True)


@app.put("/api/modules/{mid}/{kind}")
async def update_items(mid: str, kind: str, request: Request, user=Depends(creator)):
    if kind not in ("lessons", "questions", "transcript"):
        fail(404, "Not found")
    data = await body_json(request)
    items = data.get("items")
    if not isinstance(items, list):
        fail(400, "Check the saved details.")
    with connection() as c:
        m = owned_module(c, mid, user)
        table = "transcript_segments" if kind == "transcript" else kind
        ids = []
        previous_end = -1
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                fail(400, "Check the saved details.")
            item_id = item.get("id") or uuid.uuid4().hex
            if not isinstance(item_id, str) or item_id in ids:
                fail(400, "Duplicate or invalid item ID.")
            existing = c.execute(f"SELECT module_id FROM {table} WHERE id=?", (item_id,)).fetchone()
            if existing and existing["module_id"] != mid:
                fail(403, "This item belongs to another module.")
            ids.append(item_id)
            if kind == "transcript":
                start, end = finite_number(item.get("start")), finite_number(item.get("end"))
                text = item.get("text")
                if start is None or end is None or start < 0 or end <= start or (m["duration"] and end > m["duration"]) or not isinstance(text, str) or not text.strip():
                    fail(400, "Transcript segments need text and valid time ranges within the video.")
                origin = item.get("origin", "manual")
                if origin not in ("manual", "generated"):
                    origin = "manual"
                edited = int(bool(item.get("edited", origin == "manual")))
                c.execute("INSERT INTO transcript_segments(id,module_id,ord,start,end,text,origin,edited) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ord=excluded.ord,start=excluded.start,end=excluded.end,text=excluded.text,edited=excluded.edited", (item_id, mid, i, start, end, text.strip(), origin, edited))
            elif kind == "lessons":
                title = item.get("title")
                start, end = finite_number(item.get("start")), finite_number(item.get("end"))
                if not isinstance(title, str) or not title.strip() or start is None or end is None or start < previous_end or start < 0 or end <= start or (m["duration"] and end > m["duration"]):
                    fail(400, "Lessons need a title and valid, non-overlapping time ranges within the video.")
                previous_end = end
                origin = item.get("origin", "manual") if item.get("origin") in ("manual", "generated") else "manual"
                c.execute("INSERT INTO lessons(id,module_id,ord,title,summary,start,end,origin) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ord=excluded.ord,title=excluded.title,summary=excluded.summary,start=excluded.start,end=excluded.end", (item_id, mid, i, title.strip(), item.get("summary", ""), start, end, origin))
            else:
                options = item.get("options")
                at = finite_number(item.get("at"))
                answer = item.get("answer")
                prompt, explanation = item.get("prompt"), item.get("explanation")
                if not isinstance(prompt, str) or not prompt.strip() or not isinstance(explanation, str) or not explanation.strip() or not isinstance(options, list) or len(options) < 2 or any(not isinstance(o, str) or not o.strip() for o in options) or type(answer) is not int or answer not in range(len(options)):
                    fail(400, "Each question needs a prompt, explanation, two non-empty options, one correct answer, and a valid timestamp.")
                if not valid_check_timestamp(c, mid, m, at):
                    fail(400, "Place each knowledge check inside a lesson range or at the end of the video.")
                origin = item.get("origin", "manual") if item.get("origin") in ("manual", "generated") else "manual"
                c.execute("INSERT INTO questions(id,module_id,ord,prompt,options,answer,explanation,at,origin) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ord=excluded.ord,prompt=excluded.prompt,options=excluded.options,answer=excluded.answer,explanation=excluded.explanation,at=excluded.at", (item_id, mid, i, prompt.strip(), json.dumps(options), answer, explanation, at, origin))
                if 'explanation_link' in item:
                    link = item['explanation_link']
                    if link is not None:
                        try:
                            link = explanation_link(c, m, link.get('segment_ids') if isinstance(link, dict) else None, at)
                        except ValueError as exc:
                            fail(400, str(exc))
                    c.execute('UPDATE questions SET explanation_segments=? WHERE id=?',
                              (json.dumps(link['segment_ids']) if link else None, item_id))
        if ids:
            placeholders = ",".join("?" for _ in ids)
            c.execute(f"DELETE FROM {table} WHERE module_id=? AND id NOT IN ({placeholders})", [mid, *ids])
        else:
            c.execute(f"DELETE FROM {table} WHERE module_id=?", (mid,))
        removed = invalidate_explanation_links(c, module_row(c, mid))
        result = package(c, module_row(c, mid), True)
        result['cleared_explanation_links'] = removed
        return result


@app.patch("/api/modules/{mid}/publish")
def publish(mid: str, user=Depends(creator)):
    with connection() as c:
        m = owned_module(c, mid, user)
        lessons = c.execute("SELECT * FROM lessons WHERE module_id=? ORDER BY start", (mid,)).fetchall()
        questions = c.execute("SELECT * FROM questions WHERE module_id=?", (mid,)).fetchall()
        if not m["title"].strip() or not lessons or not questions or not m["video"] or not (FILES / m["video"]).is_file():
            fail(400, "Add a title, playable video, at least one lesson, and at least one valid quiz question before publishing.")
        for i, lesson in enumerate(lessons):
            if lesson["start"] < 0 or lesson["end"] <= lesson["start"] or lesson["end"] > m["duration"] or (i and lesson["start"] < lessons[i - 1]["end"]):
                fail(400, "Lesson times must be valid, stay within the video, and cannot overlap.")
        for q in questions:
            opts = json.loads(q["options"])
            if not q["prompt"].strip() or not q["explanation"].strip() or len(opts) < 2 or q["answer"] not in range(len(opts)) or q["at"] < 0 or q["at"] > m["duration"]:
                fail(400, "Each question needs a prompt, explanation, two non-empty options, one correct answer, and a valid timestamp.")
            if not valid_check_timestamp(c, mid, m, q["at"]):
                fail(400, "Place each knowledge check inside a lesson range or at the end of the video.")
        version = m["published_version"] + 1
        snapshot = package(c, m, True)
        snapshot.update(status="published", version=version)
        now = int(time.time())
        c.execute("INSERT INTO module_versions(module_id,version,snapshot,video,created_at,playback_video,media_asset_id) VALUES(?,?,?,?,?,?,?)", (mid, version, json.dumps(snapshot), m["video"], now, m["playback_video"], m["media_asset_id"]))
        c.execute("UPDATE modules SET status='published',published_at=?,published_version=? WHERE id=?", (now, version, mid))
        record_event(c, "module_published", user["workspace_id"], user["id"], mid, {"version": version})
        return {"ok": True, "version": version}


@app.post("/api/modules/{mid}/reset-progress")
def reset_progress(mid: str, user=Depends(require_csrf)):
    with connection() as c:
        m = module_row(c, mid)
        if not m or user["workspace_role"] != "learner" or not can_view(c, m, user):
            fail(404, "Assigned published module not found.")
        attempt_ids = [row["id"] for row in c.execute(
            "SELECT id FROM attempts WHERE module_id=? AND learner=?", (mid, user["id"])
        )]
        for aid in attempt_ids:
            c.execute("DELETE FROM answers WHERE attempt_id=?", (aid,))
            c.execute("DELETE FROM attempt_progress WHERE attempt_id=?", (aid,))
        c.execute("DELETE FROM attempts WHERE module_id=? AND learner=?", (mid, user["id"]))
    return {"ok": True}


@app.post("/api/attempts")
async def start_attempt(request: Request, user=Depends(require_csrf)):
    data = await body_json(request)
    mid = data.get("module_id")
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        m = module_row(c, mid)
        if not m or user["workspace_role"] != "learner" or not can_view(c, m, user):
            fail(404, "Assigned published module not found.")
        if type(data.get('new_attempt', False)) is not bool:
            fail(400, 'Invalid new attempt flag.')
        attempt = None if data.get('new_attempt') else c.execute("SELECT * FROM attempts WHERE module_id=? AND learner=? AND version=? ORDER BY started DESC, rowid DESC LIMIT 1", (mid, user["id"], m["published_version"])).fetchone()
        if not attempt:
            aid = uuid.uuid4().hex
            c.execute("INSERT INTO attempts(id,module_id,learner,started,version) VALUES(?,?,?,?,?)", (aid, mid, user["id"], int(time.time()), m["published_version"]))
            attempt = c.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
            record_event(c, "attempt_started", user["workspace_id"], user["id"], mid, {"attempt_id": aid, "version": m["published_version"]})
        c.execute("INSERT OR IGNORE INTO attempt_progress(attempt_id) VALUES(?)", (attempt["id"],))
        return attempt_state(c, attempt)


def owned_attempt(c, aid, user):
    attempt = c.execute("SELECT attempts.* FROM attempts JOIN modules ON modules.id=attempts.module_id JOIN assignments ON assignments.module_id=modules.id AND assignments.learner=attempts.learner WHERE attempts.id=? AND attempts.learner=? AND modules.workspace_id=?", (aid, user["id"], user["workspace_id"])).fetchone()
    if not attempt or user["workspace_role"] != "learner":
        fail(404, "Attempt not found.")
    return attempt


def completion(c, attempt, snapshot, score=None):
    progress = c.execute("SELECT completed_lessons FROM attempt_progress WHERE attempt_id=?", (attempt["id"],)).fetchone()
    done = set(json.loads(progress["completed_lessons"])) if progress else set()
    answered = c.execute("SELECT COUNT(DISTINCT question_id) FROM answers WHERE attempt_id=?", (attempt["id"],)).fetchone()[0]
    completed = bool(snapshot["lessons"] and snapshot["questions"] and len(done) >= len(snapshot["lessons"]) and answered >= len(snapshot["questions"]))
    score = int(attempt["score"] or 0) if score is None else int(score)
    module = module_row(c, attempt["module_id"])
    pass_score = int(module["pass_score"] if module else snapshot.get("pass_score", 70))
    return {
        "completed": completed,
        "score": score,
        "pass_score": pass_score,
        "passed": bool(completed and score >= pass_score),
    }


@app.post("/api/attempts/{aid}/progress")
async def save_progress(aid: str, request: Request, user=Depends(require_csrf)):
    data = await body_json(request)
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        attempt = owned_attempt(c, aid, user)
        snapshot = attempt_snapshot(c, attempt)
        previous = c.execute("SELECT position,completed_lessons FROM attempt_progress WHERE attempt_id=?", (aid,)).fetchone()
        done = set(json.loads(previous["completed_lessons"])) if previous else set()
        position = finite_number(data.get("position", previous["position"] if previous else 0))
        if position is None or position < 0 or position > snapshot["duration"]:
            fail(400, "Playback position is outside this module.")
        lesson_id = data.get("lesson_id")
        if lesson_id:
            if not any(x["id"] == lesson_id for x in snapshot["lessons"]):
                fail(400, "Lesson not found in this module version.")
            done.add(lesson_id)
        c.execute("INSERT INTO attempt_progress(attempt_id,position,completed_lessons) VALUES(?,?,?) ON CONFLICT(attempt_id) DO UPDATE SET position=excluded.position,completed_lessons=excluded.completed_lessons", (aid, position, json.dumps(sorted(done))))
        completed = completion(c, attempt, snapshot)
        if completed["completed"]:
            c.execute("UPDATE attempts SET completed=COALESCE(completed,?) WHERE id=?", (int(time.time()), aid))
            if not attempt["completed"]:
                record_event(c, "attempt_completed", user["workspace_id"], user["id"], attempt["module_id"], {"attempt_id": aid, "score": completed["score"], "passed": completed["passed"]})
        return {
            "position": position,
            "completed_lessons": sorted(done),
            "completed": completed["completed"] or bool(attempt["completed"]),
            "score": completed["score"],
            "pass_score": completed["pass_score"],
            "passed": completed["passed"] or bool(attempt["completed"] and completed["score"] >= completed["pass_score"]),
        }


@app.post("/api/attempts/{aid}")
async def answer(aid: str, request: Request, user=Depends(require_csrf)):
    data = await body_json(request)
    with connection() as c:
        c.execute("BEGIN IMMEDIATE")
        attempt = owned_attempt(c, aid, user)
        snapshot = attempt_snapshot(c, attempt)
        question = next((q for q in snapshot["questions"] if q["id"] == data.get("question_id")), None)
        if not question:
            fail(404, "Question not found in this module version.")
        choice = data.get("choice")
        if type(choice) is not int or choice not in range(len(question["options"])):
            fail(400, "Choose one of the available answers.")
        if c.execute("SELECT 1 FROM answers WHERE attempt_id=? AND question_id=?", (aid, question["id"])).fetchone():
            fail(409, "This question has already been answered.")
        correct = choice == question["answer"]
        c.execute("INSERT INTO answers(attempt_id,question_id,choice,correct) VALUES(?,?,?,?)", (aid, question["id"], choice, int(correct)))
        score = round(c.execute("SELECT AVG(correct)*100 FROM answers WHERE attempt_id=?", (aid,)).fetchone()[0] or 0)
        completed = completion(c, attempt, snapshot, score=score)
        c.execute("UPDATE attempts SET score=?,completed=CASE WHEN ? THEN COALESCE(completed,?) ELSE completed END WHERE id=?", (score, completed["completed"], int(time.time()), aid))
        if completed["completed"]:
            if not attempt["completed"]:
                record_event(c, "attempt_completed", user["workspace_id"], user["id"], attempt["module_id"], {"attempt_id": aid, "score": score, "passed": completed["passed"]})
        return {
            "correct": correct,
            "explanation": question["explanation"],
            "score": score,
            "pass_score": completed["pass_score"],
            "passed": completed["passed"] or bool(attempt["completed"] and score >= completed["pass_score"]),
            "completed": completed["completed"] or bool(attempt["completed"]),
        }


@app.get('/api/attempts/{aid}')
def inspect_attempt(aid: str, user=Depends(require_user)):
    with connection() as c:
        attempt = owned_attempt(c, aid, user)
        snapshot = attempt_snapshot(c, attempt)
        for question in snapshot['questions']:
            question.pop('answer', None)
        answers = [dict(row) for row in c.execute(
            'SELECT question_id,choice,correct FROM answers WHERE attempt_id=?', (aid,)).fetchall()]
        return {**attempt_state(c, attempt), 'module': snapshot, 'answers': answers}


@app.post('/api/attempts/{aid}/questions/{qid}/retry')
async def retry_answer(aid: str, qid: str, request: Request, user=Depends(require_csrf)):
    data = await body_json(request)
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        attempt = owned_attempt(c, aid, user)
        snapshot = attempt_snapshot(c, attempt)
        question = next((q for q in snapshot['questions'] if q['id'] == qid), None)
        if not question:
            fail(404, 'Question not found in this module version.')
        choice = data.get('choice')
        if type(choice) is not int or choice not in range(len(question['options'])):
            fail(400, 'Choose one of the available answers.')
        previous = c.execute('SELECT correct FROM answers WHERE attempt_id=? AND question_id=?', (aid, qid)).fetchone()
        if previous is None or previous['correct']:
            fail(409, 'Only an incorrect answer can be retried.')
        correct = choice == question['answer']
        c.execute('UPDATE answers SET choice=?,correct=? WHERE attempt_id=? AND question_id=?', (choice, int(correct), aid, qid))
        score = round(c.execute('SELECT AVG(correct)*100 FROM answers WHERE attempt_id=?', (aid,)).fetchone()[0] or 0)
        result = completion(c, attempt, snapshot, score)
        result['completed'] = result['completed'] or bool(attempt['completed'])
        result['passed'] = bool(result['completed'] and score >= result['pass_score'])
        c.execute('UPDATE attempts SET score=? WHERE id=?', (score, aid))
        record_event(c, 'answer_retried', user['workspace_id'], user['id'], attempt['module_id'],
                     {'attempt_id': aid, 'question_id': qid, 'correct': correct})
        return {**result, 'completed': result['completed'] or bool(attempt['completed']),
                'correct': correct, 'explanation': question['explanation']}


def websocket_origin_ok(socket):
    origin = socket.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == socket.headers.get("host", "")


async def cleanup_user_calls(user):
    """Close calls owned by a user whose last browser connection went away."""
    notifications = []
    with connection() as c:
        rows = c.execute(
            CALL_QUERY + " WHERE (calls.learner=? OR calls.creator=?) AND calls.status IN ('ringing','active')",
            (user["id"], user["id"]),
        ).fetchall()
        for row in rows:
            if row["status"] == "active":
                status, event = "ended", "call.ended"
            elif user["id"] == call_initiator(row):
                status, event = "cancelled", "call.cancelled"
            else:
                status, event = "missed", "call.missed"
            finish_call(c, row, status, user["id"], "Disconnected")
            payload = public_call(c, call_row(c, row["id"]))
            peer = row["creator"] if user["id"] == row["learner"] else row["learner"]
            notifications.append((peer, event, payload))
            record_event(c, "call_disconnected", user["workspace_id"], user["id"], row["module_id"], {"call_id": row["id"], "status": status})
    for peer, event, payload in notifications:
        await hub.send(peer, {"type": event, "call": payload})


@app.websocket("/ws/calls")
async def calls_socket(socket: WebSocket):
    if not websocket_origin_ok(socket):
        await socket.close(code=1008)
        return
    user = user_for_session(socket.cookies.get("trainly"))
    if not user:
        await socket.close(code=1008)
        return
    await socket.accept()
    hub.add(user["id"], socket)
    window_start, messages = time.time(), 0
    try:
        while True:
            raw = await socket.receive_text()
            if user["expires"] < time.time():
                await socket.close(code=1008)
                break
            if len(raw) > 300_000:
                await socket.close(code=1009)
                break
            now = time.time()
            if now - window_start > 10:
                window_start, messages = now, 0
            messages += 1
            if messages > 300:
                await socket.close(code=1008)
                break
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            kind = data.get("type")
            if kind == "ping":
                if not user_for_session(user["token"]):
                    await socket.close(code=1008)
                    break
                await socket.send_json({"type": "pong"})
                continue
            if kind not in ("rtc.offer", "rtc.answer", "rtc.ice"):
                continue
            call_id = data.get("call_id")
            if not isinstance(call_id, str) or not call_id or len(call_id) > 64:
                continue
            with connection() as c:
                row = call_row(c, call_id)
                if not row or row["status"] != "active" or user["id"] not in (row["learner"], row["creator"]):
                    continue
                peer_id = row["creator"] if user["id"] == row["learner"] else row["learner"]
            payload = data.get("payload")
            if not isinstance(payload, (dict, str)):
                continue
            await hub.send(peer_id, {"type": kind, "call_id": call_id, "payload": payload}, exclude=socket)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Call signaling failed for user %s", user["id"])
    finally:
        hub.remove(user["id"], socket)
        if not hub.online(user["id"]):
            await cleanup_user_calls(user)


if __name__ == "__main__":
    from threading import Thread

    import uvicorn
    from worker import main as run_media_worker

    Thread(target=run_media_worker, name="trainly-media-worker", daemon=True).start()
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        app,
        host=os.environ.get("TRAINLY_HOST", "192.168.254.109"),
        port=port,
        ssl_certfile=os.environ.get("TRAINLY_SSL_CERTFILE") or None,
        ssl_keyfile=os.environ.get("TRAINLY_SSL_KEYFILE") or None,
        timeout_graceful_shutdown=2,
    )
