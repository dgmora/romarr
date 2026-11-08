# Remote standalone acquisition and delivery

This integration profile combines Transmission completion, queue matching,
atomic imports, acquisition-only behavior and authenticated ROM Hub access.
Potential upstream contributions will be extracted from the tested integration;
the deployment-specific profile and delivery helper remain separate.

On the acquisition host set `ROMARR_STANDALONE_EXPORT=1`, `LIBRARY_KIND=folder`
and `LIBRARY_PATH` to a private outgoing folder. Startup enables acquisition-only
mode, flat layout and no overwrite, normalizes the managed library row and removes
abandoned `.romarr-import-*` scratch before the import scheduler starts. Published
exports and download-client seeding data are retained. Do not share a state file
or outgoing folder between multiple ROMarr processes.

The receiving host runs:

```sh
python -m romarr.delivery rsync://sender/games/ /data/incoming /data/library
```

`incoming` must be persistent, outside the watched library, on the same filesystem
as the library. Run only one delivery process against it at a time. The sender's
rsync module must expose only the outgoing folder and allow writes for acknowledged
source cleanup. Restrict that access to the receiving host; it is not a delete-only
permission. Authentication and network policy belong to the deployment.

Delivery pulls without removing sources, publishes complete games using hardlinks
and directory rename, flushes publication, then checksum-acknowledges only matching
files. It keeps staging until sender cleanup succeeds. Identical games are cleaned
up; conflicts preserve all copies and fail visibly. Translations are containers
of individual games. Nested `platform/roms` exports are refused.

After acknowledgement, staging is atomically moved into `.retired-*` storage and
both sides of the rename are flushed before deletion. Interrupted deletion is
retried without comparing partial leftovers against published games. Never clear
active incoming staging at startup or based on age. Failed imports remain distinct
from successful exports; deleting an exported copy does not reset imported queue
history or fulfilled Wanted requests. Original torrent data is not deleted.

Tests exercise real local rsync, a daemon where permitted, publication, conflicts,
cleanup failure, lost acknowledgement, interrupted retirement and SIGKILL. These
tests do not establish real power-loss behavior, filesystem durability guarantees,
network policy, download-client compatibility or library-watcher behavior.
