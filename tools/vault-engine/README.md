# vault-engine

Deterministic gateway for an agent notes folder ("vault"): schema validation, optimistic saves by fingerprint, indexes, audit events. Since version 0.2.0 it can also keep one vault identical in several places through one shared git repository.

## Build and test

```bash
go build -o bin/vault-engine ./cmd/vault-engine
go test ./...                              # short rounds
env -u VAULT_ROOT bash test_e2e.sh         # single-folder end-to-end script
bash scripts/sync-harness.sh run           # full two-place proof (about 35-40 minutes; time limit 90 minutes)
bash scripts/build-release.sh              # darwin/amd64, darwin/arm64, linux/amd64 into bin/release/ (git-ignored)
bin/vault-engine version                   # prints "vault-engine dev" for a plain go build
```

`build-release.sh` stamps the version `0.2.0-sync+<short commit>` (override with `VERSION=...`) and writes `bin/release/SHA256SUMS`. It installs nothing; the same version must be installed in every place.

**Always set `VAULT_ROOT` when running the binary by hand.** Without it the engine looks at the current folder (or two levels up) for a `_meta` folder and then falls back to `~/workspace/agentic-vault` or `~/Documents/Obsidian Vault`, if either exists.

## Plain folder (no sync config)

Nothing changes: every command prints and exits as before.

## Shared folder

A folder is shared when `_meta/bin/sync.json` exists. That file is local to the place and is never synced.

```json
{ "place": "mac-1", "remote": "origin", "branch": "main",
  "poll_interval_ms": 3000, "inbox_quiet_ms": 3000,
  "net_timeout_ms": 10000, "lock_timeout_ms": 15000, "max_retries": 5 }
```

Only `place` is required (lower-case letters, digits and `-`, up to 63 characters, starting with a letter or digit); the other values shown are the defaults. A value that is zero, negative or empty is refused. Environment variables:

| Variable | Meaning |
|---|---|
| `VAULT_ROOT` | The vault folder |
| `VAULT_PLACE` | Overrides `place` (for containers: the pod name) |
| `VAULT_ACTOR` | Who is recorded for `ingest` (default `agent`) |
| `VAULT_HUB_PLACE` | Read by the hub's door check; the engine sets it on every git command it runs |

### What a save does

`commit`, `ingest`, `capture` and `publish-knowledge` each run as one locked step: take the folder lock, settle anything an interrupted run left, get the newest version, run the operation, check size and type of what it wrote, record exactly those files as `<actor>@<place>`, send, and if the answer is unclear ask the shared copy. If another place got in first, the step undoes its own save, rebuilds the indexes and tries again (up to `max_retries`, 5 by default). With a sync config, `ingest` only accepts a file that is already inside `_inbox/`.

The last stdout line is always one of:

| Last line | Exit | Meaning |
|---|---|---|
| `SAVED` | 0 | The shared copy has it |
| `REFUSED engine-error` | 1 | The engine did not accept the input (reason on stderr) |
| `REFUSED note-changed` | 3 | The note changed since it was read, or no fingerprint was given |
| `REFUSED no-connection` | 4 | The shared copy cannot be reached |
| `REFUSED too-large` | 5 | A size, count or daily limit was exceeded |
| `REFUSED type-not-allowed` | 6 | File type or path not accepted |
| `REFUSED busy` | 7 | The folder is in use, or the retries were all lost to races |

Other commands in a shared folder: `whoami` prints the place name. `sync-daemon` keeps the place in step (asks every `poll_interval_ms`, fast-forwards under the lock, rebuilds indexes, sends inbox files after a quiet period of `inbox_quiet_ms`, sets hand edits aside in `_quarantine/<place>/`, and moves a file made by hand outside `_inbox/` there after the same quiet period); `sync-daemon --once` does one pass. A stop signal (SIGINT, SIGTERM, SIGHUP) ends `sync-daemon` with exit 0. `run-workflow` and `daemon` are refused (`REFUSED engine-error`, exit 1), because they change notes outside the save step. `route` is a plain lookup and is unchanged.

Local files, never synced: `_meta/guards/folder.guard` (the folder lock), `_meta/guards/sync-daemon.guard` (stops a second `sync-daemon` from starting in the same place), `_meta/guards/save-in-progress.json` (marker), `_quarantine/<place>/` with `REPORT.log`.

### The shared copy ("hub")

```bash
sh hub/create-hub.sh <hub-dir> <engine-binary> [limits.json]
```

creates a bare repository that only moves forward on `refs/heads/main` (`receive.denyNonFastForwards`, `receive.denyDeletes`, `receive.maxInputSize`, `receive.fsckObjects`) with a `pre-receive` hook that runs `vault-engine hub-pre-receive`. The limits live in one file, `<hub>/hooks/vault-limits.json`:

| Limit | Value |
|---|---|
| One upload | 20 MB (20971520 bytes), cut off while uploading with git's own message |
| One file | 1 MB; `.png` / `.jpg` / `.svg` 300 KB |
| File types | `.md` `.json` `.jsonl` `.yaml` `.yml` `.txt` `.csv`, images; `.gitignore`, `.gitkeep`, `.sh` under `_meta/scripts/`, `.raw` under `_meta/ledger/raw/` |
| Never accepted | `.obsidian/` `_tmp/` `_quarantine/` `_meta/bin/` `_meta/locks/` `_meta/guards/` `_meta/logs/` `_meta/indexes/` `graft/` |
| Files per send | 500 |
| Per place per day | 52428800 bytes (50 MB), counted per UTC day in `<hub>/vault-usage/<date>.json` |

Every file in every commit of a send is checked. A refusal reads `vault-hub: REFUSED <too-large|type-not-allowed>: <message>`.

### Known limits

- **Hub-side check is not complete.** Plan 1 turns on `receive.fsckObjects` but does not tell thin-pack base objects from smuggled ones. A place holding a login and a hand-built pack could leave up to 20 MB per send of unchecked, unreachable data on the hub until git cleans it up. A correct fix belongs with the real receive path and is deferred to Plan 2 (hub on the server).
- **The daily allowance counts the full size of every changed file**, not just the new data (the hub measures every new object in a send). The cost of a save therefore grows with file size. The default is 52428800 bytes per place per day; in the scenario tests one place ran out after about 740 saves in one day (`REFUSED too-large`, exit 5).
- **A freshly set-up place has no index file until its first save or update.**
- **After a refused send the daemon backs off.** It skips only the send step for 1, 2, 4 ... up to 100 passes before trying again, and the wait resets after an accepted send. A lost push race does not start the wait. Updating, recovery and handling of stray files continue on every pass.
- **Measured delay between two places:** median about 1.9 s, worst about 2.9 s over 50 runs with a 3000 ms poll (target: worst under 5 s). The full harness run (`scripts/sync-harness.sh run`) takes about 35-40 minutes.

### Rules for agents

`templates/vault-rules/` holds the section for the vault's `AGENTS.md` and the one-line `CLAUDE.md` / `GEMINI.md` that import it. They are installed into a vault by hand (or by the test harness into test vaults).

### Test harness

`bash scripts/sync-harness.sh setup <empty-dir> <engine-binary>` builds `hub.git`, `mac-test` and `srv-test` from a synthetic fixture. It refuses to work inside the real vault.

## Not yet done

The shared copy as a network service with one login per place, migrating the real vault, and tests with real LLM agents are separate plans.
