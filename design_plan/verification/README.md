# Transcription and explanation replay verification

Verified on Windows with Python 3.13.5 and Edge. All application smoke tests
used a separate database and media directory under `.test_tmp_replay_demo`;
the normal application database and uploaded media were not used.

## Automated checks

- Full Python suite: **59 passed**. Covers API permissions, migrations and
  legacy upgrades, transcript-only worker processing, versioned passages and
  captions, concurrent retries, completed-attempt preservation, and reopening.
- Editor JavaScript suite: **8 passed**.
- Player review JavaScript suite: **5 passed**. Covers clip boundaries,
  out-of-range seeking, checkpoint priority, restoring the return position,
  and listener cleanup.
- Extended retry assertions verify creator results reflect corrected scores,
  retain the completion timestamp and attempt count, and require CSRF.
- JavaScript syntax and Git whitespace checks passed.

## Real local transcription

Installed the optional requirements in the repository's Windows/Python 3.13
environment. A disposable, single-speaker English tutorial was synthesized
with Windows speech synthesis and encoded as an MP4 using FFmpeg.

The actual worker completed upload inspection, audio extraction, CPU/INT8
`small.en` transcription, transcript-only draft storage, and explicit draft
application. The transcript correctly included “Before you begin, save your
work” and “Select the File menu and choose Save,” with ordered timestamps.
Cached inference also passed with `HF_HUB_OFFLINE=1` after dependency pinning.
This is a functional smoke test, not an accuracy or throughput benchmark for
customer recordings.

PyAV 19 was incompatible with faster-whisper 1.2.1's decoder call; PyAV 16.1.0
is pinned. The model downloader is also pinned to avoid introducing a second
HTTP client that changes the existing FastAPI test environment.

## Browser checks

- Creator editor: existing links displayed; first/last transcript segment
  selection saved a consecutive source passage; local-processing disclosure
  correctly stated that lessons and questions remain manually authored.
- Learner: wrong answer displayed review/retry/continue controls; review played
  the selected 0:00–0:06 passage and stopped at its end with the retry form.
- Keyboard: Space selected the answer and Enter submitted it. A correct retry
  changed the score from 0% to 100% and removed the question from missed review.
- Continue returned to the original playback point. Starting a new attempt
  reset its answer state without deleting the previous attempt.
- Responsive check at 390 × 844: playback, checkpoint feedback, replay, and
  retry controls were usable; no horizontal overflow was observed.
- No browser console errors were captured.

The responsive check used Edge's viewport emulation, not a physical phone or
Safari. Broader browser/device certification remains part of pilot readiness.

## Screenshots

- [Creator passage selector](creator-link-explanation.png)
- [Desktop corrected-answer feedback](learner-retry-desktop.png)
- [Mobile-width retry form](learner-retry-mobile.png)
