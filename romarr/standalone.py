"""Opt-in profile for an immutable outgoing spool and a separate receiver.

This profile is maintained on the integration branch, not proposed as a default
library policy. Configure it only before importer/scheduler work can start.
"""
from pathlib import Path
import os
import shutil


def configure_export(store, library):
    library = Path(library)
    store.settings.update({"acquisition_only": True, "standalone_export": True,
                           "library_layout": "flat", "rescan_after_import": False,
                           "reconcile_after_import": False, "overwrite_existing": False})
    for entry in store.list_items("libraries"):
        if entry.get("type") == "folder" and entry.get("path") == str(library):
            store.put_item("libraries", {**entry, "layout": "flat"})
    # Do not follow symlinked directories. Only abandoned unpublished scratch
    # is disposable; never clean receiver staging or published exports here.
    for directory, names, _ in os.walk(library, followlinks=False):
        for name in list(names):
            if not name.startswith(".romarr-import-"):
                continue
            names.remove(name)
            scratch = Path(directory)/name
            if scratch.is_symlink():
                scratch.unlink()
            else:
                shutil.rmtree(scratch)
    store.save()
