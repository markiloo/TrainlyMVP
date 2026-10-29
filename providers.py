"""Replaceable speech-to-text and draft-generation provider adapters.

The adapters use the OpenAI-compatible HTTP shape so a deployment can point
``TRAINLY_AI_BASE_URL`` at a hosted or self-hosted provider. Provider choice and
credentials stay outside product logic. When no provider is configured the
upload pipeline still completes: media is processed and the creator writes
lessons and questions manually.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx


class ProviderNotConfigured(ValueError):
    """Raised when automatic processing was requested but no provider is set."""


class ProviderError(ValueError):
    """A safe, creator-facing provider failure."""


def _base_url() -> str:
    return os.environ.get("TRAINLY_AI_BASE_URL", "").strip().rstrip("/")


def _api_key() -> str:
    return os.environ.get("TRAINLY_AI_API_KEY", "").strip()


def _timeout() -> float:
    try:
        return max(10.0, float(os.environ.get("TRAINLY_AI_TIMEOUT_SECONDS", "600")))
    except ValueError:
        return 600.0


def ai_status() -> dict[str, Any]:
    base = _base_url()
    return {
        "ai_enabled": bool(base),
        "ai_provider": "OpenAI-compatible" if base else None,
        "transcription_model": os.environ.get("TRAINLY_TRANSCRIBE_MODEL", "whisper-1"),
        "draft_model": os.environ.get("TRAINLY_DRAFT_MODEL", "gpt-4o-mini"),
    }


def ai_enabled() -> bool:
    return bool(_base_url())


def _headers() -> dict[str, str]:
    key = _api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _request_error(response: httpx.Response) -> ProviderError:
    detail = ""
    try:
        payload = response.json()
        detail = payload.get("error", {}).get("message", "") if isinstance(payload, dict) else ""
    except ValueError:
        detail = ""
    if not isinstance(detail, str) or not detail:
        detail = f"The AI provider returned HTTP {response.status_code}."
    # Keep provider text short and free of request content.
    return ProviderError(f"AI provider request failed: {detail[:240]}")


def transcribe_audio(path: Path, duration: float) -> list[dict[str, Any]]:
    """Return validated, ordered timestamped segments for an audio file."""
    base = _base_url()
    if not base:
        raise ProviderNotConfigured("Automatic transcription is not configured.")
    path = Path(path)
    if not path.is_file():
        raise ProviderError("The extracted audio file is missing. Retry processing.")
    data = {
        "model": os.environ.get("TRAINLY_TRANSCRIBE_MODEL", "whisper-1"),
        "response_format": "verbose_json",
    }
    try:
        with path.open("rb") as stream:
            response = httpx.post(
                f"{base}/audio/transcriptions",
                headers=_headers(),
                data=data,
                files={"file": (path.name, stream, "audio/wav")},
                timeout=_timeout(),
            )
    except httpx.HTTPError as exc:
        raise ProviderError("The AI provider could not be reached. Check the connection and retry.") from exc
    if response.status_code >= 400:
        raise _request_error(response)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("The AI provider returned an unreadable transcription.") from exc
    return validate_transcript(payload, duration)


def validate_transcript(payload: Any, duration: float) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ProviderError("The AI provider returned an unreadable transcription.")
    raw_segments = payload.get("segments")
    segments: list[dict[str, Any]] = []
    if isinstance(raw_segments, list):
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            try:
                start = float(item.get("start"))
                end = float(item.get("end"))
            except (TypeError, ValueError):
                continue
            if not isinstance(text, str) or not text.strip() or end <= start:
                continue
            segments.append(
                {
                    "start": max(0.0, round(start, 2)),
                    "end": min(float(duration), round(end, 2)),
                    "text": re.sub(r"\s+", " ", text).strip(),
                }
            )
    if not segments:
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            segments.append(
                {"start": 0.0, "end": max(0.1, float(duration)), "text": re.sub(r"\s+", " ", text).strip()}
            )
    segments = [item for item in segments if item["end"] > item["start"] and item["text"]]
    if not segments:
        raise ProviderError("No speech was detected. Add transcript segments manually and retry.")
    segments.sort(key=lambda item: (item["start"], item["end"]))
    # Keep one segment per non-empty, non-overlapping span.
    cleaned: list[dict[str, Any]] = []
    previous_end = 0.0
    for item in segments:
        start = max(item["start"], previous_end)
        end = min(item["end"], float(duration))
        if end - start < 0.05:
            continue
        cleaned.append({"start": round(start, 2), "end": round(end, 2), "text": item["text"]})
        previous_end = end
    if not cleaned:
        raise ProviderError("No usable speech segments were returned. Review the transcript manually.")
    return cleaned


DRAFT_SCHEMA = """Return only a JSON object with this shape:
{
  "title": "short module title",
  "description": "one or two sentence summary",
  "lessons": [
    {"title": "lesson title", "summary": "one sentence", "start": 0, "end": 30}
  ],
  "questions": [
    {"prompt": "question text", "options": ["a", "b", "c"], "answer": 1, "explanation": "why", "at": 25}
  ]
}
Use 2 to 10 lessons with ordered, non-overlapping ranges inside the video, and
3 to 10 questions. Questions must be answerable from the transcript and must
not invent facts. Place each question after the moment that teaches its answer.
The answer is the zero-based index of the correct option."""


def generate_draft(
    transcript: list[dict[str, Any]],
    duration: float,
    current_title: str = "",
    current_description: str = "",
) -> dict[str, Any]:
    """Generate and validate a draft from reviewed/generated transcript segments."""
    base = _base_url()
    if not base:
        raise ProviderNotConfigured("Automatic draft generation is not configured.")
    lines = "\n".join(
        f"[{float(item['start']):.1f}-{float(item['end']):.1f}] {item['text']}" for item in transcript
    )
    prompt = (
        "Create a training module draft from the transcript below. "
        "Keep titles and questions plain and grounded only in the transcript.\n\n"
        f"Video duration: {float(duration):.1f} seconds.\n"
        f"Current title: {current_title or '(none)'}\n"
        f"Current description: {current_description or '(none)'}\n\n"
        f"Transcript:\n{lines}\n\n{DRAFT_SCHEMA}"
    )
    payload = {
        "model": os.environ.get("TRAINLY_DRAFT_MODEL", "gpt-4o-mini"),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You write concise workplace training drafts as strict JSON."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers={"Content-Type": "application/json", **_headers()},
            json=payload,
            timeout=_timeout(),
        )
    except httpx.HTTPError as exc:
        raise ProviderError("The AI provider could not be reached. Check the connection and retry.") from exc
    if response.status_code == 400 and "response_format" in response.text:
        # Some compatible providers do not support JSON mode; retry without it.
        payload.pop("response_format", None)
        try:
            response = httpx.post(
                f"{base}/chat/completions",
                headers={"Content-Type": "application/json", **_headers()},
                json=payload,
                timeout=_timeout(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError("The AI provider could not be reached. Check the connection and retry.") from exc
    if response.status_code >= 400:
        raise _request_error(response)
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProviderError("The AI provider returned an unreadable draft.") from exc
    if not isinstance(content, str):
        raise ProviderError("The AI provider returned an unreadable draft.")
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise ProviderError("The AI provider returned an invalid draft.") from exc
    return validate_draft(data, duration)


def validate_draft(payload: Any, duration: float) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProviderError("The generated draft was not a JSON object.")
    title = payload.get("title")
    description = payload.get("description")
    title = title.strip()[:120] if isinstance(title, str) else ""
    description = description.strip()[:500] if isinstance(description, str) else ""
    lessons = payload.get("lessons")
    questions = payload.get("questions")
    if not isinstance(lessons, list) or not 2 <= len(lessons) <= 10:
        raise ProviderError("The generated draft did not include 2 to 10 lessons.")
    if not isinstance(questions, list) or not 3 <= len(questions) <= 10:
        raise ProviderError("The generated draft did not include 3 to 10 questions.")
    clean_lessons: list[dict[str, Any]] = []
    previous_end = -1.0
    for item in lessons:
        if not isinstance(item, dict):
            raise ProviderError("A generated lesson was not valid.")
        text = item.get("title")
        summary = item.get("summary")
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            raise ProviderError("A generated lesson had an invalid time range.")
        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(summary, str)
            or not summary.strip()
            or start < 0
            or end <= start
            or end > float(duration) + 1
            or start < previous_end
        ):
            raise ProviderError("A generated lesson had invalid text or an invalid time range.")
        clean_lessons.append(
            {
                "title": text.strip()[:120],
                "summary": summary.strip()[:300],
                "start": round(start, 2),
                "end": round(end, 2),
            }
        )
        previous_end = end
    clean_questions: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()
    for item in questions:
        if not isinstance(item, dict):
            raise ProviderError("A generated question was not valid.")
        prompt = item.get("prompt")
        explanation = item.get("explanation")
        options = item.get("options")
        answer = item.get("answer")
        try:
            at = float(item.get("at"))
        except (TypeError, ValueError):
            raise ProviderError("A generated question had an invalid timestamp.")
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or prompt.strip().lower() in seen_prompts
            or not isinstance(explanation, str)
            or not explanation.strip()
            or not isinstance(options, list)
            or not 2 <= len(options) <= 5
            or any(not isinstance(option, str) or not option.strip() for option in options)
            or type(answer) is not int
            or answer not in range(len(options))
            or at < 0
            or at > float(duration) + 1
        ):
            raise ProviderError("A generated question had invalid text, options, answer, or timestamp.")
        seen_prompts.add(prompt.strip().lower())
        clean_questions.append(
            {
                "prompt": prompt.strip()[:500],
                "options": [option.strip()[:200] for option in options],
                "answer": answer,
                "explanation": explanation.strip()[:500],
                "at": round(min(at, float(duration)), 2),
            }
        )
    clean_questions.sort(key=lambda item: (item["at"], item["prompt"]))
    return {
        "title": title,
        "description": description,
        "lessons": clean_lessons,
        "questions": clean_questions,
    }
