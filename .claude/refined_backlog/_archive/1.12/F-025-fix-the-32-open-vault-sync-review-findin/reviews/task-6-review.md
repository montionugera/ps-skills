# Task 6 review (wording: A2, A3, A11, A23, README sentences for A1 and A8)

Range 1231549..e3b6908. Method: read the review package once, then one focused
look per new sentence at the code it describes. No tests run, nothing changed.
Paths below are under tools/vault-engine/.

### Spec Compliance
- ✅ Spec compliant. Every listed file has its hunk and each hunk is the text the brief gives, word for word.
  - A2: pkg/vaultsync/repo.go:38-40 (note on Repo) and :61-62 (note on stop).
  - A3: pkg/vaultsync/syncer.go:54-58.
  - A23: pkg/vaultsync/lock_test.go:78-81.
  - A11: templates/vault-rules/AGENTS.section.md:50-53 reads "Your input is probably fine."; pkg/vaultsync/harness_test.go:47 quotes the new sentence.
  - A1 sentence: README.md:61 ("within a couple of seconds"; "ends at once" is gone).
  - A8 sentence: README.md:82 (tree or blob, `type-not-allowed`, exit 6).
- Acceptance 4 checked line by line: repo.go +5, syncer.go +5, lock_test.go -1/+4, every one a `//` line. No executable line changed. harness_test.go changes one string literal only.
- Scope: six files, all under tools/vault-engine/. Two new commits, each names its items (A2 A3 A23; A11 A1 A8). No amend visible.
- ⚠️ Cannot verify from diff: the report's test output (red then green for the rules-file test, verify-6.sh exit 0). Not re-run, per the method.

### Claims checked against the code
1. Repo "not safe for use from more than one goroutine: lock, gate and stop are plain fields" - TRUE. The fields are written at daemon.go:60, :69, :73, :74 and syncer.go:141, :143 and read in repo.go run() (:153, :158, :167) with no mutex or atomic. The only goroutine the package starts (repo.go:178) touches cmd.Wait only.
2. stop "is set and read on the one goroutine that uses the Repo" - TRUE in production. main.go:455 calls d.Run on the main goroutine; passes run there (daemon.go:57). The cancel arrives through the context, which is safe to cancel from elsewhere; the field itself is not touched by another goroutine.
3. errorOutcome "a failed fetch is ErrNoConnection and also carries its cause" - TRUE: repo.go:233 wraps both with two %w. "The first match wins" - TRUE (a Go switch). See Minor 1 for the one loose phrase.
4. A23 comment - TRUE and it now says less than the old one, correctly. lock.go:58-60 closes the file in the ctx.Done branch; the test only proves the lock can be taken again after the holder lets go. A leaked descriptor that never held the flock would indeed not show.
5. README A1 sentence - does not promise an outcome line, so the named risk does not apply. Checked: a stop that lands before r.Head() (syncer.go:344-346) gives errorOutcome(err), which is engine-error because ErrStopped has no case; the break at syncer.go:350-351 leads to "REFUSED no-connection" (:379). The README says neither. In the daemon both are swallowed anyway (daemon.go:184-186 returns quietly, Run returns nil, exit 0), and one-shot commands never set stop.
6. README A8 sentence - TRUE for a hub that already has a main line (hub.go:119-120, tests at hub_test.go:476 and :498). See Minor 3 for the empty hub.

### Strengths
- The text follows the brief exactly; no drive-by edits, no reflowed neighbours.
- The A23 comment removes a claim the test never proved and names where the close really is.
- The stop note points back to the Repo note instead of repeating it.

### Issues
#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. pkg/vaultsync/syncer.go:55-57 - "one error can match more than one of them" is followed by an example whose causes (ErrStopped, ErrTimedOut, *exec.ExitError) are not cases of this switch. Today that fetch error matches one named case (ErrNoConnection) plus default, so order does not yet change any answer. The last sentence (a new case placed above can change an existing answer) is the true and useful part. Fix: say "matches ErrNoConnection today; a case for its cause, such as ErrStopped, placed above would take over". Plan-mandated wording.
2. README.md:61 - "so `sync-daemon` ends within a couple of seconds" reads as a bound the code does not give. What is bounded: a running git is killed and waited for at most 2 s (repo.go:164 WaitDelay), a lock wait ends within 20 ms (lock.go:58-61), later git commands are refused by the gate (daemon.go:60-63), one 500 ms sleep can remain (syncer.go:334). What is not bounded: work that is not git and is already running when the signal lands, such as an index rebuild (vault.go:390 takes no context) or the folder scan; the daemon ends after it. Fix: "normally ends within a couple of seconds". Plan-mandated wording.
3. README.md:82 - the tree-or-blob sentence is unconditional, but the check sits inside `if oldSHA != zeroSHA` (hub.go:109-121). A tree or blob sent to an empty hub skips it and goes to rev-list (hub.go:126), as the plan's own decision 3 says. Fix: add "on a hub that already has a main line", or leave as is and accept the gap. Plan-mandated wording.

### Assessment
**Task quality:** Approved
**Reasoning:** The change is what the brief asked for, comments only in the three Go files, and every new sentence holds against the code in the normal case. The three Minor items are places where the mandated wording is a little wider than the code; none misleads a reader about ordinary behaviour.
