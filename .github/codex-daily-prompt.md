Work on TrainlyMVP against the real PRD checklist, not a generated task list.

Read AGENTS.md, design_plan/prd.md, design_plan/checklist.md and design_plan/web_stack.md. Identify **5 to 7 currently unchecked checklist items** that are highest priority and can reasonably be implemented together, respecting dependencies, especially the initial FastAPI migration.

For each selected item: implement the required behavior, add or update tests, run appropriate validation, and mark [x] ONLY if it is completely implemented and verified. Do not split an incomplete parent into "done". If a task is too large or blocked, move to another safe prerequisite, and clearly record partial work. Aim to FINISH five to seven items, but never falsely declare completion, degrade safety, or skip validation to meet the number. Do not work beyond the job timeout.

The final response must enumerate: selected items; items fully completed; tests run with results; incomplete/blocked items with reasons; changed files; follow-on recommendations. Do not merge, deploy, change workflows/secrets, or use external AI video providers.
