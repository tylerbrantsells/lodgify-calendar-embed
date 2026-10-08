# A queued Pages deploy holds the group until someone cancels it

**Problem:** The public calendar stayed on the 5 October file until 8 October. Hourly sync commits kept landing. Pages runs showed `cancelled`, and `gh run list --status in_progress` was empty.

**Dead ends:** Renaming `concurrency.group` again. The group was already `pages-deploy`. The holder was not in the recent list: run 37324227672 had been `queued` since 2026-10-05, build green, deploy job with no steps. Run 36764422215 had been `waiting` since 2026-09-30 on an approval nobody could grant. `deploy-rescue` ignores `cancelled`, so it never touched them.

**What worked:** Cancel those two runs. The newest pending run started on its own and deployed. Live `Last-Modified` moved to 2026-10-08 19:19:46 GMT.

**The rule:** If Pages runs are cancelled in a chain, find the run whose status is `queued` or `waiting`. Cancel that run. A `pending` run with zero jobs is the waiter, not the holder.

**Applies when:** the freshness mail fires and the iCal sync workflow is green.
