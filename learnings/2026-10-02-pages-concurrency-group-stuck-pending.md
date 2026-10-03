# A stuck Actions concurrency group cancels every later Pages deploy

**Problem:** After 2026-09-30 the public calendar stayed on that day's data. Hourly sync commits kept landing. Every "Deploy calendar to GitHub Pages" run sat `pending` with an empty job list, then showed `cancelled` when the next sync arrived. `gh run list --status in_progress` found nothing holding the lock.

**Dead ends:** Waiting on the pending run does not help. These runs never received a runner, including one that sat for 1h33m. `deploy-rescue.yml` does not rerun them, because the conclusion is `cancelled`, not `failure`. A new `workflow_dispatch` into the same group only replaces the pending run.

**What worked:** Rename the `concurrency.group`. The next dispatch created jobs within seconds and the deploy finished. The live `calendar_data.js` `Last-Modified` moved to that deploy.

**The rule:** If a workflow's runs stay `pending` with zero jobs, and each new run cancels the previous one, treat the concurrency group name as stuck. Rename the group. Do not wait for a runner that is not queued.

**Applies when:** GitHub Actions runs for one workflow never start, while other workflows in the same repo still get runners.
