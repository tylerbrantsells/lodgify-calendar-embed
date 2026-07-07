# Adding a New Property

No code changes are needed — properties are pure config.

## Assisted path (recommended)

Paste the property **name** and its **Lodgify iCal export URL** into a Claude Code session in this repo and ask it to add the property. It follows `.claude/skills/add-property/SKILL.md`:
merge into local `.env`, push the updated GitHub secret, trigger the sync, and verify the property appears on the published calendar.

## Manual path

1. Get the property's iCal export URL from Lodgify.
2. Update the **local `.env`** first — it is the source of truth (GitHub secrets can't be read back). Add the entry to `ICS_URLS_JSON`, e.g.:
   ```json
   {"111 Eagles": "https://...", "42 New Place": "https://new-ical-url"}
   ```
3. Push the same JSON to GitHub: repo **Settings → Secrets and variables → Actions → `ICS_URLS_JSON`**, or:
   ```sh
   gh secret set ICS_URLS_JSON < <(grep '^ICS_URLS_JSON=' .env | cut -d= -f2-)
   ```
4. Optional ordering: add the name to `PROPERTY_ORDER_JSON` (JSON list, display order). If omitted, properties sort by leading street number.
5. Trigger a sync (or wait for the hourly one):
   ```sh
   gh workflow run "Lodgify iCal Sync"
   ```
   The Pages deploy chains automatically; the property appears a couple of minutes later.

## Verify

After the sync commit lands, confirm the new name shows up:

```sh
git pull && python3 -c "import json; print([p['name'] for p in json.load(open('calendar_data.json'))['properties']])"
```

## If `.env` and the GitHub secret drift

Re-paste the full URL set into `.env`, then re-run step 3 to overwrite the secret.
