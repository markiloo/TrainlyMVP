# Trainly Codex cloud development setup

## Schedule and behavior
GitHub Actions cron `0 16 * * *` runs at midnight in Asia/Manila (UTC+8) the next day. GitHub scheduled workflows can start late and run only from the default branch.

The agent attempts **5–7 highest-priority unchecked items** from `design_plan/checklist.md` per day, reading `design_plan/prd.md` and `design_plan/web_stack.md`. The priority is the FastAPI migration. It checks off a requirement only when finished and verified, and creates a **draft pull request** for human review, never automatic merges. Complex items may mean fewer than five are completed in a run.

## Usage and billing
The target is 5–7 checklist items, **not** half the tokens in a ChatGPT five-hour usage window. This GitHub Actions solution uses an independently billed OpenAI API key. A four-hour run timeout is an upper-bound on runtime, not a token cap. To bound financial exposure use an API project with appropriate externally enforced spending controls; simple alerting budgets may not guarantee cutoff.

## Activate
This workflow is OFF unless repository Actions variable `CODEX_AUTOMATION_ENABLED` equals `true`. Before enabling:
1. Review and merge the setup pull request.
2. Configure repository Actions secret `OPENAI_API_KEY` with an API key associated with a billing arrangement you approve.
3. Review Actions permissions and allow Actions to create pull requests; grant appropriate workflow token permissions.
4. Set `CODEX_AUTOMATION_ENABLED=true` and manually run the workflow once to validate it.
5. Inspect the draft PR, logs, cost, and tests before trusting the schedule.

To stop new runs, set the variable to `false`; cancel in-progress jobs separately. Do not enter an API key in a commit or chat.

## Guardrails
The agent must not check off incomplete tasks, make irreversible deployments, change workflow/billing/secrets, or merge changes. GitHub Actions will not guarantee a run completes 5–7 items; the checklist remains the source of truth. Review the workflow and model access before enabling paid autonomous code execution.
