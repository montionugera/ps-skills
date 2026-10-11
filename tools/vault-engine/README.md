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

**Keep the `env -u VAULT_ROOT` prefix on `test_e2e.sh`.** The script uses an already-exported `VAULT_ROOT` as its work folder and ends with `rm -rf "$VAULT_ROOT"`, so running it while `VAULT_ROOT` points at a real notes folder deletes that folder. With the prefix it works in a fresh temporary folder of its own.

`build-release.sh` stamps the version `0.2.0-sync+<short commit>`, with `.dirty` added when the engine folder holds uncommitted or untracked files (an explicit `VERSION=...` is used as given). It checks that every binary carries that version and then writes `bin/release/SHA256SUMS`. Everything is built and checked in a staging folder first, so a build that fails leaves the earlier set as it was. Moving the new set into place is not one atomic step: if it is interrupted, `SHA256SUMS` is missing, and a missing `SHA256SUMS` means the set is not complete and must be built again. It installs nothing; the same version must be installed in every place.

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
| `VAULT_HUB_PLACE` | Read by the hub's door check; the engine sets it on every git command it runs. The hub takes this name as sent and does not check who the sender is (see Known limits) |

### What a save does

`commit`, `ingest`, `capture` and `publish-knowledge` each run as one locked step: take the folder lock, settle anything an interrupted run left, get the newest version, run the operation, check size and type of what it wrote, record exactly those files as `<actor>@<place>`, send, and if the answer is unclear ask the shared copy. If another place got in first, the step undoes its own save, rebuilds the indexes and tries again (up to `max_retries`, 5 by default). With a sync config, `ingest` only accepts a file that is already inside `_inbox/`.

The last stdout line is always one of:

| Last line | Exit | Meaning |
|---|---|---|
| `SAVED` | 0 | The shared copy has it |
| `REFUSED engine-error` | 1 | The engine did not accept the input, or the engine or the shared copy hit a fault of its own, such as hub settings it cannot read (reason on stderr) |
| `REFUSED note-changed` | 3 | The note changed since it was read, or no fingerprint was given |
| `REFUSED no-connection` | 4 | The shared copy cannot be reached |
| `REFUSED too-large` | 5 | A size, count or daily limit was exceeded |
| `REFUSED type-not-allowed` | 6 | File type or path not accepted |
| `REFUSED busy` | 7 | The folder is in use, or the retries were all lost to races |

Other commands in a shared folder: `whoami` prints the place name. `sync-daemon` keeps the place in step (asks every `poll_interval_ms`, fast-forwards under the lock, rebuilds indexes, sends inbox files after a quiet period of `inbox_quiet_ms`, sets hand edits aside in `_quarantine/<place>/`, and moves a file made by hand outside `_inbox/` there after the same quiet period); `sync-daemon --once` does one pass. A stop signal (SIGINT, SIGTERM, SIGHUP) ends `sync-daemon` with exit 0. The stop does not wait for a time limit: a git command that is running is killed, and a wait for the folder lock ends at once. `run-workflow` and `daemon` are refused (`REFUSED engine-error`, exit 1), because they change notes outside the save step. `route` is a plain lookup and is unchanged.

Local files, never synced: `_meta/guards/folder.guard` (the folder lock), `_meta/guards/sync-daemon.guard` (stops a second `sync-daemon` from starting in the same place), `_meta/guards/save-in-progress.json` (marker; it also records that an undo of that save was started), `_quarantine/<place>/` with `REPORT.log`.

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

