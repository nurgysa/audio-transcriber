# Google Drive Backup + Sync — Design Spec

## Context

User wants the app's transcripts and tasks to:
1. Survive OS reinstall / new laptop (true backup)
2. Eventually be available on a second device (sync)

Mental model: «как WhatsApp» — but as discussed in design conversation, WhatsApp's
real-time multi-device sync uses WhatsApp's own infrastructure, not Google Drive.
The Drive integration in WhatsApp is **one-way backup-only**.

Therefore this spec is split: backup is mandatory and ships first; sync is a
later phase that builds on the same Drive integration.

## Phasing

| Phase | Goal | Independently shippable? |
|---|---|---|
| **7.0** GDrive auth + Settings UI | OAuth login button, token cache, status badge | Yes — user can log in / out, no backup yet |
| **7.1** Manual backup | "Сделать backup сейчас" — upload history/ + config (text only) | Yes — user has working backup |
| **7.2** Manual restore | "Восстановить из Drive" — pick snapshot, download | Yes — survives OS reinstall |
| **7.3** Auto-schedule | Daily/weekly checkbox in Settings | Yes — ships hands-off backup |
| ~~**7.4** Audio opt-in~~ | ~~Checkbox «Бэкапить аудио файлы»~~ | **Out of scope per user decision (2026-04-30) — text-only backup.** Can be revisited later if needed. |
| **7.5** *(future)* Eventual two-way sync | Pull-merge-push on `tasks.json` between devices | Yes — adds collaboration |

**After 7.0-7.3: WhatsApp-equivalent backup (text-only).** Phase 7.5 adds
collaboration, deferred until 7.0-7.3 is stable in real use.

**Scope decision 2026-04-30**: User chose text-only backup — `*.wav`/`*.mp3`
files are excluded from `history.zip`. Backup payload becomes ≤1 MB per
snapshot (typical 30 meetings); 15 GB free Drive tier holds ~15 000
snapshots — effectively unlimited for personal use. Audio backup is
deferred indefinitely.

## Architecture

### New package: `gdrive/`

```
gdrive/
├── __init__.py
├── auth.py          # OAuth login + token persistence + refresh
├── client.py        # thin Drive API v3 wrapper (upload/list/download/delete)
├── backup.py        # orchestrator: filesystem → Drive snapshot
├── restore.py       # orchestrator: Drive snapshot → filesystem
├── scheduler.py     # daily/weekly tick (Phase 7.3)
└── sync.py          # eventual-sync merge protocol (Phase 7.5, stub for now)
```

### New UI

- `ui/dialogs/settings.py` — gains a "Google Drive" section: status badge, "Войти" / "Выйти" button, frequency dropdown (7.3), "Бэкапить аудио" checkbox (7.4).
- `ui/dialogs/restore.py` — **new** dialog (Phase 7.2): list of snapshots in Drive with timestamps + sizes; user picks one and clicks Восстановить.

### Auth (Phase 7.0)

**Library**: `google-auth-oauthlib` + `google-api-python-client` (official Google packages).

**Scope**: `https://www.googleapis.com/auth/drive.file` — **non-sensitive**, no
Google verification needed. App sees only files it created (privacy + speed win).

**Flow** (Desktop OAuth — RFC 8252 loopback):
1. User clicks "Войти через Google" in Settings.
2. App starts a local HTTP server on `localhost:<random-port>`.
3. Opens default browser to Google consent screen with `redirect_uri=http://localhost:<port>`.
4. User logs in + consents (one-time).
5. Browser redirects to localhost; app catches the auth code, exchanges for tokens.
6. Tokens cached in `~/.audio-transcriber/gdrive-token.json` (NOT in `config.json`,
   keeps API keys away from sync surface).
7. Refresh token is long-lived (180 days for verified apps, 7 days while in
   "Testing" mode in GCP — that's a known constraint while we're unverified).

**Public client_id** ships in `gdrive/auth.py` as a constant. Anyone with the binary
uses the same OAuth project; that's expected for desktop apps. (See Discord's,
Notion's, similar tools.)

### Backup payload structure (Phase 7.1)

Drive folder created on first backup: `audio-transcriber-backup/`.

Inside it, each backup is a **timestamped subfolder**:

```
audio-transcriber-backup/
├── 2026-04-30T12-30-00/
│   ├── manifest.json           ← summary + checksums
│   ├── config.json             ← user settings (API keys REDACTED)
│   └── history.zip             ← history/ folder zipped, EXCLUDING *.wav/*.mp3
├── 2026-04-29T22-00-00/
│   └── ...
```

`manifest.json` schema:
```json
{
  "version": 1,
  "created_at": "2026-04-30T12:30:00",
  "app_version": "phase-6.5",
  "host": "DESKTOP-7VTOJR2",
  "files": {
    "config.json":  {"size": 1234, "sha256": "..."},
    "history.zip":  {"size": 567890, "sha256": "..."}
  },
  "transcripts_count": 42,
  "audio_included": false
}
```

**Why timestamped folders** vs overwriting one file:
- User can restore from N days ago if recent backup is corrupted
- Easy to inspect what changed between snapshots
- Trivial deletion of old snapshots in cleanup

**Retention policy** (Phase 7.3+): keep last 7 daily + last 4 weekly + last 12 monthly. Total ~23 snapshots. Older ones auto-deleted on next successful backup.

