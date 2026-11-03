# Acquisition-only mode

Enable **Acquisition only** in Settings → Media Management, or set
`acquisition_only: true` through the settings API. It defaults to false.

Use this when ROMarr imports into an outgoing folder and a separate process
moves completed games into a permanent library. Successful imports still fulfil
Wanted requests and persist imported queue entries. Removing those outgoing
files, including across a restart, does not make completed queue entries eligible
for another import or automatically recreate Wanted requests.

Automatic post-import rescans and reconciliation are suppressed in this mode.
Explicit collection reconciliation returns a skipped result without inspecting
the outgoing folder. Disabling the mode restores normal library management.
`reconcile_after_import` is also a supported independent setting.

The local library browser and collection tools still see only that outgoing
folder. This mode does not add remote collection awareness, confirm delivery,
or prevent a user from explicitly requesting an already delivered game. A failed
or incomplete import is not a delivered acquisition. The delivery process must
publish complete games and retain retry state before deleting outgoing files.
