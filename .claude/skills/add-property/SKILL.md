---
name: add-property
description: Onboard a new rental property to the DSP cleaner calendar. Use when the user wants to add a property, gives a new Lodgify iCal URL, or asks to update ICS_URLS_JSON.
---

# Add a property

Input needed from the user: property **name** and **Lodgify iCal export URL** (and optionally where it should sort).

GitHub secrets cannot be read back — the local `.env` in the repo root is the source of truth for `ICS_URLS_JSON`. Always merge there first, then push to GitHub.

## Steps

1. Read `ICS_URLS_JSON` from `.env` (single line, JSON dict of `{name: url}`).
2. Add the new entry; write the updated line back to `.env` (keep it one line).
3. Push the secret:
   ```sh
   gh secret set ICS_URLS_JSON --body '<merged-json>'
   ```
4. If the user wants a specific position: update `PROPERTY_ORDER_JSON` in `.env` the same way and `gh secret set PROPERTY_ORDER_JSON --body '<json-list>'`. Otherwise skip — properties auto-sort by leading street number.
5. Trigger the sync and watch it:
   ```sh
   gh workflow run "Lodgify iCal Sync"
   ```
   The Pages deploy chains off it automatically.
6. Verify: after the sync's "Hourly calendar sync" commit, `git pull --rebase` and confirm the new property name is in `calendar_data.json` (`properties[].name`). Report the live calendar will show it within a couple of minutes.

## Gotchas

- Always `git pull --rebase` before any push — the hourly sync bot commits to main constantly.
- If `.env` and the GitHub secret have drifted, ask the user to paste the full URL set and overwrite both.
- Removing a property is the same flow: delete the entry and push the secret.