Every file in every commit of a send is checked. A refusal reads `vault-hub: REFUSED <too-large|type-not-allowed|engine-error>: <message>`. `too-large` and `type-not-allowed` mean the send broke a rule in the table above. `engine-error` means the hub itself could not read or compute something (its settings file, git's own input, a git command inside the hook (including the check that a send only moves forward), the usage file): the send is still refused, and the place answers `REFUSED engine-error` (exit 1), not a size or type refusal.

### Known limits

- **Hub-side check is not complete.** Plan 1 turns on `receive.fsckObjects` but does not tell thin-pack base objects from smuggled ones. Anything that can send to the hub (in this plan: anything that can write to the hub folder; there is no login) could, with a hand-built pack, leave up to 20 MB per send of unchecked, unreachable data on the hub until git cleans it up. A correct fix belongs with the real receive path and is deferred to Plan 2 (hub on the server).
- **The hub trusts the place name as sent.** The door check reads the sender's name from `VAULT_HUB_PLACE` and nothing verifies it: there is no login in this plan. A sender that gives another place's name is counted against that place's daily allowance, and there is no enforced way to cut off one place. One login per place belongs to the plan that puts the hub on a server.
- **The daily allowance charges much more than the new data, and the charge grows with the number of event files. Known gap, owner decision needed.** What the code does (`pkg/vaultsync/hub.go`, the allowance block of `PreReceive`): every send is charged the full, uncompressed size of every object that is new to the hub. That is the whole of every changed file (not only the changed lines), the commit record, and the whole listing of every folder in which anything changed. Every `commit` and every `publish-knowledge` writes one new event file into `_meta/events/<year>/<month>/` (`ingest`, `capture` and inbox sends write none), so each of those two commands is charged that folder's complete listing again, about 66 bytes per event file already there (28 bytes plus the file name; 66 with a 13-character agent id). The cost of a `commit` or `publish-knowledge` therefore grows with the number of those saves all places have made that month, not with the size of the note. Measured in the final review (scratch repository): a 402-byte save was charged 47,109 bytes with 700 event files in the month's folder, 98% of it the one folder listing. Consequences:
  - In the scenario tests one place ran out of the default 52428800 bytes after about 740 saves in one day (`REFUSED too-large`, exit 5).
  - A place can be refused because of event files other places wrote.
  - Near 15,900 event files in one month (1048576 / 66) the folder listing itself passes the 1 MB limit for one record (`max_file_bytes`), and every `commit` and `publish-knowledge` from every place is refused until the month changes (`ingest`, `capture` and inbox sends do not touch that folder and still go through).
  - `_meta/ledger/captures.jsonl` (`pkg/vault/ledger.go`) is one growing, synced file: every `capture` is charged the whole file, and once it passes 1 MB every capture from every place is refused.

  This is a known gap against the design's "50 MB of new data per day". It fails closed and loses nothing, and it is deliberately not changed in this plan. It needs an owner decision before the real notes folder is moved onto sync.
- **Rebuild the indexes when you set up a place.** A freshly set-up place has no index file until its first save or update, and until then `search` answers "No matching records found" with no error, even for notes that are there. After setting up a place run `VAULT_ROOT=<place> vault-engine rebuild-index` once.
- **An inbox file can be sent half-written.** `sync-daemon` sends an inbox file once it has been untouched for `inbox_quiet_ms` (3 s by default). If the writer pauses longer than that in the middle, the half-written file is sent, and the full text written afterwards is treated as a hand edit and lands in `_quarantine/<place>/`. Write the file somewhere else and move it into the inbox in one step (write, then rename) to avoid this.
- **No automatic git clean-up and no git hooks in a place.** Every git command the engine runs in a place turns off git's automatic clean-up (`gc.auto=0`, `maintenance.auto=false`) and hooks (`core.hooksPath=/dev/null`). A place's repository is never packed by itself; clean-up has to be scheduled by a later plan. The hub's own `pre-receive` hook still runs.
- **No alert when an invalid note arrives.** A note that arrives from the shared copy is applied as it is, even if the local engine would consider it invalid; no alert event is written (the design asks for one; not built in this plan).
- **`REFUSED no-connection` can mean "not confirmed yet".** When the answer to a send is unclear and the shared copy does not show the save, the engine keeps the save and its marker and answers `REFUSED no-connection` (exit 4). The save may still have arrived: the next engine command or daemon pass in that place asks the shared copy and either keeps the save or takes it back. Running the same command again is safe; it answers `SAVED` or `REFUSED note-changed` if the first try did arrive.
- **In a shared folder `ingest` refuses a file from outside the inbox** (`REFUSED engine-error`, exit 1). `ingest` deletes its source, and only a file under `_inbox/` is kept in the shared history first. Put the file in the inbox, then ingest it from there. In a plain folder `ingest` works on any path as before.
- **The engine ignores git's repository variables and needs the folder to be its own repository.** In a place, `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` and the like are not passed on to git, and a shared folder that is not the top level of its own git repository is refused (`REFUSED engine-error`).
- **After a refused send the daemon backs off.** It skips only the send step for 1, 2, 4 ... up to 100 passes before trying again, and the wait resets after an accepted send. A lost push race does not start the wait. Updating, recovery and handling of stray files continue on every pass.
- **Measured delay between two places:** median about 1.9 s, worst about 2.9 s over 50 runs with a 3000 ms poll (target: worst under 5 s). The full harness run (`scripts/sync-harness.sh run`) takes about 35-40 minutes.

### Rules for agents

`templates/vault-rules/` holds the section for the vault's `AGENTS.md` and the one-line `CLAUDE.md` / `GEMINI.md` that import it. They are installed into a vault by hand (or by the test harness into test vaults).

### Test harness

`bash scripts/sync-harness.sh setup <empty-dir> <engine-binary>` builds `hub.git`, `mac-test` and `srv-test` from a synthetic fixture. It refuses to work inside the real vault.

## Not yet done

The shared copy as a network service with one login per place, migrating the real vault, and tests with real LLM agents are separate plans.
