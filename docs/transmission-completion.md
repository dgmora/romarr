# Transmission completion and ownership

Transmission clients accept a download directory, expose the returned torrent
hash as the job identity and poll fully completed, nonempty torrents. Polling
filters by the configured label and directory before returning import paths.
Paths come from actual torrent files, which may differ from the display name.
Multiple files must share a safe root; metadata must be complete before import.

A duplicate submission is accepted only when the existing torrent's hash, label
and directory match. A foreign or uninspectable duplicate fails without moving,
relabeling or deleting an existing torrent. This matters when several applications
share the same Transmission instance. Configure a dedicated label and directory
when duplicate adoption is required. RPC failures remain visible to the importer.

Labelled submissions discover and cache the RPC version through `session-get`.
A successful connection test supplies that cache. RPC 17 and later receive labels
in `torrent-add`. RPC 16 receives labels through `torrent-set` only after a new
torrent is created, then its hash, label and destination are verified. Failed
capability discovery or RPC versions below 16 refuse labelled submissions before
adding anything. Post-add labelling or verification failures report failure and
leave the torrent intact for inspection. Vuze and BiglyBT use the same capability
checks through their Transmission RPC plugins.

Tests simulate RPC responses and exercise the existing 409 handshake; they do not
claim compatibility with a running Transmission daemon or all RPC-compatible forks.
