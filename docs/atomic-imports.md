# Atomic import publication

Each ROM or disc set is assembled in hidden `.romarr-import-*` scratch storage
on the destination filesystem, then published only after all members have copied.
Readers and synchronization tools must ignore that scratch prefix. Publication is
per game, not a transaction for an archive containing multiple games. Flat/nested
layouts, translations, custom platform folders and DAT renaming remain supported.

Single files use exclusive hardlink publication, or atomic replacement when
explicit overwrite is requested. A complete directory is published by rename.
Empty directories can be reused; nonempty disc directories and symlink destinations
are preserved. Atomic replacement of a nonempty directory is not portable, so even
an explicit overwrite request fails with instructions to move that set aside first.

Handled copy failures clean unpublished scratch. A hard process interruption can
leave scratch behind; this change alone does not add startup or age-based cleanup.
This guarantees publication visibility during normal execution, not power-loss
durability or distributed transactions with another machine.
