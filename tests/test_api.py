import importlib
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
    sys.modules.pop("app", None)
    sys.modules.pop("data", None)
    api = importlib.import_module("app")
    with TestClient(api.app) as client:
        yield api, client
    database.unlink(missing_ok=True)


def sign_in(client, email, password="trainly"):
    response = client.post("/api/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


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


def test_media_requires_assignment_and_supports_range(setup_app):
    api, client = setup_app
    video_name = f"test-{uuid.uuid4().hex}.mp4"
    with api.connection() as c:
        c.execute("INSERT INTO users(email,name,password,role) VALUES(?,?,?,?)", ("other@trainly.local", "Other", api.password_hash("trainly"), "learner"))
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
    monkeypatch.setattr(api, "inspect_video", lambda path, extension: 20)
    uploaded = client.post(
        f"/api/modules/{mid}/upload",
        files={"file": ("training.mp4", b"sample video data", "video/mp4")},
        headers=creator_headers,
    )
    assert uploaded.status_code == 200
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
    attempt = client.post("/api/attempts", json={"module_id": mid}, headers=learner_headers).json()
    response = client.post(f"/api/attempts/{attempt['id']}", json={"question_id": module["questions"][0]["id"], "choice": 0}, headers=learner_headers)
    assert response.status_code == 200
    response = client.post(f"/api/attempts/{attempt['id']}/progress", json={"position": 20, "lesson_id": module["lessons"][0]["id"]}, headers=learner_headers)
    assert response.json()["completed"] is True

    sign_in(client, "creator@trainly.local")
    results = client.get(f"/api/modules/{mid}/results").json()
    assert results[0]["status"] == "completed"
    assert results[0]["score"] == 100
    with api.connection() as c:
        video = c.execute("SELECT video FROM modules WHERE id=?", (mid,)).fetchone()[0]
    (api.FILES / video).unlink(missing_ok=True)
