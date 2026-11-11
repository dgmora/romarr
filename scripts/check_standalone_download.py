"""Focused local checks for standalone acquisition and remote delivery."""
from pathlib import Path
import subprocess
import sys

TESTS = [
    "test_store.py", "test_folder_library.py", "test_import_match_by_id.py",
    "test_queue_persistence.py", "test_import_naming.py", "test_more_clients.py",
    "test_library.py", "test_multi_rom_import.py", "test_disc_import.py",
    "test_every_client.py", "test_reconcile_sweep.py",
    "test_transmission_completion.py", "test_pending_queue_matching.py",
    "test_atomic_publication.py", "test_acquisition_only.py",
    "test_hub_acquisition.py", "test_disc_groups.py", "test_hub_failure_visibility.py",
    "test_hub_queue_ui.py", "test_sabnzbd_failed_jobs.py",
    "test_failed_download_handling.py", "test_hub_torrent_handoff.py",
    "test_standalone_export.py", "test_delivery.py", "test_ia_auth.py",
]

if __name__ == "__main__":
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", *["tests/" + name for name in TESTS]],
        cwd=Path(__file__).resolve().parents[1]))
