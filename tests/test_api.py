import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def setup_app(monkeypatch):
    database = Path("storage") / f"test-{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("TRAINLY_DB", str(database.resolve()))
    monkeypatch.setenv("TRAINLY_STORAGE", str(Path("storage").resolve()))
    for name in ("app", "data", "worker", "providers", "migrations"):
        sys.modules.pop(name, None)
    api = importlib.import_module("app")
    with TestClient(api.app) as client:
        yield api, client
    database.unlink(missing_ok=True)


def run_worker(monkeypatch, duration=20):
    """Process one queued job without invoking FFprobe or FFmpeg."""
    worker = importlib.import_module("worker")
    monkeypatch.setattr(
        worker,
        "inspect_video_details",
        lambda path, extension: {
            "duration": duration,
            "container": ["mp4"],
            "video_codec": "h264",
            "audio_codec": "aac",
        },
    )
    monkeypatch.setattr(worker, "prepare_browser_playback", lambda path, extension, details: (path, False))
    return worker.process_one()


def sign_in(client, email, password="trainly"):
    response = client.post("/api/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_learner_can_reset_video_demo_progress(setup_app):
    _, client = setup_app
    learner = sign_in(client, "learner@trainly.local")
    mid = "ltspice-models-demo"
    module = client.get(f"/api/modules/{mid}").json()
    attempt = client.post("/api/attempts", json={"module_id": mid}, headers=learner).json()
    assert client.post(f"/api/attempts/{attempt['id']}/progress", json={"position": 125, "lesson_id": module["lessons"][0]["id"]}, headers=learner).status_code == 200
    assert client.post(f"/api/attempts/{attempt['id']}", json={"question_id": module["questions"][0]["id"], "choice": 0}, headers=learner).status_code == 200
    assert client.post(f"/api/modules/{mid}/reset-progress", headers=learner).status_code == 200
    fresh = client.post("/api/attempts", json={"module_id": mid}, headers=learner).json()
    assert fresh["id"] != attempt["id"]
    assert fresh["position"] == 0
    assert fresh["completed_lessons"] == []
    assert fresh["answered_questions"] == []
    assert client.post(f"/api/attempts/{attempt['id']}/progress", json={"position": 1}, headers=learner).status_code == 404
    creator = sign_in(client, "creator@trainly.local")
    assert client.post(f"/api/modules/{mid}/reset-progress", headers=creator).status_code == 404


def test_new_items_persist_and_foreign_ids_are_rejected(setup_app):
    api, client = setup_app
    headers = sign_in(client, "creator@trainly.local")
    created = client.post("/api/modules", json={"title": "New training"}, headers=headers).json()
    mid = created["id"]
    lesson = {"title": "First lesson", "summary": "Intro", "start": 0, "end": 10}
    response = client.put(f"/api/modules/{mid}/lessons", json={"items": [lesson]}, headers=headers)
    assert response.status_code == 200
    assert len(response.json()["lessons"]) == 1
    assert response.json()["lessons"][0]["id"]

    question = {"prompt": "Ready?", "options": ["Yes", "No"], "answer": 0, "explanation": "Yes", "at": 10}
    response = client.put(f"/api/modules/{mid}/questions", json={"items": [question]}, headers=headers)
    assert response.status_code == 200
    assert len(response.json()["questions"]) == 1

    with api.connection() as c:
        foreign_id = c.execute("SELECT id FROM questions WHERE module_id='workplace-safety' LIMIT 1").fetchone()[0]
    response = client.put(f"/api/modules/{mid}/questions", json={"items": [{**question, "id": foreign_id}]}, headers=headers)
    assert response.status_code == 403
    with api.connection() as c:
        assert c.execute("SELECT prompt FROM questions WHERE id=?", (foreign_id,)).fetchone()[0] != "Ready?"


def test_question_can_be_saved_before_a_lesson_or_video(setup_app):
    _, client = setup_app
    headers = sign_in(client, "creator@trainly.local")
    created = client.post("/api/modules", json={"title": "Question first"}, headers=headers).json()
    assert created["lessons"] == []
    assert client.put(f"/api/modules/{created['id']}/lessons", json={"items": []}, headers=headers).status_code == 200
    question = {"prompt": "What is the first step?", "options": ["Report it", "Ignore it"], "answer": 0, "explanation": "Report it promptly.", "at": 0}
    saved = client.put(f"/api/modules/{created['id']}/questions", json={"items": [question]}, headers=headers)
    assert saved.status_code == 200
    assert client.get(f"/api/modules/{created['id']}").json()["questions"][0]["prompt"] == question["prompt"]


def test_upload_limit_preserves_previous_video_and_removes_partial_file(setup_app, monkeypatch):
    api, client = setup_app
    headers = sign_in(client, "creator@trainly.local")
    mid = client.post("/api/modules", json={"title": "Upload retry"}, headers=headers).json()["id"]
    first = client.post(f"/api/modules/{mid}/upload", files={"file": ("first.mp4", b"good", "video/mp4")}, headers=headers)
    assert first.status_code == 202
    assert first.json()["state"] == "queued"
    assert run_worker(monkeypatch, duration=12) is True
    with api.connection() as c:
        original = c.execute("SELECT video FROM modules WHERE id=?", (mid,)).fetchone()[0]
        assert c.execute("SELECT duration FROM modules WHERE id=?", (mid,)).fetchone()[0] == 12
        job = c.execute("SELECT state,transcript_state FROM processing_jobs WHERE module_id=?", (mid,)).fetchone()
        assert job["state"] == "ready"
        assert job["transcript_state"] == "not_configured"
    before = set(api.FILES.glob(f"{mid}-*.mp4"))
    monkeypatch.setattr(api, "MAX_VIDEO_BYTES", 4)
    assert client.get("/api/config").json()["max_video_bytes"] == 4
    failed = client.post(f"/api/modules/{mid}/upload", files={"file": ("second.mp4", b"too large", "video/mp4")}, headers=headers)
    assert failed.status_code == 413
    with api.connection() as c:
        assert c.execute("SELECT video FROM modules WHERE id=?", (mid,)).fetchone()[0] == original
    assert set(api.FILES.glob(f"{mid}-*.mp4")) == before
    retry = client.post(f"/api/modules/{mid}/upload", files={"file": ("second.mp4", b"okay", "video/mp4")}, headers=headers)
    assert retry.status_code == 202
    run_worker(monkeypatch, duration=8)
    with api.connection() as c:
        assert c.execute("SELECT duration FROM modules WHERE id=?", (mid,)).fetchone()[0] == 8
        assert c.execute("SELECT video FROM modules WHERE id=?", (mid,)).fetchone()[0] != original
    for path in api.FILES.glob(f"{mid}-*"):
        path.unlink()


def test_media_requires_assignment_and_supports_range(setup_app):
    api, client = setup_app
    video_name = f"test-{uuid.uuid4().hex}.mp4"
    with api.connection() as c:
        other_id = c.execute("INSERT INTO users(email,name,password,role) VALUES(?,?,?,?)", ("other@trainly.local", "Other", api.password_hash("trainly"), "learner")).lastrowid
        c.execute("INSERT INTO memberships(workspace_id,user_id,role) VALUES(?,?,?)", ("local", other_id, "learner"))
        c.execute("UPDATE modules SET video=? WHERE id=?", (video_name, "workplace-safety"))
        c.execute("UPDATE module_versions SET video=? WHERE module_id=? AND version=1", (video_name, "workplace-safety"))
    video = api.FILES / video_name
    video.write_bytes(b"0123456789")
    sign_in(client, "other@trainly.local")
    assert client.get("/media/workplace-safety?version=1").status_code == 403
    sign_in(client, "learner@trainly.local")
    response = client.get("/media/workplace-safety?version=1", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    video.unlink(missing_ok=True)


def test_answer_cannot_be_resubmitted_for_a_better_score(setup_app):
    api, client = setup_app
    headers = sign_in(client, "learner@trainly.local")
    attempt = client.post("/api/attempts", json={"module_id": "workplace-safety"}, headers=headers).json()
    question = client.get("/api/modules/workplace-safety").json()["questions"][0]
    url = f"/api/attempts/{attempt['id']}"
    first = client.post(url, json={"question_id": question["id"], "choice": 0}, headers=headers)
    assert first.status_code == 200
    second = client.post(url, json={"question_id": question["id"], "choice": 1}, headers=headers)
    assert second.status_code == 409
    with api.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM answers WHERE attempt_id=? AND question_id=?", (attempt["id"], question["id"])).fetchone()[0] == 1


def test_creator_publish_and_learner_completion(setup_app, monkeypatch):
    api, client = setup_app
    creator_headers = sign_in(client, "creator@trainly.local")
    mid = client.post("/api/modules", json={"title": "Safety review"}, headers=creator_headers).json()["id"]
    uploaded = client.post(
        f"/api/modules/{mid}/upload",
        files={"file": ("training.mp4", b"sample video data", "video/mp4")},
        headers=creator_headers,
    )
    assert uploaded.status_code == 202
    assert run_worker(monkeypatch, duration=20)
    lesson = {"title": "Review", "summary": "Safety basics", "start": 0, "end": 20}
    response = client.put(f"/api/modules/{mid}/lessons", json={"items": [lesson]}, headers=creator_headers)
    assert response.status_code == 200
    question = {"prompt": "Choose yes", "options": ["Yes", "No"], "answer": 0, "explanation": "Yes is correct", "at": 20}
    response = client.put(f"/api/modules/{mid}/questions", json={"items": [question]}, headers=creator_headers)
    assert response.status_code == 200
    assert client.patch(f"/api/modules/{mid}/publish", json={}, headers=creator_headers).json()["version"] == 1
    assert client.post(f"/api/modules/{mid}/assign", json={"email": "learner@trainly.local"}, headers=creator_headers).status_code == 200

    learner_headers = sign_in(client, "learner@trainly.local")
    module = client.get(f"/api/modules/{mid}").json()
    assert "answer" not in module["questions"][0]
    assert module["pass_score"] == 70
    attempt = client.post("/api/attempts", json={"module_id": mid}, headers=learner_headers).json()
    response = client.post(f"/api/attempts/{attempt['id']}", json={"question_id": module["questions"][0]["id"], "choice": 0}, headers=learner_headers)
    assert response.status_code == 200
    assert response.json()["score"] == 100
    response = client.post(f"/api/attempts/{attempt['id']}/progress", json={"position": 20, "lesson_id": module["lessons"][0]["id"]}, headers=learner_headers)
    assert response.json()["completed"] is True
    assert response.json()["passed"] is True

    sign_in(client, "creator@trainly.local")
    results = client.get(f"/api/modules/{mid}/results").json()
    assert results[0]["status"] == "completed"
    assert results[0]["outcome"] == "passed"
    assert results[0]["score"] == 100
    with api.connection() as c:
        video = c.execute("SELECT video FROM modules WHERE id=?", (mid,)).fetchone()[0]
    (api.FILES / video).unlink(missing_ok=True)


def test_invitation_creates_a_learner_and_assigns_the_module(setup_app):
    api, client = setup_app
    headers = sign_in(client, "creator@trainly.local")
    response = client.post("/api/invitations", json={"email": "New.Learner@example.com", "module_id": "workplace-safety"}, headers=headers)
    assert response.status_code == 201
    token = response.json()["token"]
    details = client.post("/api/invitations/inspect", json={"token": token}).json()
    assert details["email"] == "new.learner@example.com"
    assert details["module"] == "Workplace safety essentials"
    accepted = client.post("/api/invitations/accept", json={"token": token, "name": "New Learner", "password": "secure-pass-123"})
    assert accepted.status_code == 200
    assert accepted.json()["user"]["role"] == "learner"
    assert any(m["id"] == "workplace-safety" for m in client.get("/api/modules").json())
    assert client.post("/api/invitations/inspect", json={"token": token}).status_code == 410
    assert client.post("/api/invitations/accept", json={"token": token, "name": "Again", "password": "secure-pass-123"}).status_code == 410
    assert sign_in(client, "new.learner@example.com", "secure-pass-123")


def test_workspace_membership_scopes_module_and_media_access(setup_app):
    api, client = setup_app
    media_name = f"test-{uuid.uuid4().hex}.mp4"
    with api.connection() as c:
        c.execute("INSERT INTO workspaces(id,name) VALUES(?,?)", ("other", "Other team"))
        owner = c.execute("INSERT INTO users(email,name,password,role) VALUES(?,?,?,?)", ("other.creator@example.com", "Other Creator", api.password_hash("secure-pass-123"), "creator")).lastrowid
        c.execute("INSERT INTO memberships(workspace_id,user_id,role) VALUES(?,?,?)", ("other", owner, "creator"))
        c.execute("INSERT INTO modules(id,owner,workspace_id,title,video,duration,status,published_version) VALUES(?,?,?,?,?,?,?,?)", ("other-training", owner, "other", "Private training", media_name, 10, "published", 1))
        c.execute("INSERT INTO module_versions(module_id,version,snapshot,video,created_at) VALUES(?,?,?,?,?)", ("other-training", 1, '{"questions":[],"lessons":[]}', media_name, 1))
        local_learner = c.execute("SELECT id FROM users WHERE email='learner@trainly.local'").fetchone()[0]
        c.execute("INSERT INTO assignments(module_id,learner,assigned_at) VALUES(?,?,?)", ("other-training", local_learner, 1))
    video = api.FILES / media_name
    video.write_bytes(b"private")
    sign_in(client, "learner@trainly.local")
    assert client.get("/api/modules/other-training").status_code == 403
    assert client.get("/media/other-training?version=1").status_code == 403
    assert client.post("/api/attempts", json={"module_id": "other-training"}, headers={"X-CSRF-Token": client.get("/api/me").json()["csrf"]}).status_code == 404
    sign_in(client, "creator@trainly.local")
    assert all(m["id"] != "other-training" for m in client.get("/api/modules").json())
    assert client.get("/api/modules/other-training/results").status_code == 403
    video.unlink(missing_ok=True)


def test_passing_score_is_configurable_and_reported(setup_app):
    api, client = setup_app
    creator = sign_in(client, "creator@trainly.local")
    assert client.put("/api/modules/workplace-safety", json={"title": "Workplace safety essentials", "pass_score": 101}, headers=creator).status_code == 400
    updated = client.put("/api/modules/workplace-safety", json={"title": "Workplace safety essentials", "pass_score": 80}, headers=creator)
    assert updated.status_code == 200
    assert updated.json()["pass_score"] == 80
    preserved = client.put("/api/modules/workplace-safety", json={"title": "Workplace safety essentials"}, headers=creator)
    assert preserved.json()["pass_score"] == 80

    learner = sign_in(client, "learner@trainly.local")
    module = client.get("/api/modules/workplace-safety").json()
    assert module["pass_score"] == 80
    attempt = client.post("/api/attempts", json={"module_id": "workplace-safety"}, headers=learner).json()
    assert attempt["pass_score"] == 80
    wrong_choices = [0, 1, 0]
    for question, choice in zip(module["questions"], wrong_choices):
        response = client.post(f"/api/attempts/{attempt['id']}", json={"question_id": question["id"], "choice": choice}, headers=learner)
        assert response.status_code == 200
    for lesson in module["lessons"]:
        response = client.post(f"/api/attempts/{attempt['id']}/progress", json={"position": lesson["start"], "lesson_id": lesson["id"]}, headers=learner)
        assert response.status_code == 200
    final = response.json()
    assert final["completed"] is True
    assert final["passed"] is False
    assert final["pass_score"] == 80

    sign_in(client, "creator@trainly.local")
    result = client.get("/api/modules/workplace-safety/results").json()[0]
    assert result["status"] == "completed"
    assert result["outcome"] == "not_passed"
    assert result["passed"] is False


def test_generated_draft_apply_keeps_creator_edits_and_captions_work(setup_app, monkeypatch):
    api, client = setup_app
    creator = sign_in(client, "creator@trainly.local")
    mid = client.post("/api/modules", json={"title": "Draft review"}, headers=creator).json()["id"]
    uploaded = client.post(f"/api/modules/{mid}/upload", files={"file": ("draft.mp4", b"video bytes", "video/mp4")}, headers=creator)
    assert uploaded.status_code == 202
    run_worker(monkeypatch, duration=30)
    lesson = {"title": "Creator lesson", "summary": "Written by the creator", "start": 0, "end": 30}
    assert client.put(f"/api/modules/{mid}/lessons", json={"items": [lesson]}, headers=creator).status_code == 200
    question = {"prompt": "Creator question?", "options": ["Yes", "No"], "answer": 0, "explanation": "Yes.", "at": 15}
    assert client.put(f"/api/modules/{mid}/questions", json={"items": [question]}, headers=creator).status_code == 200

    data = sys.modules["data"]
    with api.connection() as c:
        data.save_generated_draft(
            c, mid,
            [{"start": 0, "end": 12, "text": "Generated transcript."}],
            [{"title": "Generated lesson", "summary": "Generated summary", "start": 0, "end": 30}],
            [{"prompt": "Generated question?", "options": ["A", "B"], "answer": 0, "explanation": "Because.", "at": 20}],
            title="Generated title", description="Generated description", provider="Test provider",
        )
        c.commit()
    draft = client.get(f"/api/modules/{mid}/draft").json()["draft"]
    assert draft["lessons"][0]["title"] == "Generated lesson"

    applied = client.post(f"/api/modules/{mid}/draft/apply", json={"sections": ["transcript", "lessons", "questions"]}, headers=creator)
    assert applied.status_code == 200
    result = applied.json()
    assert result["applied"] == ["transcript"]
    assert set(result["skipped"]) == {"lessons", "questions"}
    assert result["module"]["lessons"][0]["title"] == "Creator lesson"
    assert result["module"]["transcript"][0]["text"] == "Generated transcript."
    assert result["module"]["transcript"][0]["origin"] == "generated"

    replaced = client.post(f"/api/modules/{mid}/draft/apply", json={"sections": ["lessons", "questions"], "replace": True}, headers=creator)
    assert replaced.status_code == 200
    assert replaced.json()["applied"] == ["lessons", "questions"]
    assert replaced.json()["module"]["lessons"][0]["title"] == "Generated lesson"
    assert replaced.json()["module"]["lessons"][0]["origin"] == "generated"

    assert client.patch(f"/api/modules/{mid}/publish", json={}, headers=creator).json()["version"] == 1
    assert client.post(f"/api/modules/{mid}/assign", json={"email": "learner@trainly.local"}, headers=creator).status_code == 200
    learner = sign_in(client, "learner@trainly.local")
    captions = client.get(f"/media/{mid}/captions.vtt?version=1")
    assert captions.status_code == 200
    assert captions.headers["content-type"].startswith("text/vtt")
    assert captions.text.startswith("WEBVTT")
    assert "Generated transcript." in captions.text
    assert client.get(f"/media/{mid}/captions.vtt?version=1", headers={"X-CSRF-Token": ""}).status_code == 200  # GET needs no CSRF
    with api.connection() as c:
        video = c.execute("SELECT video FROM modules WHERE id=?", (mid,)).fetchone()[0]
    (api.FILES / video).unlink(missing_ok=True)


def test_worker_runs_ai_pipeline_and_stores_a_reviewable_draft(setup_app, monkeypatch):
    api, client = setup_app
    creator = sign_in(client, "creator@trainly.local")
    mid = client.post("/api/modules", json={"title": "AI pipeline"}, headers=creator).json()["id"]
    assert client.post(f"/api/modules/{mid}/upload", files={"file": ("ai.mp4", b"video bytes", "video/mp4")}, headers=creator).status_code == 202

    data = sys.modules["data"]
    providers = importlib.import_module("providers")
    worker = importlib.import_module("worker")
    audio = api.FILES / "ai-audio.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(providers, "ai_enabled", lambda: True)
    monkeypatch.setattr(providers, "ai_status", lambda: {"ai_provider": "Test provider"})
    monkeypatch.setattr(worker, "extract_audio", lambda path: audio)
    monkeypatch.setattr(providers, "transcribe_audio", lambda path, duration: [{"start": 0, "end": 10, "text": "Hello training."}])
    monkeypatch.setattr(
        providers,
        "generate_draft",
        lambda transcript, duration, current_title="": {
            "title": "Generated training",
            "description": "A generated description.",
            "lessons": [{"title": "Generated lesson", "summary": "Summary", "start": 0, "end": 10}],
            "questions": [{"prompt": "What is this?", "options": ["Training", "Nothing"], "answer": 0, "explanation": "It is training.", "at": 5}],
        },
    )
    assert run_worker(monkeypatch, duration=10)
    with api.connection() as c:
        job = c.execute("SELECT state,stage,transcript_state,draft_state,provider,error FROM processing_jobs WHERE module_id=?", (mid,)).fetchone()
    assert job["state"] == "ready"
    assert job["stage"] == "complete"
    assert job["transcript_state"] == "ready"
    assert job["draft_state"] == "ready"
    assert job["provider"] == "Test provider"
    assert job["error"] is None
    draft = client.get(f"/api/modules/{mid}/draft").json()["draft"]
    assert draft["state"] == "ready"
    assert draft["transcript"][0]["text"] == "Hello training."
    assert draft["questions"][0]["answer"] == 0
    audio.unlink(missing_ok=True)
    with api.connection() as c:
        asset = c.execute("SELECT asset FROM processing_jobs WHERE module_id=?", (mid,)).fetchone()[0]
    (api.FILES / asset).unlink(missing_ok=True)


def test_worker_records_safe_ai_failure_and_can_retry(setup_app, monkeypatch):
    api, client = setup_app
    creator = sign_in(client, "creator@trainly.local")
    mid = client.post("/api/modules", json={"title": "AI retry"}, headers=creator).json()["id"]
    upload = client.post(f"/api/modules/{mid}/upload", files={"file": ("retry.mp4", b"video bytes", "video/mp4")}, headers=creator)
    assert upload.status_code == 202
    data = sys.modules["data"]
    providers = importlib.import_module("providers")
    worker = importlib.import_module("worker")
    audio = api.FILES / "retry-audio.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(providers, "ai_enabled", lambda: True)
    monkeypatch.setattr(providers, "ai_status", lambda: {"ai_provider": "Test provider"})
    monkeypatch.setattr(worker, "extract_audio", lambda path: audio)

    def unreachable(path, duration):
        raise providers.ProviderError("The AI provider could not be reached. Check the connection and retry.")

    monkeypatch.setattr(providers, "transcribe_audio", unreachable)
    assert run_worker(monkeypatch, duration=10)
    with api.connection() as c:
        job = c.execute("SELECT state,transcript_state,draft_state,error FROM processing_jobs WHERE module_id=?", (mid,)).fetchone()
        module = c.execute("SELECT video,duration FROM modules WHERE id=?", (mid,)).fetchone()
    assert job["state"] == "ready"
    assert job["transcript_state"] == "failed"
    assert job["error"].startswith("The AI provider could not be reached")
    assert module["video"] and module["duration"] == 10

    status = client.get(f"/api/modules/{mid}/uploads/{upload.json()['job_id']}")
    assert status.status_code == 200
    assert status.json()["can_retry"] is True
    assert status.json()["error"].startswith("The AI provider")
    assert client.post(f"/api/modules/{mid}/uploads/{upload.json()['job_id']}/retry", headers=creator).status_code == 200

    monkeypatch.setattr(providers, "transcribe_audio", lambda path, duration: [{"start": 0, "end": 8, "text": "Recovered speech."}])
    monkeypatch.setattr(
        providers,
        "generate_draft",
        lambda transcript, duration, current_title="": {
            "title": "Recovered",
            "description": "Recovered draft.",
            "lessons": [{"title": "Recovered lesson", "summary": "Summary", "start": 0, "end": 8}],
            "questions": [{"prompt": "Recovered?", "options": ["Yes", "No"], "answer": 0, "explanation": "Yes.", "at": 4}],
        },
    )
    assert run_worker(monkeypatch, duration=10)
    with api.connection() as c:
        job = c.execute("SELECT state,transcript_state,draft_state,error FROM processing_jobs WHERE module_id=?", (mid,)).fetchone()
    assert job["state"] == "ready"
    assert job["transcript_state"] == "ready"
    assert job["draft_state"] == "ready"
    assert job["error"] is None
    assert client.get(f"/api/modules/{mid}/draft").json()["draft"]["title"] == "Recovered"
    audio.unlink(missing_ok=True)
    with api.connection() as c:
        asset = c.execute("SELECT asset FROM processing_jobs WHERE module_id=?", (mid,)).fetchone()[0]
    (api.FILES / asset).unlink(missing_ok=True)


def test_delete_module_removes_media_and_generated_draft(setup_app, monkeypatch):
    api, client = setup_app
    creator = sign_in(client, "creator@trainly.local")
    mid = client.post("/api/modules", json={"title": "Delete me"}, headers=creator).json()["id"]
    upload = client.post(f"/api/modules/{mid}/upload", files={"file": ("delete.mp4", b"video bytes", "video/mp4")}, headers=creator).json()
    run_worker(monkeypatch, duration=5)
    with api.connection() as c:
        asset = c.execute("SELECT asset FROM processing_jobs WHERE id=?", (upload["job_id"],)).fetchone()[0]
        data = sys.modules["data"]
        data.save_generated_draft(c, mid, [{"start": 0, "end": 5, "text": "Delete draft."}], [], [])
        c.commit()
    media = api.FILES / asset
    assert media.is_file()
    assert client.delete(f"/api/modules/{mid}", headers=creator).status_code == 204
    assert not media.exists()
    assert client.get(f"/api/modules/{mid}").status_code == 404
    with api.connection() as c:
        assert c.execute("SELECT 1 FROM generated_drafts WHERE module_id=?", (mid,)).fetchone() is None
