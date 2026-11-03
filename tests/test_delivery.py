"""Exercise production delivery against a real rsync daemon."""

import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "romarr/delivery.py"
spec = importlib.util.spec_from_file_location("delivery", SCRIPT)
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o755)
        self.source, self.stage, self.library = [self.root / p for p in ("source", "stage", "library")]
        for p in (self.source, self.stage, self.library):
            p.mkdir()
        self.uid, self.gid = os.getuid(), os.getgid()
        groups = Path("/proc/self/setgroups")
        self.daemon_mode = not (self.uid == 0 and groups.exists()
                                and groups.read_text().strip() == "deny")
        if not self.daemon_mode:
            # This sandbox maps only root and prohibits setgroups. Exercise
            # real local rsync here; ordinary CI also exercises daemon access.
            self.url = f"{self.source}/"
            return
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = self.root / "rsyncd.conf"
        self.config = config
        config.write_text(f"""pid file = {self.root}/rsyncd.pid
use chroot = false
[games]
path = {self.source}
read only = false
uid = {self.uid}
gid = {self.gid if self.uid == 0 else ''}
hosts allow = 127.0.0.1
exclude = .romarr-import-*/
""")
        self.daemon = subprocess.Popen(["rsync", "--daemon", "--no-detach",
            f"--config={config}", f"--port={port}", "--address=127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_daemon)
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    break
            except OSError:
                if self.daemon.poll() is not None:
                    self.fail("rsync daemon failed to start")
                time.sleep(.01)
        else:
            self.fail("rsync daemon did not become ready")
        self.url = f"rsync://127.0.0.1:{port}/games/"

    def stop_daemon(self):
        self.daemon.terminate()
        self.daemon.wait(timeout=5)

    def put(self, name, data=b"ROM"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def deliver(self):
        delivery.transfer(self.url, self.stage, self.library)

    def test_platforms_staging_and_existing_identical_game(self):
        for slug in ("sms", "turbografx16--1", "sega32", "neogeomvs", "lynx", "famicom"):
            self.put(f"{slug}/Demo.zip")
        self.put(".romarr-import-abandoned/snes/Unfinished.sfc")
        (self.library / "sms").mkdir()
        existing = self.library / "sms/Demo.zip"
        existing.write_bytes(b"ROM")
        inode = existing.stat().st_ino
        self.deliver()
        self.assertEqual(existing.stat().st_ino, inode)
        for slug in ("sms", "turbografx16--1", "sega32", "neogeomvs", "lynx", "famicom"):
            self.assertEqual((self.library / slug / "Demo.zip").read_bytes(), b"ROM")
            self.assertFalse((self.source / slug / "Demo.zip").exists())
        self.assertFalse((self.library / "snes/Unfinished.sfc").exists())

    def test_complete_disc_directory_is_published_once(self):
        self.put("psx/Demo/Demo.cue", b'FILE "Demo.bin" BINARY')
        self.put("psx/Demo/Demo.bin", b"track" * 256)
        original = delivery.os.link
        observations = []
        def link(source, dest, **kw):
            observations.append((self.library / "psx/Demo").exists())
            return original(source, dest, **kw)
        with patch.object(delivery.os, "link", side_effect=link):
            self.deliver()
        self.assertTrue(observations)
        self.assertFalse(any(observations))
        self.assertEqual({p.name for p in (self.library / "psx/Demo").iterdir()}, {"Demo.cue", "Demo.bin"})
        self.assertFalse((self.source / "psx/Demo/Demo.bin").exists())

    def test_successive_translations_publish_individual_games(self):
        self.put("psx/Translations/GameA/GameA.bin", b"track A")
        self.put("psx/Translations/GameA/GameA.cue", b'FILE "GameA.bin" BINARY')
        self.deliver()
        first = self.library / "psx/Translations/GameA/GameA.bin"
        inode = first.stat().st_ino
        self.put("psx/Translations/GameB/GameB.bin", b"track B")
        self.put("psx/Translations/GameB/GameB.cue", b'FILE "GameB.bin" BINARY')
        self.put("snes/Translations/GameC.sfc", b"translated ROM")
        original = delivery.os.link
        def link(source, destination, **kw):
            if Path(source).parent.name == "GameB":
                self.assertFalse((self.library / "psx/Translations/GameB").exists())
            return original(source, destination, **kw)
        with patch.object(delivery.os, "link", side_effect=link):
            self.deliver()
        self.assertEqual(first.stat().st_ino, inode)
        self.assertEqual((self.library / "psx/Translations/GameB/GameB.bin").read_bytes(), b"track B")
        self.assertEqual((self.library / "snes/Translations/GameC.sfc").read_bytes(), b"translated ROM")
        self.assertFalse((self.source / "psx/Translations/GameB/GameB.bin").exists())

    def test_nested_layout_is_rejected_without_publication_or_cleanup(self):
        source = self.put("psx/roms/GameA.chd")
        with self.assertRaisesRegex(ValueError, "nested library layout"):
            self.deliver()
        self.assertTrue(source.exists())
        self.assertTrue((self.stage / "psx/roms/GameA.chd").exists())
        self.assertFalse((self.library / "psx/roms").exists())

    def test_conflict_preserves_all_copies_and_returns_failure(self):
        source = self.put("snes/Demo.sfc", b"new")
        (self.library / "snes").mkdir()
        existing = self.library / "snes/Demo.sfc"
        existing.write_bytes(b"old")
        with self.assertRaisesRegex(RuntimeError, "conflicting games"):
            self.deliver()
        self.assertEqual(existing.read_bytes(), b"old")
        self.assertEqual(source.read_bytes(), b"new")
        self.assertEqual((self.stage / "snes/Demo.sfc").read_bytes(), b"new")

    def test_failed_pull_does_not_publish_or_delete(self):
        source = self.put("snes/Demo.sfc")
        with patch.object(delivery.subprocess, "run", side_effect=subprocess.CalledProcessError(23, "rsync")):
            with self.assertRaises(subprocess.CalledProcessError):
                self.deliver()
        self.assertTrue(source.exists())
        self.assertFalse((self.library / "snes/Demo.sfc").exists())

    def test_sigkill_after_publication_is_recovered(self):
        source = self.put("psx/Demo/Demo.bin", b"track")
        self.put("psx/Demo/Demo.cue", b'FILE "Demo.bin" BINARY')
        code = """import importlib.util, os, signal, sys
spec=importlib.util.spec_from_file_location('delivery', sys.argv[1])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
original=m.publish
def publish(*args):
    original(*args)
    os.kill(os.getpid(), signal.SIGKILL)
m.publish=publish
m.transfer(*sys.argv[2:])
"""
        result = subprocess.run([sys.executable, "-c", code, str(SCRIPT), self.url,
                                 str(self.stage), str(self.library)])
        self.assertEqual(result.returncode, -9)
        self.assertTrue(source.exists())
        self.assertTrue((self.stage / "psx/Demo/Demo.bin").exists())
        self.assertEqual((self.library / "psx/Demo/Demo.bin").read_bytes(), b"track")
        self.deliver()
        self.assertFalse(source.exists())
        self.assertFalse((self.stage / "psx/Demo").exists())

    def test_cleanup_failure_is_retried_without_replacing_library(self):
        source = self.put("snes/Demo.sfc")
        original = delivery.subprocess.run
        def run(args, **kwargs):
            if "--remove-source-files" in args:
                raise subprocess.CalledProcessError(23, args)
            return original(args, **kwargs)
        with patch.object(delivery.subprocess, "run", side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                self.deliver()
        inode = (self.library / "snes/Demo.sfc").stat().st_ino
        self.assertTrue(source.exists())
        self.deliver()
        self.assertEqual((self.library / "snes/Demo.sfc").stat().st_ino, inode)
        self.assertFalse(source.exists())

    def test_cleanup_acknowledgement_loss_keeps_published_and_staging_copies(self):
        source = self.put("snes/Demo.sfc")
        original = delivery.subprocess.run
        def run(args, **kwargs):
            result = original(args, **kwargs)
            if "--remove-source-files" in args:
                # Sender deletion happened, but the receiver did not observe
                # successful completion (e.g. connection/process loss).
                raise subprocess.CalledProcessError(23, args)
            return result
        with patch.object(delivery.subprocess, "run", side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                self.deliver()
        self.assertFalse(source.exists())
        self.assertEqual((self.stage / "snes/Demo.sfc").read_bytes(), b"ROM")
        self.assertEqual((self.library / "snes/Demo.sfc").read_bytes(), b"ROM")
        self.deliver()
        self.assertFalse((self.stage / "snes/Demo.sfc").exists())

    def test_interrupted_retired_deletion_recovers(self):
        self.put("psx/Demo/Demo.bin", b"track")
        self.put("psx/Demo/Demo.cue", b'FILE "Demo.bin" BINARY')
        original = delivery.shutil.rmtree
        def remove(path, *args, **kwargs):
            path = Path(path)
            if path.name.startswith(".retired-") and (path/"game").is_dir():
                next((path/"game").iterdir()).unlink()
                raise OSError("interrupted deletion")
            return original(path, *args, **kwargs)
        with patch.object(delivery.shutil, "rmtree", remove):
            with self.assertRaisesRegex(OSError, "interrupted deletion"):
                self.deliver()
        self.assertFalse((self.stage/"psx/Demo").exists())
        self.assertEqual(list((self.source/"psx/Demo").iterdir()), [])
        self.deliver()
        self.assertEqual(list(self.stage.glob(".retired-*")), [])
        self.assertEqual({p.name for p in (self.library/"psx/Demo").iterdir()}, {"Demo.bin", "Demo.cue"})

    def test_sigkill_during_retired_deletion_recovers(self):
        self.put("psx/Demo/Demo.bin", b"track")
        self.put("psx/Demo/Demo.cue", b'FILE "Demo.bin" BINARY')
        code = """import importlib.util, os, signal, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('delivery', sys.argv[1])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
original=m.shutil.rmtree
def remove(path, *args, **kwargs):
    path=Path(path)
    if path.name.startswith('.retired-') and (path/'game').is_dir():
        next((path/'game').iterdir()).unlink()
        os.kill(os.getpid(), signal.SIGKILL)
    return original(path, *args, **kwargs)
m.shutil.rmtree=remove
m.transfer(*sys.argv[2:])
"""
        result = subprocess.run([sys.executable, "-c", code, str(SCRIPT), self.url,
                                 str(self.stage), str(self.library)])
        self.assertEqual(result.returncode, -9)
        self.assertFalse((self.stage / "psx/Demo").exists())
        self.assertEqual(list((self.source / "psx/Demo").iterdir()), [])
        retired = list(self.stage.glob(".retired-*/game"))
        self.assertEqual(len(retired), 1)
        self.assertEqual(len(list(retired[0].iterdir())), 1)
        self.assertEqual({p.name for p in (self.library / "psx/Demo").iterdir()}, {"Demo.bin", "Demo.cue"})
        self.deliver()
        self.assertEqual(list(self.stage.glob(".retired-*")), [])


    def test_read_only_daemon_refuses_cleanup_without_losing_staging(self):
        if not self.daemon_mode:
            self.skipTest("sandbox prohibits rsync daemon setgroups; run on ordinary CI")
        source = self.put("snes/Demo.sfc")
        self.config.write_text(self.config.read_text().replace("read only = false", "read only = true"))
        with self.assertRaises(subprocess.CalledProcessError):
            self.deliver()
        self.assertTrue(source.exists())
        self.assertTrue((self.stage / "snes/Demo.sfc").exists())
        self.assertEqual((self.library / "snes/Demo.sfc").read_bytes(), b"ROM")
        self.config.write_text(self.config.read_text().replace("read only = true", "read only = false"))
        self.deliver()
        self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()

