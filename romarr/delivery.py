"""Deliver immutable ROMarr imports, publish whole games, then clean the sender.

Staging must be outside RomM's watched root and on the same filesystem. Keep
it across failures: it is retry state, not disposable temporary storage.
"""

import filecmp
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def files(path):
    if path.is_symlink():
        raise ValueError(f"symlinks are not supported: {path}")
    entries = [path] if not path.is_dir() else list(path.rglob("*"))
    for entry in entries:
        if entry.is_symlink():
            raise ValueError(f"symlinks are not supported: {entry}")
        if entry.is_file():
            yield entry
        elif not entry.is_dir():
            raise ValueError(f"not a regular file or directory: {entry}")


def identical(left, right):
    if left.is_symlink() or right.is_symlink():
        return False
    if left.is_dir() != right.is_dir():
        return False
    if left.is_file():
        return right.is_file() and filecmp.cmp(left, right, shallow=False)
    a = {p.relative_to(left): p for p in files(left)}
    b = {p.relative_to(right): p for p in files(right)}
    return a.keys() == b.keys() and all(
        filecmp.cmp(a[name], b[name], shallow=False) for name in a)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable(path):
    for entry in files(path):
        with entry.open("rb") as handle:
            os.fsync(handle.fileno())
    if path.is_dir():
        for entry in sorted(path.rglob("*"), reverse=True):
            if entry.is_dir():
                sync_directory(entry)
        sync_directory(path)
    sync_directory(path.parent)


def games(platform):
    for entry in sorted(platform.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.name == "roms" and entry.is_dir():
            raise ValueError(f"nested library layout is unsupported; retained {entry}")
        if entry.name == "Translations":
            if entry.is_symlink() or not entry.is_dir():
                raise ValueError(f"invalid translation container: {entry}")
            yield from (game for game in sorted(entry.iterdir())
                        if not game.name.startswith("."))
        else:
            yield entry


def publish(staging, library):
    ready = []
    conflicts = []
    # These contain only extra hardlinks; canonical staging and sender files
    # remain intact even if a previous publisher was killed here.
    for scratch in staging.glob(".publish-*"):
        if scratch.is_symlink():
            scratch.unlink()
        else:
            shutil.rmtree(scratch)
    for platform in sorted(staging.iterdir()):
        if platform.name.startswith("."):
            continue
        if platform.is_symlink() or not platform.is_dir():
            raise ValueError(f"invalid platform directory: {platform}")
        destination_root = library / platform.name
        if destination_root.is_symlink():
            raise ValueError(f"symlink destination: {destination_root}")
        destination_root.mkdir(exist_ok=True)
        for game in games(platform):
            members = list(files(game))
            if not members:
                continue
            destination = library / game.relative_to(staging)
            if destination.parent.is_symlink():
                raise ValueError(f"symlink destination: {destination.parent}")
            destination.parent.mkdir(exist_ok=True)
            if destination.exists() or destination.is_symlink():
                if not identical(game, destination):
                    conflicts.append(str(game.relative_to(staging)))
                    print(f"ROMarr conflict retained: {game} -> {destination}", file=sys.stderr)
                    continue
            elif game.is_file():
                # link() refuses an existing destination; never replace it.
                os.link(game, destination)
            else:
                with tempfile.TemporaryDirectory(prefix=".publish-", dir=staging) as tmp:
                    candidate = Path(tmp) / "game"
                    shutil.copytree(game, candidate, copy_function=os.link)
                    candidate.rename(destination)
            # Flush data and directory entries BEFORE acknowledging delivery.
            durable(destination)
            # Translations adds another directory entry below the platform.
            for parent in destination.parents:
                sync_directory(parent)
                if parent == library:
                    break
            ready.append(game.relative_to(staging))
    return ready, conflicts


def discard_retired(staging):
    # Retired entries have already been published and acknowledged. They must
    # never re-enter incoming-game comparison, even after a partial deletion.
    for path in staging.glob(".retired-*"):
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
    sync_directory(staging)


def retire(game, staging):
    retired = Path(tempfile.mkdtemp(prefix=".retired-", dir=staging))
    game.rename(retired / "game")
    # Persist both sides of the rename BEFORE deleting any members. A crash
    # leaves a complete incoming game or disposable retired content.
    sync_directory(retired)
    sync_directory(game.parent)
    sync_directory(staging)
    shutil.rmtree(retired)
    sync_directory(staging)


def transfer(source, staging, library):
    staging, library = Path(staging), Path(library)
    staging.mkdir(parents=True, exist_ok=True)
    library.mkdir(parents=True, exist_ok=True)
    if staging.is_symlink() or library.is_symlink():
        raise ValueError("staging and library must be real directories")
    if staging == library or staging.is_relative_to(library) or library.is_relative_to(staging):
        raise ValueError("staging must be outside the watched library")
    if staging.stat().st_dev != library.stat().st_dev:
        raise ValueError("staging and library must share a filesystem")
    discard_retired(staging)
    common = ["rsync", "-a", "--no-owner", "--no-group", "--delay-updates",
              "--partial-dir=.rsync-partial", "--prune-empty-dirs", "--fsync",
              "--exclude=.romarr-import-*/", "--exclude=.rsync-partial/",
              "--chmod=F664,D2775", "--outbuf=L", "--progress",
              "--out-format=RSYNC_FILE\t%i\t%l\t%n"]
    # A failed pull publishes nothing. Existing staging files are retained;
    # immutable published source games cannot acquire additional members.
    subprocess.run(common + ["--ignore-existing", source, f"{staging}/"], check=True)
    ready, conflicts = publish(staging, library)
    if ready:
        acknowledged = [str(p.relative_to(staging)) for game in ready
                        for p in files(staging / game)]
        # Keep staging hardlinks until this second pass succeeds. Checksums
        # handle lost acknowledgements without modifying the live library.
        subprocess.run(common + ["--existing", "--checksum", "--remove-source-files", "--ignore-missing-args",
                                 "--from0", "--files-from=-", source, f"{staging}/"],
                       input=b"".join(os.fsencode(p) + b"\0" for p in acknowledged), check=True)
        for relative in ready:
            game, destination = staging / relative, library / relative
            filecmp.clear_cache()
            if not identical(game, destination):
                raise RuntimeError(f"source changed during cleanup; retained {game}")
            retire(game, staging)
    if conflicts:
        raise RuntimeError("conflicting games require attention: " + ", ".join(conflicts))


if __name__ == "__main__":
    transfer(*sys.argv[1:])
