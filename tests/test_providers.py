import sqlite3
import sys

import pytest

import providers
from migrations import migrate


def test_transcript_validation_clips_and_orders_segments():
    segments = providers.validate_transcript(
        {
            "segments": [
                {"start": 8, "end": 12, "text": "  second   part "},
                {"start": 0, "end": 9, "text": "first part"},
                {"start": 20, "end": 30, "text": "past the end"},
                {"start": 3, "end": 3, "text": "empty"},
                {"start": 1, "end": 2, "text": ""},
            ]
        },
        duration=10,
    )
    assert segments[0] == {"start": 0.0, "end": 9.0, "text": "first part"}
    assert segments[1] == {"start": 9.0, "end": 10.0, "text": "second part"}
    assert all(item["end"] <= 10 for item in segments)


def test_transcript_validation_rejects_missing_speech():
    with pytest.raises(providers.ProviderError, match="No speech"):
        providers.validate_transcript({"segments": []}, duration=10)


def test_draft_validation_accepts_valid_json_and_rejects_bad_ranges():
    draft = providers.validate_draft(
        {
            "title": " Safety ",
            "description": " Summary ",
            "lessons": [
                {"title": "One", "summary": "First", "start": 0, "end": 10},
                {"title": "Two", "summary": "Second", "start": 10, "end": 20},
            ],
            "questions": [
                {"prompt": "A?", "options": ["Yes", "No"], "answer": 0, "explanation": "Because.", "at": 5},
                {"prompt": "B?", "options": ["One", "Two", "Three"], "answer": 2, "explanation": "Because.", "at": 15},
                {"prompt": "C?", "options": ["Yes", "No"], "answer": 1, "explanation": "Because.", "at": 20},
            ],
        },
        duration=20,
    )
    assert draft["title"] == "Safety"
    assert [question["prompt"] for question in draft["questions"]] == ["A?", "B?", "C?"]
    with pytest.raises(providers.ProviderError, match="time range"):
        providers.validate_draft(
            {
                "lessons": [
                    {"title": "One", "summary": "First", "start": 0, "end": 30},
                    {"title": "Two", "summary": "Second", "start": 10, "end": 20},
                ],
                "questions": [
                    {"prompt": "A?", "options": ["Yes", "No"], "answer": 0, "explanation": "Because.", "at": 5},
                    {"prompt": "B?", "options": ["Yes", "No"], "answer": 0, "explanation": "Because.", "at": 6},
                    {"prompt": "C?", "options": ["Yes", "No"], "answer": 0, "explanation": "Because.", "at": 7},
                ],
            },
            duration=20,
        )


def test_captions_are_webvtt_and_escape_cue_timing(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("TRAINLY_DB", str(tmp_path / "captions.sqlite3"))
    monkeypatch.setenv("TRAINLY_STORAGE", str(tmp_path / "storage"))
    sys.modules.pop("data", None)
    data = importlib.import_module("data")
    body = data.captions_vtt(
        [
            {"start": 0, "end": 1.5, "text": "Hello --> world"},
            {"start": 1.5, "end": 2, "text": "Line one\nLine two"},
        ]
    )
    assert body.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:01.500" in body
    assert "Hello → world" in body
    assert "-->" not in body.splitlines()[4]


def test_migrations_upgrade_an_old_database():
    c = sqlite3.connect(":memory:")
    c.executescript(
        """
        CREATE TABLE modules(id TEXT PRIMARY KEY, title TEXT, description TEXT, video TEXT, duration INTEGER, status TEXT, published_at INTEGER);
        CREATE TABLE module_versions(module_id TEXT, version INTEGER, snapshot TEXT, video TEXT, created_at INTEGER);
        CREATE TABLE attempts(id TEXT PRIMARY KEY, module_id TEXT, learner INTEGER, started INTEGER, completed INTEGER, score INTEGER);
        CREATE TABLE processing_jobs(id TEXT PRIMARY KEY, module_id TEXT);
        CREATE TABLE lessons(id TEXT PRIMARY KEY, module_id TEXT);
        CREATE TABLE questions(id TEXT PRIMARY KEY, module_id TEXT);
        """
    )
    migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 4
    module_columns = {row[1] for row in c.execute("PRAGMA table_info(modules)")}
    assert {"workspace_id", "published_version", "pass_score", "playback_video"} <= module_columns
    job_columns = {row[1] for row in c.execute("PRAGMA table_info(processing_jobs)")}
    assert {"audio_path", "transcript_state", "draft_state", "provider", "message"} <= job_columns
    assert "origin" in {row[1] for row in c.execute("PRAGMA table_info(lessons)")}
    assert c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='generated_drafts'").fetchone()
    migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 4
