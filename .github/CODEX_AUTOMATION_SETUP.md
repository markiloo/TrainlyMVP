# TrainlyMVP scheduled Codex Cloud setup (ChatGPT account)

This repository is prepared for a **Codex Cloud task signed into the owner's ChatGPT account**, not an OpenAI API-key GitHub Actions workflow. There are no automated GitHub Actions jobs in this PR, and no schedule has been activated by these repository files.

## Configure in Codex / ChatGPT Work
1. Open Codex via your ChatGPT account and connect the GitHub repository `markiloo/TrainlyMVP`; set up a cloud environment.
2. Where a recurring cloud automation is offered for your account and environment, schedule **daily 00:00 Asia/Manila**. Codex and ChatGPT Scheduled Tasks are distinct capabilities. If no supported Codex Cloud scheduler is available, use eligible scheduled ChatGPT Work with access to the GitHub repository and appropriate approval settings.
3. Paste the task instructions from `.github/codex-daily-prompt.md`. Ensure the task reads `AGENTS.md` and the existing `design_plan/prd.md`, `design_plan/checklist.md`, and `design_plan/web_stack.md`.
4. Require draft pull requests, no automatic merging or deployment, and human review before merging.
5. Verify the first scheduled run's GitHub access, test logs, checklist changes, and actual consumption under **Settings > Usage**.

## Goal and practical limits
Each run **targets 5–7 fully completed checklist items**, with tests. It may legitimately finish fewer if tasks are too broad, blocked or usage is insufficient. Never check off incomplete tasks.

Subscription Codex and Work share your account's usage allowance; usage can be constrained by five-hour and weekly limits. A new five-hour window starts when eligible activity begins after the previous window ends, not necessarily at midnight. The subscription allowance is not a deterministic token allocation and cannot be hard-split by this repo. Do **not** provide an API key, buy credits, or enable separate API billing as part of this configuration.

Scheduling and cloud execution are account- and product-feature-dependent. **This PR alone does not schedule or start any development.**
