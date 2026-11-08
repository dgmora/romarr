# Transmission completion and ownership

Transmission clients accept a download directory, expose the returned torrent
hash as the job identity and poll fully completed, nonempty torrents. Polling
filters by the configured label and directory before returning import paths.

A duplicate submission is accepted only when the existing torrent's hash, label
and directory match. A foreign or uninspectable duplicate fails without moving,
relabeling or deleting an existing torrent. This matters when several applications
share the same Transmission instance. Configure a dedicated label and directory
when duplicate adoption is required. RPC failures remain visible to the importer.

Tests simulate RPC responses and exercise the existing 409 handshake; they do not
claim compatibility with a running Transmission daemon or all RPC-compatible forks.
