"""Trainly's HTTP API and browser entry point."""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from data import (
    COOKIE_SECURE, FILES, ROOT, attempt_snapshot, attempt_state, db,
    finite_number, inspect_video, module_row, package, password_hash,
    password_matches, published_package,
)

app = FastAPI(title="Trainly", docs_url=None, redoc_url=None)
MAX_VIDEO_BYTES = 1024 * 1024 * 1024


@app.middleware("http")
async def response_headers(request: Request, call_next):
    response = await call_next(request)
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


def current_user(request: Request):
    token = request.cookies.get("trainly")
    if not token:
        return None
    with connection() as c:
        row = c.execute(
            "SELECT users.*, sessions.token, sessions.csrf, sessions.expires "
            "FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=?",
            (token,),
        ).fetchone()
        return dict(row) if row and row["expires"] >= int(time.time()) else None


def require_user(user=Depends(current_user)):
    if not user:
        fail(401, "Sign in to continue.")
    return user


def require_csrf(request: Request, user=Depends(require_user)):
    if request.headers.get("X-CSRF-Token") != user["csrf"]:
        fail(403, "Session expired. Refresh and try again.")
    return user


def creator(user=Depends(require_csrf)):
    if user["role"] != "creator":
        fail(403, "Creator access is required.")
    return user


def owned_module(c, mid, user):
    m = module_row(c, mid)
    if not m:
        fail(404, "Module not found.")
    if user["role"] != "creator" or m["owner"] != user["id"]:
        fail(403, "Creator access is required.")
    return m


def can_view(c, m, user):
    if user and user["role"] == "creator" and m["owner"] == user["id"]:
        return True
    return bool(
        user and user["role"] == "learner" and m["status"] == "published"
        and c.execute("SELECT 1 FROM assignments WHERE module_id=? AND learner=?", (m["id"], user["id"])).fetchone()
    )


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def index():
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/app.css")
def css():
    return FileResponse(ROOT / "static" / "app.css", media_type="text/css")


@app.get("/app.js")
def javascript():
    return FileResponse(ROOT / "static" / "app.js", media_type="text/javascript")


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"user": {k: user[k] for k in ("id", "name", "email", "role")}, "csrf": user["csrf"]} if user else {"user": None}


@app.post("/api/login")
async def login(request: Request):
    data = await body_json(request)
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        fail(400, "Enter your login details.")
    with connection() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
        if not row or not password_matches(password, row["password"]):
            fail(401, "Email or password is incorrect.")
        if not row["password"].startswith("pbkdf2_sha256$"):
            c.execute("UPDATE users SET password=? WHERE id=?", (password_hash(password), row["id"]))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
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


@app.get("/api/learners")
def learners(user=Depends(require_user)):
    if user["role"] != "creator":
        fail(403, "Creator access is required.")
    with connection() as c:
        return [dict(r) for r in c.execute("SELECT id,name,email FROM users WHERE role='learner' ORDER BY name")]


