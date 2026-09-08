# Publishing to the Omarchy plugin marketplace

Written 2026-09-08. Status: **submitted, under review**: #5546, filed
2026-09-08 at `90a7dd2` (v1.12.5); `main` stays parked there until it
closes (see the Submission log at the end). This mirrors what was done for `costafot.markets`
(`~/Work/omarchy-markets/PUBLISHING.md`, the short version) and
`costafot.clippy` (`~/Work/omarchy-inappropriate-clippy/PUBLISHING.md`,
the long one, with the form's fields and the prior art).

## The flow (https://plugins.omarchy.org/publish.html)

Marketplace repo: https://github.com/omacom/omarchy-plugin-marketplace
(docs there: `SUBMISSION.md`, `SECURITY.md`, `VERIFICATION.md`).

1. Repo prep: root `manifest.json`, README with install **and remove**
   commands, `LICENSE`, root `preview.png` (16:9; the marketplace makes the
   card and detail images from it). Public repo, pushed, a GitHub release
   per version (the listing links `releases/latest`). All done.
2. `omarchy plugin validate ~/Work/omarchy-android-dev` on the real
   checkout, not the symlink in `~/.config/omarchy/plugins`.
3. First submission: the "Submit a plugin" issue form, title
   `[Plugin]: Android Dev`. Later releases: the "Verify plugin" form
   (`issues/new?template=verify-plugin.yml`, action "Verify and publish a
   newer upstream commit") with the full 40-character target SHA.
4. Two bots comment on the issue: "Marketplace validation" (structure and
   Quattro compatibility at the exact commit) and "Automated security
   baseline" (`passed`, `review-required` or `needs-fixes`). Editing the
   issue body re-runs them; a comment or a push triggers nothing.
5. A maintainer reviews by hand and labels `approved-and-verified`. The
   publication bot runs separately, in batches: it labels `listed`,
   comments the URL and closes the issue. The listing will be
   https://plugins.omarchy.org/plugin.html?id=costafot.android-dev.

## The branch rule

**`main` is the marketplace.** The listing pins a commit, but the badge
follows HEAD of the default branch: the catalog re-validates every new HEAD
on its own, and any HEAD newer than the verified commit shows as
"Update unverified" until the next Verify issue is approved, docs-only
commits included. While a Verify issue is open, a push breaks the approval
outright (`update-upstream-changed`: HEAD must still be the target commit).

So `main` sits on the last release tag and moves only at release time.
Everything between releases is committed on `next`, which can be pushed
freely. A release is one sitting: merge `next` into `main`, bump
`manifest.json` and the CHANGELOG (this repo bumps them with every change,
so the merge already carries the version), tag `vX.Y.Z`, push `main`,
`gh release create vX.Y.Z --title X.Y.Z --notes-file <the CHANGELOG entry>`,
then file the Verify issue at that HEAD and record its number below. If a
fix lands while the Verify issue is still unreviewed, edit its Target
commit rather than pushing after approval.

## What the security baseline reads

The baseline flags a fixed set of tokens as capabilities and a maintainer
then has to rule on each. This tree names none of them, in prose or in
code, and `tests/test_tree.py` fails if any tracked or untracked file does
(the test assembles them from halves so it does not name them either).
The list itself is on the board, in the submission issue (COS-109), on
purpose not here. The README says "install the `android-tools` package or
the SDK platform-tools" and never gives a command line for it; keep it so.

The scanner also probes every binary asset whose file name contains
`install`, `installer`, `setup` or `uninstall` and fails closed on one it
cannot read as text (`security-baseline-scope.mjs`; seen 2026-09-08 with
`apks-installed.png`: "is not a supported text file", no approval possible).
`test_tree.py` pins that no file in the tree carries such a name. The
scanner can be run locally against a pushed commit: clone the marketplace
repo, then `runSecurityBaseline(repoUrl, sha, { requiredPaths })` from
`scripts/security-baseline.mjs` with `GITHUB_TOKEN` set (`gh auth token`);
Markets' listed commit is the control that passes. On this tree the scan
completes as `review-required` with one capability, `package-manager`: its
regex reads the word `apk` followed by `install` in any scanned text as
Alpine's package manager, and the helper's APK verb is spelled that way in
the README and in `cli.py`. Renaming the verb would look like evading the
scanner (Costa, 2026-09-08), so it stays and the maintainer notes explain
it; a maintainer accepts a capability by hand, as Clippy's were.

What a maintainer will read, and what the notes below say up front:

- The QML never runs `adb`. One Python helper (`bin/omarchy-android-dev`,
  stdlib only, no pip, no venv, no binaries) is started as
  `/usr/bin/python3 <plugin dir>/bin/omarchy-android-dev …` through
  `/bin/sh -c 'exec "$0" "$@"'`, absolute interpreter and absolute path,
  and answers one JSON line; every error rides inside the JSON and the
  helper never crashes. Every adb call is an argument list with `-s SERIAL`,
  a deadline and an output cap, never a shell string; the whole run has a
  60 s alarm and the store a SIGTERM/SIGKILL pair behind it.
- Children: `adb` (the user's own), `omarchy-notification-send`, `wl-copy`
  and `wl-paste` as argv; `scrcpy`, the SDK `emulator` and
  `xdg-terminal-exec` for logcat, launched detached through `uwsm-app` the
  way Omarchy's launchers do and never signalled; `qrencode` for the pairing
  QR with the payload on its stdin. Nothing is killed by name, no PID
  files, no `/tmp`.
- Network: none of the plugin's own. adb talks to its server on
  `127.0.0.1:5037`, to the device over USB, and to a phone's address on the
  LAN for wireless debugging; adb's mDNS discovery is multicast on that LAN.
  No internet, no accounts, no telemetry.
- State in `~/.local/state/omarchy/costafot.android-dev/` (0700, checked on
  every run, atomic 0600 writes; the pairing PNG while a session runs).
  Config writes: only the plugin's own entry in `~/.config/omarchy/shell.json`
  on Save in the Settings page, one `updateEntryInline`.
- The device changes it makes are the ones the user asks for on a page:
  developer toggles, `pm clear`, `uninstall` (behind a dialog), `install`,
  permission grants, `input text`, key events, `wm density`, the font
  scale, dark mode. The pairing code goes to `adb pair` on stdin, never on
  an argv.
- Every QML `Text` is `Text.PlainText`; `preview.png` and the screenshots
  are my own captures.

## What the maintainer's review refuses

The bots are the first gate; a maintainer reads the tree after them and
applies `needs-fixes` for what the scanner cannot see. Seen on this
submission and on four others in the same week (2026-09-06 to 2026-09-08,
the same reviewer): a root `AGENTS.md` in the validated commit. The
installed folder is the repository cloned whole and the manifest
has no packaging exclusion, so a coding agent opened in or above it reads
that file as instructions nobody reviewed. The fix every submitter made is
the file leaving the tree, and that is this repo's rule since 1.13.0: the
reference is `docs/reference.md`, the session notes are an untracked
`AGENTS.md` that `.gitignore` keeps out (with `CLAUDE.md`), and
`tests/test_tree.py` refuses a tracked agent-instruction file at any depth.
The same reviewer had listed omarchy-markets with its `AGENTS.md` in place,
so an update to that plugin will meet the rule too.

## The form (first submission)

- Category: Developer Tools. Tags: Bar, Quickshell; suggested tag
  "android".
- Maintainer notes: the bullets above, in prose, with the current HEAD SHA
  and the release URL.
- Five checkboxes, all ticked; the six headings must stay in order or the
  bot ignores the issue.

## After it's listed

- Add the marketplace URL to the README under the install command, on
  `next`, and it ships with the next release (a docs-only push to `main`
  turns the badge to "Update unverified").
- Close COS-109 on the board with the issue number and the listing URL; the
  projects page entry on the site gains its Marketplace link.

## Submission log

- 2026-09-08: v1.12.4 tagged and released; `next` branched off `main` for
  the work between releases. Running the baseline scanner locally against
  that commit failed closed on `apks-installed.png` (the rule above), so
  v1.12.5 renames the screenshot and is the commit submitted, with the
  `package-manager` capability above disclosed in the notes. Filed as
  **#5546** (https://github.com/omacom/omarchy-plugin-marketplace/issues/5546),
  Developer Tools, bar + quickshell, suggested tag "android", at
  `90a7dd27eba5f5350856deae868c5e4155251ae5`. Both bots answered in a
  minute: validation passed, the baseline `review-required` with the one
  capability.
- 2026-09-08 07:12 UTC: the maintainer marked #5546 `needs-fixes` over the
  root `AGENTS.md` (the rule above), with the full review of the adb, APK,
  wireless and process surface to follow at the corrected SHA. v1.13.0
  moves the reference to `docs/reference.md`; tagged and released at
  `91acdb892a94eb53d7639ae88463b41390c3c2e7`, `main` fast-forwarded onto
  it, the issue body edited to name that commit (an edit reruns both bots)
  and a comment left for the maintainer with the diff summary. The full
  review is theirs from here.