**API key redaction in `config.json`**:
- `openrouter_api_key`, `linear_api_key`, `glide_api_key`, `assemblyai_api_key`
- `google_oauth_token` (defensive — even though it's in separate file)
- These keys are replaced with `"<REDACTED>"` in the uploaded copy.
- Restore prompts user to re-enter keys.

### Restore (Phase 7.2)

UI: list dialog showing all snapshots with `created_at`, `transcripts_count`, sizes.

User picks one → app:
1. Downloads `manifest.json` and verifies it parses
2. Confirms with user: «Это перезапишет ваши текущие history/ и config (без API ключей). Продолжить?»
3. Downloads `history.zip` (and `audio.zip` if present and user opts in)
4. Extracts to `history/` (clobbering existing — backup of pre-restore state to `history.bak.<ts>/`)
5. Merges `config.json` with current (preserves user's freshly-entered API keys, overrides everything else)
6. Verifies SHA256 against manifest
7. Status: «✓ Восстановлено N записей из {timestamp}»

### Auto-schedule (Phase 7.3)

In `__init__` of main App, schedule a Tk `after(N_ms, self._gdrive_tick)` loop.

Tick (every 60 sec) checks:
- Last backup timestamp from `config.json["gdrive_last_backup"]`
- User-selected frequency: `daily` / `weekly` / `off`
- If overdue + Drive enabled + token valid → spawn worker thread that runs `backup.py`
- Worker uses existing `_active_clients` pattern for cancel-on-close

**Why Tk after vs OS scheduler (Task Scheduler / cron):**
- App-level scheduler ties backup to "user is using the app" — backup happens during real use, not at midnight when laptop's asleep
- Simpler: no admin perms, no separate config to break
- Trade-off: missed backups on days the app isn't opened. Acceptable for personal-tool.

### Audio opt-in (Phase 7.4)

Checkbox: «Бэкапить исходные аудио файлы (\*.wav, \*.mp3)».

Off by default. When toggled on:
- Show informational dialog: «Аудио файлы крупные. Один час записи ≈ 50-100 MB. Free Google Drive — 15 GB. Ваш текущий объём аудио: X.XX GB. Продолжить?»
- Save to `config["gdrive_backup_audio"] = true`
- Next backup tick zips audio + uploads as `audio.zip`

### Eventual two-way sync (Phase 7.5 — future)

Idea (not in scope for this spec, sketch only):
- A single canonical `tasks.json` file on Drive (`audio-transcriber-backup/_sync/tasks.json`).
- Each device, on save: GET file with `If-Match: <last-known-etag>`. If 412 → fetch, merge, retry. If 200 → write succeeded.
- Merge protocol: per-task LWW by `edited_at` timestamp; per-task local_id stable across devices.
- Conflicts: same-task edited within ms → user gets a UI prompt to pick.

Not implemented now. Spec'd here so we don't paint ourselves into corners
during 7.0-7.4.

## Configuration additions (`config.json`)

```json
{
  "gdrive_enabled": false,
  "gdrive_account_email": "user@gmail.com",        // displayed in Settings
  "gdrive_last_backup": "2026-04-30T12:30:00",     // ISO timestamp
  "gdrive_backup_frequency": "daily",              // off / daily / weekly
  "gdrive_backup_audio": false,                    // 7.4 opt-in
  "gdrive_root_folder_id": "1abc...XYZ"            // cached after first backup
}
```

OAuth tokens live OUTSIDE config.json:
- `~/.audio-transcriber/gdrive-token.json` — refresh + access tokens
- This file is NOT backed up to Drive (it's the auth FOR Drive — chicken/egg)

## Testing

Per existing project patterns (mock clients, no real network in CI):

| Test file | Coverage |
|---|---|
| `tests/test_gdrive_auth.py` | Token persistence, refresh logic, expired-token handling |
| `tests/test_gdrive_backup.py` | Manifest building, zip creation, redaction, upload-orchestrator |
| `tests/test_gdrive_restore.py` | Manifest parsing, SHA256 verification, merge-config-with-keys |
| `tests/test_gdrive_scheduler.py` | Frequency math (is overdue?), tick gating |

Manual smoke:
- Auth: real Google account login, token persisted across restart
- Backup: empty history → backup → verify on Drive UI
- Restore: delete history locally, restore from snapshot, verify content
- Auto: set frequency=daily, advance system clock, see auto-tick fire
- Audio opt-in: toggle on, verify size warning, see audio.zip on Drive

## Dependencies

Add to `requirements.txt`:
```
google-auth==2.43.0
google-auth-oauthlib==1.3.0
google-api-python-client==2.197.0
```

Total ~5 MB additional install. Pure Python, no native deps.

## Open questions

- **Encryption at rest**: WhatsApp added end-to-end encrypted backup in 2021.
  Should we encrypt zips before upload? Adds password management UX (one extra
  password the user must remember; if lost, backup is unrecoverable). **Recommendation
  for now: rely on Google's at-rest encryption** (TLS in transit + Drive's server-side
  AES-256 — same as WhatsApp's pre-2021 default). Revisit if a real privacy threat appears.
- **Multi-account**: user might want backup to a different Gmail than the one
  they signed in to. Out of scope; one Google account per app install.
- **Quota exhaustion handling**: if Drive returns 403 quota_exceeded, what's the UX?
  Recommendation: show a notification, pause auto-backup, suggest deleting old
  snapshots or upgrading Google One. Not blocking 7.0-7.1 but plan for 7.3.

## Implementation order recap

1. **7.0** — auth flow, Settings UI section, token cache. ~250 LOC + ~100 tests.
2. **7.1** — manual backup button, manifest, zip + upload. ~300 LOC + ~150 tests.
3. **7.2** — restore dialog, manifest parsing, download + extract. ~300 LOC + ~150 tests.
4. **7.3** — scheduler tick + frequency dropdown. ~120 LOC + ~80 tests.
5. **7.4** — audio opt-in checkbox + size warning. ~80 LOC + ~30 tests.
6. **7.5** — *(future)* eventual sync. Out of scope here.

Each phase ends with a manual smoke + tag (`phase-7.X`). Tests run on every commit.