@app.get("/api/modules")
def modules(user=Depends(require_user)):
    with connection() as c:
        if user["role"] == "learner":
            rows = c.execute('SELECT modules.* FROM modules JOIN assignments ON assignments.module_id=modules.id WHERE modules.status="published" AND assignments.learner=? ORDER BY modules.published_at DESC', (user["id"],)).fetchall()
        else:
            rows = c.execute('SELECT * FROM modules WHERE status="published" OR owner=? ORDER BY published_at DESC', (user["id"],)).fetchall()
        result = []
        for m in rows:
            owned = user["role"] == "creator" and m["owner"] == user["id"]
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
        c.execute("INSERT INTO modules(id,owner,title,description) VALUES(?,?,?,?)", (mid, user["id"], title.strip(), data.get("description", "")))
        c.execute("INSERT INTO lessons VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, mid, 0, "Introduction", "Add a short overview for learners.", 0, 0))
        return package(c, module_row(c, mid), True)


@app.get("/api/modules/{mid}")
def get_module(mid: str, user=Depends(require_user)):
    with connection() as c:
        m = module_row(c, mid)
        if not m:
            fail(404, "Module not found.")
        if not can_view(c, m, user):
            fail(403, "You do not have access to this module.")
        return package(c, m, True) if m["owner"] == user["id"] and user["role"] == "creator" else published_package(c, m)


@app.get("/api/modules/{mid}/results")
def results(mid: str, user=Depends(require_user)):
    with connection() as c:
        owned_module(c, mid, user)
        rows = c.execute('''SELECT users.name,users.email,
            (SELECT score FROM attempts x WHERE x.module_id=assignments.module_id AND x.learner=assignments.learner ORDER BY started DESC LIMIT 1) AS score,
            (SELECT started FROM attempts x WHERE x.module_id=assignments.module_id AND x.learner=assignments.learner ORDER BY started DESC LIMIT 1) AS started,
            (SELECT completed FROM attempts x WHERE x.module_id=assignments.module_id AND x.learner=assignments.learner ORDER BY started DESC LIMIT 1) AS completed_at,
            (SELECT COUNT(*) FROM attempts x WHERE x.module_id=assignments.module_id AND x.learner=assignments.learner) AS attempt_count
            FROM assignments JOIN users ON users.id=assignments.learner WHERE assignments.module_id=? ORDER BY users.name''', (mid,)).fetchall()
        return [dict(name=r["name"], email=r["email"], completed=bool(r["completed_at"]), status="completed" if r["completed_at"] else "in_progress" if r["started"] else "not_started", score=r["score"], started=r["started"], completed_at=r["completed_at"], attempt_count=r["attempt_count"]) for r in rows]


@app.post("/api/modules/{mid}/assign")
async def assign(mid: str, request: Request, user=Depends(creator)):
    data = await body_json(request)
    email = data.get("email", "")
    with connection() as c:
        m = owned_module(c, mid, user)
        if m["status"] != "published":
            fail(400, "Publish this module before assigning learners.")
        learner = c.execute("SELECT id FROM users WHERE email=? AND role='learner'", (email.lower() if isinstance(email, str) else "",)).fetchone()
        if not learner:
            fail(404, "No learner account found for that email.")
        c.execute("INSERT OR IGNORE INTO assignments(module_id,learner,assigned_at) VALUES(?,?,?)", (mid, learner["id"], int(time.time())))
    return {"ok": True}


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
    asset = f"{mid}-{uuid.uuid4().hex[:8]}{ext}"
    target = FILES / asset
    size = 0
    try:
        with target.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    fail(413, "This video is larger than the 1 GB limit.")
                stream.write(chunk)
        try:
            duration = inspect_video(target, ext)
        except ValueError as exc:
            fail(400, str(exc))
        with connection() as c:
            owned_module(c, mid, user)
            c.execute("UPDATE modules SET video=?,duration=? WHERE id=?", (asset, duration, mid))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return {"ok": True, "filename": filename, "duration": duration, "message": f"Video saved and checked ({duration // 60} min). Add the lesson and quiz content below; automatic transcription will be available after an AI provider is configured."}


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
            saved = c.execute("SELECT video FROM module_versions WHERE module_id=? AND version=?", (mid, int(version))).fetchone()
            video = saved["video"] if saved else ""
        else:
            video = m["video"]
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
        owned_module(c, mid, user)
        c.execute("UPDATE modules SET title=?,description=? WHERE id=?", (title.strip(), data.get("description", ""), mid))
        return package(c, module_row(c, mid), True)


@app.put("/api/modules/{mid}/{kind}")
async def update_items(mid: str, kind: str, request: Request, user=Depends(creator)):
    if kind not in ("lessons", "questions"):
        fail(404, "Not found")
    data = await body_json(request)
    items = data.get("items")
    if not isinstance(items, list):
        fail(400, "Check the saved details.")
    with connection() as c:
        m = owned_module(c, mid, user)
        ids = []
        previous_end = -1
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                fail(400, "Check the saved details.")
            item_id = item.get("id") or uuid.uuid4().hex
            if not isinstance(item_id, str) or item_id in ids:
                fail(400, "Duplicate or invalid item ID.")
            existing = c.execute(f"SELECT module_id FROM {kind} WHERE id=?", (item_id,)).fetchone()
            if existing and existing["module_id"] != mid:
                fail(403, "This item belongs to another module.")
            ids.append(item_id)
            if kind == "lessons":
                title = item.get("title")
                start, end = finite_number(item.get("start")), finite_number(item.get("end"))
                if not isinstance(title, str) or not title.strip() or start is None or end is None or start < previous_end or start < 0 or end <= start or (m["duration"] and end > m["duration"]):
                    fail(400, "Lessons need a title and valid, non-overlapping time ranges within the video.")
                previous_end = end
                c.execute("INSERT INTO lessons VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ord=excluded.ord,title=excluded.title,summary=excluded.summary,start=excluded.start,end=excluded.end", (item_id, mid, i, title.strip(), item.get("summary", ""), start, end))
            else:
                options = item.get("options")
                at = finite_number(item.get("at"))
                answer = item.get("answer")
                prompt, explanation = item.get("prompt"), item.get("explanation")
                if not isinstance(prompt, str) or not prompt.strip() or not isinstance(explanation, str) or not explanation.strip() or not isinstance(options, list) or len(options) < 2 or any(not isinstance(o, str) or not o.strip() for o in options) or type(answer) is not int or answer not in range(len(options)) or at is None or at < 0 or (m["duration"] and at > m["duration"]):
                    fail(400, "Each question needs a prompt, explanation, two non-empty options, one correct answer, and a valid timestamp.")
                c.execute("INSERT INTO questions VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ord=excluded.ord,prompt=excluded.prompt,options=excluded.options,answer=excluded.answer,explanation=excluded.explanation,at=excluded.at", (item_id, mid, i, prompt.strip(), json.dumps(options), answer, explanation, at))
        if ids:
            placeholders = ",".join("?" for _ in ids)
            c.execute(f"DELETE FROM {kind} WHERE module_id=? AND id NOT IN ({placeholders})", [mid, *ids])
        else:
            c.execute(f"DELETE FROM {kind} WHERE module_id=?", (mid,))
        return package(c, module_row(c, mid), True)


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
        version = m["published_version"] + 1
        snapshot = package(c, m, True)
        snapshot.update(status="published", version=version)
        now = int(time.time())
        c.execute("INSERT INTO module_versions(module_id,version,snapshot,video,created_at) VALUES(?,?,?,?,?)", (mid, version, json.dumps(snapshot), m["video"], now))
        c.execute("UPDATE modules SET status='published',published_at=?,published_version=? WHERE id=?", (now, version, mid))
        return {"ok": True, "version": version}


@app.post("/api/attempts")
async def start_attempt(request: Request, user=Depends(require_csrf)):
    data = await body_json(request)
    mid = data.get("module_id")
    with connection() as c:
        m = module_row(c, mid)
        if not m or user["role"] != "learner" or not can_view(c, m, user):
            fail(404, "Assigned published module not found.")
        attempt = c.execute("SELECT * FROM attempts WHERE module_id=? AND learner=? AND version=? AND completed IS NULL ORDER BY started DESC LIMIT 1", (mid, user["id"], m["published_version"])).fetchone()
        if not attempt:
            aid = uuid.uuid4().hex
            c.execute("INSERT INTO attempts(id,module_id,learner,started,version) VALUES(?,?,?,?,?)", (aid, mid, user["id"], int(time.time()), m["published_version"]))
            attempt = c.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
        c.execute("INSERT OR IGNORE INTO attempt_progress(attempt_id) VALUES(?)", (attempt["id"],))
        return attempt_state(c, attempt)


def owned_attempt(c, aid, user):
    attempt = c.execute("SELECT * FROM attempts WHERE id=? AND learner=?", (aid, user["id"])).fetchone()
    if not attempt or user["role"] != "learner":
        fail(404, "Attempt not found.")
    return attempt


def completion(c, attempt, snapshot):
    progress = c.execute("SELECT completed_lessons FROM attempt_progress WHERE attempt_id=?", (attempt["id"],)).fetchone()
    done = set(json.loads(progress["completed_lessons"])) if progress else set()
    answered = c.execute("SELECT COUNT(DISTINCT question_id) FROM answers WHERE attempt_id=?", (attempt["id"],)).fetchone()[0]
    return bool(snapshot["lessons"] and snapshot["questions"] and len(done) >= len(snapshot["lessons"]) and answered >= len(snapshot["questions"]))


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
        if completed:
            c.execute("UPDATE attempts SET completed=COALESCE(completed,?) WHERE id=?", (int(time.time()), aid))
        return {"position": position, "completed_lessons": sorted(done), "completed": completed or bool(attempt["completed"])}


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
        completed = completion(c, attempt, snapshot)
        c.execute("UPDATE attempts SET score=?,completed=CASE WHEN ? THEN COALESCE(completed,?) ELSE completed END WHERE id=?", (score, completed, int(time.time()), aid))
        return {"correct": correct, "explanation": question["explanation"], "score": score, "completed": completed or bool(attempt["completed"])}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)
