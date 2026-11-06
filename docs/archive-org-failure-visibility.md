# Hub failure visibility

Hub acquisitions keep their synchronous fetch/import execution. Queue displays
Failed with the recorded cause; Search again runs the existing release search.
No live transfer progress, automatic retries, background worker, or file deletion
is introduced. Unresolved Hub failures block automatic acquisition for their
game/platform until Search again or Remove/Clear successfully dismisses the job.
Other download clients retain their existing failure and retirement policy.

Each ledger job has an `id`. Queue stores it in `download_id`, scoped by the
configured client `id` in `download_client`; `download_protocol` identifies Hub
rows even if the client is removed. `hub_acceptance` distinguishes accepted,
definitively rejected, and uncertain handoffs. `hub_failure_recorded` prevents
repeated History failures. Rejected handoffs need no ledger dismissal; uncertain
handoffs require identity repair. A failed result write is retained in memory
with its error and fenced against another fetch. Recovery after a process crash
before that result can be persisted is deferred.

## Repairing legacy identity

Stop ROMarr and back up its JSON store (`ROMARR_DATA`) and every referenced Hub
client's `save_path/.romarr-hub.json` before editing either. On Plank these are
`/var/lib/romarr/romarr.json` and
`/var/lib/romarr/hub-downloads/.romarr-hub.json`.

In the store, inspect `queue` and `settings.download_clients`: bind a Queue row's
`download_client` to the proven configured client `id`. Compare its exact
`release`, `release_id`, `indexer`, and `size` against that client's ledger jobs'
`name` and decoded `url` release metadata. Titles alone do not resolve duplicate
acquisitions. Bind `download_id` only to one proven job's `id`. Old jobs without
an ID acquire a deterministic `legacy-` ID from SHA-256 of their sorted JSON
record; persist that ID in the backed-up ledger before using it in the store.
Use the adapter's `_read()` result to obtain that exact ID, without changing the
job's other fields. Do not invent an ID or select among ambiguous candidates.

If no match is proven, leave the row unresolved. A confirmed orphan can be
removed from the backed-up store only after inspecting all referenced ledgers.
Restart ROMarr, run Import completed, and verify the binding before a Queue
action. Search again and Remove refuse active fetch/import operations and failed
ledger writes; they do not cancel a synchronous operation already running.

## Regression evidence

Run `python scripts/check_standalone_download.py` with pytest, requests, the
Flake-pinned ROM Hub, Node.js, libarchive, and rsync on PATH. Node.js executes the
Queue renderer regression; without it that one check is explicitly skipped.

`tests/test_hub_failure_visibility.py` covers scheduled ImportCompleted with
retirement disabled/no release ID; metadata 503 and History deduplication across
sweeps/restarts; scheduled Wanted search guarding; unique/ambiguous/missing
legacy identity; thread-local handoff IDs and concurrent Queue grabs; duplicate
pending acceptance; Search again/removal/bulk dismissal; stale and mismatched
identities; active fetch/import conflicts; overlapping fetch/add/dismiss;
atomic replacement and handoff/result/dismissal write failures; retained failed
and successful results; mixed bulk refusal; linked failure, replacement and
available status; and definitive rejection versus uncertain acceptance.

`tests/test_hub_queue_ui.py` executes the actual Queue renderer and handlers,
checking failure detail, Search again, identity submission, and both bulk
refusals remaining visible after refreshing rows. Existing Hub acquisition,
torrent handoff, SABnzbd failure/retirement, standalone import, authentication,
and rsync delivery tests run in the same gate.

Deployment and live Archive.org end-to-end acquisition remain separate checks.
