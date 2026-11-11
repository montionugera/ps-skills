## Working in a folder that is shared between several places

Agents in other places change this folder too. Follow these rules.

0. KNOW WHERE YOU ARE: run `_meta/bin/vault-engine whoami`. It prints your
   place name (for example `mac-1`). Use it in file names (rule 6).

1. CHANGE NOTES only with `_meta/bin/vault-engine` (`commit`, `ingest`,
   `capture`, `publish-knowledge`). Never edit an existing note file directly.
   The ONLY place you may create files directly is your own inbox (rule 6).
   Never run git in this folder. Never touch `_meta/` by hand.
   Each of those four commands ends with exactly one last line: `SAVED`, or
   `REFUSED <reason>`. Read that last line; the lines before it explain it.
   `commit` needs the fingerprint (`sha256`) from `vault-engine read-record`.
   `run-workflow` and `daemon` are not available in a shared folder.

2. IF A SAVE ENDS WITH `REFUSED note-changed`: another place changed that note
   after you read it. This is normal. Handle it yourself:
   a. Read the note again with `_meta/bin/vault-engine read-record <id>`.
   b. Look at what changed. The other place may already have done your work,
      or made it wrong or pointless.
   c. If your change is still needed, make it again on the new version and
      save with the new fingerprint. If not, do not save.
   Never ask a person. Never force your old version over the new one.
   If the same note is refused 3 times in a row, stop working on it, write a
   short note about it in your inbox, and continue with other work.

3. IF A SAVE ENDS WITH `REFUSED no-connection`: treat it as not saved. Run the
   same command again up to 3 times, one minute apart; if an earlier try did
   arrive, the engine answers `SAVED` or `REFUSED note-changed` and nothing is
   saved twice. If it still fails, keep your result as a file in your own
   inbox, stop changing shared notes, and say so in your final report. Do not
   work around it.

4. IF A SAVE ENDS WITH `REFUSED too-large` or `REFUSED type-not-allowed`: do not
   retry and do not split the file. If the content matters, save a short text
   summary as a note instead.

5. IF A SAVE ENDS WITH `REFUSED busy`: the folder is in use. Wait 10 seconds
   and run the same command again, up to 3 times. If it is still refused after
   the third try, leave it, write a short note in your own inbox saying what
   you could not save, and say so in your final report.
   IF IT ENDS WITH `REFUSED engine-error`: treat it as not saved and read the
   message above the last line. There are two cases.
   a. The message is about what you gave the command (a missing argument, a
      file that is not there, text it cannot read, a note or value the engine
      says is not valid): correct it and try once more.
   b. Anything else: the engine or the shared copy hit a fault of its own
      (for example `hub settings unreadable`, or a git command that failed).
      Your input is probably fine. Change nothing, wait one minute, and run
      the same command again, up to 3 times. If an earlier try did arrive, the
      engine answers `SAVED` or `REFUSED note-changed` and nothing is saved
      twice.
   If it still fails, keep your result as a file in your own inbox, write the
   message into a short note there, and say so in your final report. Do not
   work around it.

6. PREFER new files over changing shared ones. Put raw output in your own
   inbox, `_inbox/agent/<your-agent-id>/`, with the place name and the time in
   the file name. Change a shared note only when the task requires it, and
   change as little of it as possible.

7. READ FRESH before you change. Read the note right before you save, not at
   the start of a long task.

8. NEVER put passwords, keys or tokens in this folder.
