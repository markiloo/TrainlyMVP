# Trainly autonomous development instructions

Read `design_plan/prd.md`, `design_plan/checklist.md`, and `design_plan/web_stack.md` before making changes.

- Each daily run **targets 5–7 unchecked checklist items**, in dependency order. Prioritize the FastAPI migration requirements before later features. Choose a coherent, testable group; avoid unrelated high-risk migrations.
- Complete as many as can be **fully implemented and verified** within the job limit. Never mark partial work complete. Report the exact number of completed items and blockers; do not invent success if fewer than five are feasible.
- Preserve existing API paths, status codes, response shapes, authorization, CSRF protections, and authenticated media seeking.
- Add appropriate tests and run relevant tests. Only check an item after all its requirements are satisfied and checks pass.
- Never independently select AI providers or transmit private videos/transcripts externally. Defer PRD Section 10 decisions.
- Avoid destructive operations, production deployments, and unreviewed data migrations.
- Do not modify GitHub Actions, secrets, billing settings, or these agent instructions in development runs.
- Never merge pull requests or push to the default branch.
