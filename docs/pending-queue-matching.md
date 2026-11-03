# Repeated download identities

Completion matching prefers an eligible grabbed request over imported or failed
history sharing its torrent hash or client job id. Matching several pending
requests is ambiguous: the importer persists an actionable import failure for all
those requests instead of selecting one arbitrarily. Prior imported history is
preserved, and ambiguity does not mark the release as bad. Resolve duplicate
requests before retrying. This is queue identity handling, not a delivery receipt
or a reset of fulfilled requests when library files are removed.
