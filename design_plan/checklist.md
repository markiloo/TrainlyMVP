# Trainly MVP implementation checklist

Use this checklist to track work against the [product requirements](./prd.md) and [web stack decision](./web_stack.md). Checked items describe behavior present in the local MVP as of 2026-10-19; they do not imply production readiness. Update the boxes as work lands. Requirement IDs refer to Section 4.3 of the PRD.

## 1. Move the existing app to FastAPI first

- [ ] Replace the `BaseHTTPRequestHandler` entry point with a FastAPI app served by Uvicorn.
- [ ] Preserve the current `/api` paths, HTTP methods, status codes, and JSON response shapes used by `static/app.js`.
- [ ] Move sign-in, session lookup, role checks, and CSRF checks into reusable route dependencies. (F1)
- [ ] Move module, assignment, attempt, progress, result, and publish routes without changing their existing behavior. (F1, F7–F10)
- [ ] Use FastAPI upload handling for MP4, MOV, and WebM without buffering a full 1 GB file in memory. (F2)
- [ ] Preserve authorization and byte range seeking on private video responses. (F2, F8)
- [ ] Serve the existing page and static assets through the new app; introduce Jinja2 rendering when page routes need server data.
- [ ] Confirm creator and learner flows against the migrated routes before adding new product features.
- [ ] Move database access into short, explicit units of work, then introduce SQLAlchemy models and Alembic migrations in a separate step.

## 2. Accounts, workspaces, and assignments

- [x] Seed creator and learner demo accounts and support sign-in with hashed passwords. (F1)
- [x] Store server-side sessions in SQLite and use an HTTP-only cookie. (F1)
- [x] Enforce creator and learner roles on existing editing and learning routes. (F1)
- [x] Let a creator assign a published module to an existing learner by email. (F8)
- [ ] Add workspace and membership records, with workspace roles for creators and learners. (F1)
- [ ] Provision or invite users without relying on seeded demo accounts. (F1)
- [ ] Scope module, assignment, attempt, result, and private media queries to the user's workspace. (F1)
- [ ] Define the private-link versus invitation behavior after the assignment decision in PRD Section 10. (F1, F8)
- [ ] Require HTTPS and secure session cookies in deployment; review session expiry and CSRF behavior. (F1)

## 3. Video intake and private playback

- [x] Accept MP4, MOV, and WebM uploads and inspect container, video stream, and duration with FFprobe. (F2)
- [x] Reject uploads over 1 GB or 120 minutes and show validation errors. (F2, F11)
- [x] Store videos outside public static files and serve authenticated byte ranges for seeking. (F2, F8)
- [ ] Make upload size and duration limits deployment configurable. (F2)
- [ ] Show upload progress and distinguish upload, queued, processing, ready, and failed states. (F2, F3)
- [ ] Handle interrupted uploads so users can retry without losing module edits. (F11)
- [ ] Store asset metadata and derived files separately from module content. (F2, F3)
- [ ] Prepare a browser playable video when the source codec needs conversion. (F2, F8)

## 4. Durable processing and AI draft

- [ ] Add a SQLite processing-job table with stage, state, retry count, timestamps, and safe error details. (F3, F11)
- [ ] Run one separate worker that claims jobs, releases stale claims, and records each stage result. (F3)
- [ ] Move media inspection and audio extraction into processing stages outside HTTP requests. (F3)
- [ ] Select transcription and text-generation providers after the video data handling decision in PRD Section 10. (F3)
- [ ] Add replaceable provider adapters with credentials supplied through configuration. (F3)
- [ ] Transcribe speech into timestamped segments; report missing speech or low quality for manual review. (F3, F4)
- [ ] Generate a proposed title, summary, 2–10 ordered lessons, and 3–10 quiz questions from the transcript. (F3, F5, F6)
- [ ] Validate generated time ranges, answer keys, explanations, and source grounding before displaying a draft. (F5, F6)
- [ ] Expose processing stage, failure reason, and a safe retry action without requiring another upload. (F3, F11)
- [ ] Keep creator edits intact when a failed generation stage is retried. (F11)

## 5. Creator review and publishing

- [x] Create and edit module titles and descriptions. (F5)
- [x] Add, remove, reorder, and edit lessons with nonoverlapping ranges inside the video. (F5)
- [x] Add, remove, reorder, and edit questions, answers, explanations, and timestamps. (F6)
- [x] Validate required title, video, lesson, and question data before creator-only publishing. (F7)
- [x] Save an immutable content and video snapshot for each published version. (F7)
- [ ] Store and edit timestamped transcript segments, including their origin and edit state. (F4)
- [ ] Let creators seek the video from a transcript segment or a question timestamp. (F4, F6)
- [ ] Show which lesson and question text came from generation and requires review. (F4–F6)
- [ ] Provide a learner preview before publishing. (F7)
- [x] Keep draft edits separate from the currently published version through republishing. (F7)

## 6. Learner experience, progress, and results

- [x] Show assigned published modules, lesson navigation, video playback, and timed or end-position questions. (F8)
- [x] Save answers, scores, playback position, completed lessons, and resumable attempts against a published version. (F9)
- [x] Require all lessons and questions before marking an attempt complete. (F9)
- [x] Show each assigned learner's latest status, score, dates, and attempt count to the creator. (F10)
- [ ] Block seeking past unanswered required checkpoints until the question is handled. (F8)
- [ ] Support mobile seeking and playback transitions across supported browsers. (F8)
- [ ] Generate captions from the reviewed transcript and provide accessible caption controls. (F4, F8)
- [ ] Make question overlays, feedback, focus movement, and keyboard controls accessible. (F8)
- [ ] Add a per-module passing score, defaulting to 70%, and settle whether passing is required for completion. (F9)
- [ ] Retry or reconcile failed progress saves without losing a learner's place or duplicating answers. (F9, F11)

## 7. Operations, privacy, and pilot readiness

- [ ] Configure SQLite foreign keys, write ahead logging, and a busy timeout for the API and worker.
- [ ] Add reviewed schema migrations for existing data and future workspace, transcript, and job tables.
- [ ] Deploy one writable Uvicorn app instance and one worker behind HTTPS with persistent database and media volumes.
- [ ] Back up and restore both SQLite data and private media as a documented recovery procedure.
- [ ] Define video, transcript, and generated-artifact retention and deletion rules before production use.
- [ ] Tell creators when uploaded content may be sent to configured AI providers.
- [ ] Record request failures and processing timing without logging private video or transcript content.
- [ ] Review the learner flow against WCAG 2.2 AA with keyboard and screen reader checks.
- [ ] Record upload, processing, editing, publishing, and completion events for the PRD success measures.
- [ ] Run a pilot and compare draft success, creator time, publish rate, and learner completion against the targets in PRD Section 8.
