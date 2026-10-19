# Trainly autonomous development instructions

Read `design_plan/prd.md`, `design_plan/checklist.md`, and `design_plan/web_stack.md` before making changes.

- Work on only **one small, highest-priority unchecked** item per run, prioritizing the FastAPI migration sequence in the PRD.
- Preserve existing API paths, status codes, response shapes, authorization, CSRF protections, and authenticated media seeking.
- Add focused tests and run existing relevant tests. If checks cannot run, report this; do not claim completion.
- Update a checklist checkbox **only when** its acceptance criteria are fully met and tests pass; otherwise leave it unchecked and document partial progress in the PR body.
- Never independently select third-party AI providers or transmit private videos/transcripts to external providers. Defer unresolved Section 10 decisions.
- Avoid destructive operations, data migrations affecting existing data without review, deployment, or secrets changes.
- Do not change GitHub Actions workflows, permissions, secrets, billing settings, or these agent instructions during development runs.
- Do not merge any pull request or push to the default branch.
