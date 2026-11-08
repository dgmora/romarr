import pytest
from romarr.app import ROMarr
from romarr.downloaders import AmbiguousQueueMatch, match_queue_item
from romarr.store import QueueItem, Store

HASH = "a" * 40

def row(game, state):
    return QueueItem(game, "snes", "Demo.sfc", 1, state, release_id="btih:"+HASH, download_id=HASH)

@pytest.mark.parametrize("state", ["imported", "import-failed", "failed"])
@pytest.mark.parametrize("identity", [{"hash":HASH}, {"id":HASH}])
def test_pending_request_takes_priority_over_history(state, identity):
    pending = row("new", "grabbed")
    assert match_queue_item([row("old", state), pending], identity) is pending

def test_ambiguous_identity_is_not_arbitrarily_claimed():
    with pytest.raises(AmbiguousQueueMatch):
        match_queue_item([row("A", "grabbed"), row("B", "grabbed")], {"hash":HASH})

def test_ambiguity_is_persisted_and_does_not_mark_releases_bad(tmp_path):
    state = tmp_path/"state.json"
    s = ROMarr({"ROMARR_DATA":str(state)})
    for game in ("A", "B"): s.store.enqueue(row(game, "grabbed"))
    class Client:
        configured = True
        def completed(self): return [{"name":"Demo.sfc", "hash":HASH}]
    s.clients = [Client()]
    result = s.import_finished(retry_failed=False)
    assert not result[0]["ok"]
    restored = Store(state)
    assert [item.state for item in restored.queue] == ["import-failed"]*2
    assert all("resolve duplicate queue entries" in item.detail and not item.release_fault for item in restored.queue)


def test_archive_errors_are_visible_and_do_not_block_other_imports(tmp_path, monkeypatch):
    import subprocess
    import romarr.library as library

    state = tmp_path / "state.json"
    broken = tmp_path / "Tekken.rar"
    broken.write_bytes(b"rar")
    good = tmp_path / "Demo.sfc"
    good.write_bytes(b"rom" * 512)
    service = ROMarr({"ROMARR_DATA": str(state), "LIBRARY_KIND": "folder",
                      "LIBRARY_PATH": str(tmp_path / "library")})
    service.store.update_settings({"acquisition_only": True})
    service.store.enqueue(QueueItem("Tekken", "psx", "Tekken.rar", 1, "grabbed"))
    service.store.enqueue(QueueItem("Demo", "snes", "Demo.sfc", 1, "grabbed"))

    class Client:
        configured = True

        def completed(self):
            return [{"name": p.name, "content_path": str(p)} for p in (broken, good)]

    service.clients = [Client()]
    monkeypatch.setattr(library, "bsdtar_path", lambda: "bsdtar")
    def fail_listing(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="RAR solid archive support unavailable")
    monkeypatch.setattr(library.subprocess, "run", fail_listing)

    results = service.import_finished(retry_failed=False)
    assert [result["ok"] for result in results] == [False, True]
    rows = Store(state).queue
    assert rows[0].state == "import-failed"
    assert "RAR solid archive support unavailable" in rows[0].detail
    assert rows[1].state == "imported"


def test_nested_archive_failure_is_visible_in_queue(tmp_path, monkeypatch):
    import subprocess
    import romarr.library as library
    state = tmp_path / "state.json"
    download = tmp_path / "Bloody Roar II"
    download.mkdir()
    (download / "Bloody Roar II.7z").write_bytes(b"archive")
    service = ROMarr({"ROMARR_DATA": str(state), "LIBRARY_KIND": "folder",
                      "LIBRARY_PATH": str(tmp_path / "library")})
    service.store.enqueue(QueueItem("Bloody Roar II", "psx", "Bloody Roar II", 1, "grabbed"))

    class Client:
        configured = True

        def completed(self):
            return [{"name": download.name, "content_path": str(download)}]

    service.clients = [Client()]
    monkeypatch.setattr(library, "bsdtar_path", lambda: "bsdtar")
    def fail_listing(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="Unrecognized archive format")
    monkeypatch.setattr(library.subprocess, "run", fail_listing)
    service.import_finished(retry_failed=False)
    item = Store(state).queue[0]
    assert item.state == "import-failed"
    assert "Unrecognized archive format" in item.detail


def test_request_tag_identifies_game_before_shared_pending_hash():
    first = row("A", "grabbed")
    second = row("B", "grabbed")
    first.download_id = "qbit-tag:first"
    second.download_id = "qbit-tag:second"
    assert match_queue_item([first, second], {"hash": HASH, "tags": "second"}) is second
