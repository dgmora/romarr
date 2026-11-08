# Develop consolidation review

The integration branch is `develop`. Its checkout directory remains
`remote-standalone-download` so existing terminal paths continue to work.

## Completed

- PRs #1–#6 are closed. The seven obsolete local branch tips are retained under
  `refs/archive/retired/`; their worktrees, local branches and associated Herdr
  workspaces are removed. Remote branches, `main`, and the pre-rebase backup remain.
- New game directories publish after staging. Explicit overwrite of an existing
  nonempty directory replaces individual members and preserves unrelated files.
  The outgoing-folder profile still rejects overwrite.
- Completion matching scopes by configured client and prefers request identity
  before a shared release hash. Transmission submission identities are thread-local.
- Transmission normalizes file completion, wanted flags, native priorities and
  torrent state. Existing DAT source jobs save and verify selection restoration.
  External selection/file-identity changes require review instead of being overwritten.
- Authentication remains in ROM Hub. ROMarr's search now applies upstream platform
  filtering and per-plugin limits even when the authenticated batch fails.
- Hub ledger identity, locked writes, active operation claims and safe dismissal
  have separate responsibilities. Synchronous execution and search-based retry remain.

## Required work before completion

Transmission exact-file magnet acquisition, additive retained reuse, explicit
retained resume and per-request completion still use qBittorrent-only application
paths. Transmission parity is incomplete. Selective magnets must remain refused;
ordinary add must never be used as fallback. Successful metadata acquisition with
no unintended payload transfer remains a prerequisite for enabling that path.

Validate shared collection scenarios across both clients, including restarts,
ownership changes and failures. Complete independent contribution extraction,
validation and the five draft PRs against the fork's main. Refresh the existing
ROM Hub authentication PR and link it from the ROMarr authentication PR.

No Transmission daemons or payload downloads may run on this development machine.
Real-daemon and authenticated Archive.org listing/download gates require an
explicitly designated isolated host. Production deployment/configuration remains
outside this task.

## Verification record

The focused mocked and local import checks after the review passed: 151 passed,
2 skipped. This covers publication, overwrite, bundle intent, matching, Transmission
adapter responses, DAT source selection/restoration, retained qBittorrent handling,
authentication, Hub failure visibility and Queue rendering.

An earlier full offline run reported 2939 passed, 4 skipped and 13 failures.
Twelve delivery failures came from system rsync lacking --fsync; rerunning delivery
with modern rsync passed all 13 tests. A later full run was interrupted following
the instruction to stop local daemon/transfer tests; it is not a full-suite pass.
Real-daemon experiments performed before that instruction proved file selection
and paused-state restoration, but did not establish safe magnet metadata acquisition.

## Separate handoff

The ClamAV fake-server stream-limit test consistently receives a connection reset
on this macOS environment. Its code and test are unchanged from main. No ClamAV
changes were made as part of this consolidation.
