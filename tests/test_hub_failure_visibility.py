import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from romarr import hub
from romarr.app import ROMarr
from romarr.downloaders import HubConfig, HubDownloader, hand_off_with_id
from romarr.selection import Release
from romarr.store import SeerrRequest

ROW = {"source_id": "ia:crash2", "title": "Crash Bandicoot 2", "platform": "psx",
       "size_bytes": 100, "plugin": "archive-org", "extra": {},
       "url": "https://archive.org/details/crash2"}


def setup(tmp_path, fetch=None):
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "store.json")})
    client = HubDownloader(HubConfig(save_path=str(tmp_path / "downloads")),
                           fetch=fetch or (lambda *a: {"ok": False, "error": "metadata HTTP 503"}))
    client.romarr_id = "hub-client"
    service.clients = [client]
    service.store.settings.update(blocklist_failed_downloads=False, auto_import=True,
                                  auto_import_interval_minutes=1)
    return service, client


def release(source="ia:crash2", title="Crash Bandicoot 2"):
    return Release(title=title, size=100, seeders=0, indexer="hub:archive-org",
                   protocol="hub", categories=(),
                   download_url=hub.encode_result({**ROW, "source_id": source, "title": title}))


def grab(s, **kw):
    assert s.grab(release(), "Crash 2", "psx", **kw)["ok"]
    return s.queue[-1]


def identity(item):
    return {k: getattr(item, k) for k in ("at", "download_id", "download_client", "release")}


def failures(s):
    return [e for e in s.store.history(100) if e["kind"] == "failed"]


def test_scheduled_import_reconciles_without_retirement_or_release_id(tmp_path, monkeypatch):
    s, c = setup(tmp_path)
    q = grab(s)
    q.release_id = ""
    monkeypatch.setattr(s, "retire_dead_downloads", lambda: pytest.fail("retirement invoked"))
    task = next(j for j in s.scheduler._jobs if j.name == "ImportCompleted")
    assert task.interval() > 0
    task.run()
    assert q.state == "failed" and q.detail == "metadata HTTP 503"
    assert q.release_fault is False
    task.run()
    assert len(failures(s)) == 1
    monkeypatch.setattr(s, "request", lambda *a, **kw: pytest.fail("automatic replacement"))
    s.store.want(q.game, q.platform)
    search = next(j for j in s.scheduler._jobs if j.name == "MissingGameSearch")
    search.run()
    s.store.settings["blocklist_failed_downloads"] = True
    assert ROMarr.retire_dead_downloads(s)["blocklisted"] == 0
    assert s.store.list_items("blocklist") == []


@pytest.mark.parametrize("match", ["unique", "ambiguous", "missing"])
def test_legacy_matching_and_actions(tmp_path, match):
    s, c = setup(tmp_path)
    q = grab(s)
    q.download_id = ""
    rows = c._read()
    rows[0].pop("id")
    rows[0].update(state="failed", detail="metadata HTTP 503")
    if match == "ambiguous":
        rows.append({**rows[0], "at": "different acquisition"})
    if match == "missing":
        rows = []
    c._write(rows)
    s.import_finished(retry_failed=False)
    assert q.state == "failed"
    if match == "unique":
        assert q.download_id and q.detail == "metadata HTTP 503"
        assert len(failures(s)) == 1
    else:
        assert "repair" in q.detail
        before = c._read()
        for action in ("retry", "remove"):
            assert not s.queue_action(0, action, identity(q))["ok"]
        assert c._read() == before
        assert s.queue == [q]


def test_concurrent_handoffs_are_thread_local_and_reuse_pending_id(tmp_path):
    _, c = setup(tmp_path)
    barrier = threading.Barrier(2)
    original = c.add

    def add(*a, **kw):
        ok = original(*a, **kw)
        barrier.wait(timeout=5)
        return ok

    c.add = add
    with ThreadPoolExecutor(2) as pool:
        urls = [release("ia:a", "A").download_url, release("ia:b", "B").download_url]
        results = list(pool.map(lambda url: hand_off_with_id(c, url), urls))
    assert all(ok for ok, _ in results)
    assert len({job for _, job in results}) == 2
    assert {r["url"]: r["id"] for r in c._read()} == dict(zip(urls, [r[1] for r in results]))
    c.add = original
    assert hand_off_with_id(c, urls[0]) == results[0]
    assert not c.add("bad") and c.last_job_id == ""


@pytest.mark.parametrize("action", ["remove", "retry", "clear"])
def test_actions_dismiss_before_forgetting_and_survive_restart(tmp_path, action, monkeypatch):
    s, c = setup(tmp_path)
    q = grab(s)
    s.import_finished()
    calls = []
    monkeypatch.setattr(s, "request", lambda *a, **kw: calls.append((a, kw)) or {"ok": True})
    result = s.clear_queue("failed") if action == "clear" else s.queue_action(0, action, identity(q))
    assert result["ok"] and not s.queue
    restarted = HubDownloader(c._config, fetch=lambda *a: pytest.fail("dismissed fetch"))
    assert restarted.completed() == [] and restarted.failed_jobs() == []
    assert c._read()[0]["state"] == "dismissed"
    assert bool(calls) == (action == "retry")


def test_fetch_add_dismiss_overlap_and_active_conflict(tmp_path):
    s, c = setup(tmp_path)
    first = grab(s)
    s.grab(release("ia:b", "B"), "B", "psx")
    second = s.queue[-1]
    entered, proceed = threading.Event(), threading.Event()

    def fetch(*a):
        entered.set()
        assert proceed.wait(timeout=5)
        return {"ok": False, "error": "metadata HTTP 503"}

    c._fetch = fetch
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(c.completed)
        assert entered.wait(timeout=5)
        try:
            assert not s.queue_action(0, "remove", identity(first))["ok"]
            assert c.add(release("ia:c", "C").download_url, name="C")
            assert s.queue_action(1, "remove", identity(second))["ok"]
        finally:
            proceed.set()
        running.result(timeout=5)
    rows = HubDownloader(c._config)._read()
    assert [r["state"] for r in rows] == ["failed", "dismissed", "pending"]


def test_active_import_and_stale_action_refused(tmp_path):
    s, c = setup(tmp_path)
    q = grab(s)
    stale = identity(q)
    q.at = "changed"
    assert not s.queue_action(0, "remove", stale)["ok"]
    file = tmp_path / "game.bin"
    file.write_bytes(b"rom")
    c._fetch = lambda *a: {"ok": True, "files": [str(file)]}
    with c.import_session():
        assert c.completed()
        assert not s.queue_action(0, "remove", identity(q))["ok"]
    assert s.queue_action(0, "remove", identity(q))["ok"]
    assert file.read_bytes() == b"rom"


@pytest.mark.parametrize("action", ["remove", "retry", "clear"])
def test_dismiss_write_failure_retains_row(tmp_path, monkeypatch, action):
    s, c = setup(tmp_path)
    q = grab(s)
    s.import_finished()
    before = c._read()
    monkeypatch.setattr(c, "_write", lambda rows: (_ for _ in ()).throw(OSError("disk full")))
    result = s.clear_queue("failed") if action == "clear" else s.queue_action(0, action, identity(q))
    assert not result["ok"] and s.queue == [q] and c._read() == before
    assert "disk full" in str(result)


def test_handoff_write_failure_is_actionable_and_guarded(tmp_path, monkeypatch):
    s, c = setup(tmp_path)
    s.store.put_seerr_request(SeerrRequest("req", "psx", game="Crash 2"))
    monkeypatch.setattr(c, "_write", lambda rows: (_ for _ in ()).throw(OSError("disk full")))
    assert not s.grab(release(), "Crash 2", "psx", external_request_id="req")["ok"]
    q = s.queue[0]
    assert q.state == "failed" and not q.release_fault and not q.download_id
    assert "disk full" in q.detail and c.last_job_id == ""
    assert s.store.get_seerr_request("req").status == "failed"
    assert len(failures(s)) == 1
    assert s._reserve_automatic_grab(q.game, q.platform) is None
    assert not s.queue_action(0, "retry", identity(q))["ok"]


def test_fetch_result_write_failure_is_reported_retained_and_not_refetched(tmp_path, monkeypatch):
    s, c = setup(tmp_path)
    s.store.put_seerr_request(SeerrRequest("req", "psx", game="Crash 2"))
    q = grab(s, external_request_id="req")
    calls = []
    c._fetch = lambda *a: calls.append(a) or {"ok": False, "error": "metadata HTTP 503"}
    write = c._write
    monkeypatch.setattr(c, "_write", lambda rows: (_ for _ in ()).throw(OSError("disk full")))
    s.import_finished()
    assert q.state == "failed" and "503" in q.detail and "disk full" in q.detail
    assert s.store.get_seerr_request("req").error == q.detail
    s.import_finished()
    assert len(calls) == 1 and len(failures(s)) == 1
    monkeypatch.setattr(c, "_write", write)
    s.import_finished()
    assert len(calls) == 1 and len(failures(s)) == 1
    assert c._read()[0]["state"] == "failed" and q.detail == "metadata HTTP 503"


def test_mixed_clear_retains_each_refusal(tmp_path, monkeypatch):
    s, c = setup(tmp_path)
    grab(s)
    s.grab(release("ia:b", "B"), "B", "psx")
    s.grab(release("ia:c", "C"), "C", "psx")
    for _ in range(3):
        s.import_finished()
    s.queue[2].download_id = "missing"
    write = c._write
    def fail_one(rows):
        if rows[1]["state"] == "dismissed":
            raise OSError("disk full")
        write(rows)
    monkeypatch.setattr(c, "_write", fail_one)
    result = s.clear_queue("failed")
    assert result["removed"] == 1 and len(result["errors"]) == 2
    assert {q.game for q in s.queue} == {"B", "C"}
    assert "disk full" in str(result) and "repair" in str(result)


def test_search_again_preserves_link_and_replacement_updates(tmp_path, monkeypatch):
    s, c = setup(tmp_path)
    s.store.put_seerr_request(SeerrRequest("req", "psx", game="Crash 2"))
    q = grab(s, external_request_id="req")
    s.import_finished()
    assert s.store.get_seerr_request("req").status == "failed"
    monkeypatch.setattr(s, "request", lambda game, platform, external_request_id="":
                        s.grab(release(), game, platform, external_request_id=external_request_id))
    assert s.queue_action(0, "retry", identity(q))["ok"]
    assert s.queue[-1].external_request_id == "req"
    assert s.store.get_seerr_request("req").status == "downloading"
    file = tmp_path / "Crash Bandicoot 2.bin"
    file.write_bytes(b"rom")
    c._fetch = lambda *a: {"ok": True, "files": [str(file)]}
    from types import SimpleNamespace
    monkeypatch.setattr(s, "library_for", lambda _: ({}, SimpleNamespace(rescan=lambda _: None)))
    monkeypatch.setattr(s, "library_root", lambda _: tmp_path)
    monkeypatch.setattr(s, "library_layout", lambda _: "flat")
    monkeypatch.setattr(s, "platform_folders", lambda _: {})
    monkeypatch.setattr("romarr.app.import_rom", lambda *a, **kw:
                        [SimpleNamespace(ok=True, destination=file, verification="unchecked")])
    s.store.settings["reconcile_after_import"] = False
    s.import_finished()
    assert s.store.get_seerr_request("req").status == "available"


def test_rejected_handoff_needs_no_dismissal(tmp_path, monkeypatch):
    s, c = setup(tmp_path)
    monkeypatch.setattr(c, "add", lambda *a, **kw: False)
    assert not s.grab(release(), "Crash 2", "psx")["ok"]
    q = s.queue[0]
    assert q.hub_acceptance == "rejected" and not q.release_fault
    monkeypatch.setattr(c, "dismiss", lambda *a: pytest.fail("rejected job dismissal"))
    monkeypatch.setattr(s, "request", lambda *a, **kw: {"ok": True})
    assert s.queue_action(0, "retry", identity(q))["ok"]


def test_legacy_missing_client_stays_visible(tmp_path):
    s, c = setup(tmp_path)
    q = grab(s)
    q.download_client = q.download_protocol = q.download_id = ""
    s.import_finished()
    assert q.state == "failed" and "repair download_client" in q.detail
    assert not s.queue_action(0, "remove", identity(q))["ok"]
    assert c._read()[0]["state"] == "failed"


def test_atomic_replace_failure_keeps_ledger_and_reports_error(tmp_path, monkeypatch):
    s, c = setup(tmp_path)
    q = grab(s)
    before = c._ledger_path().read_bytes()
    def fail(*a):
        raise OSError("replace refused")
    monkeypatch.setattr("romarr.downloaders.os.replace", fail)
    assert not s.queue_action(0, "remove", identity(q))["ok"]
    assert c._ledger_path().read_bytes() == before and s.queue == [q]
    assert sorted(p.name for p in c._ledger_path().parent.iterdir()) == [c.LEDGER]


def test_unpersisted_success_is_not_imported_until_saved(tmp_path, monkeypatch):
    s, c = setup(tmp_path)
    file = tmp_path / "Crash 2.bin"
    file.write_bytes(b"rom")
    calls = []
    c._fetch = lambda *a: calls.append(a) or {"ok": True, "files": [str(file)]}
    q = grab(s)
    write = c._write
    monkeypatch.setattr(c, "_write", lambda rows: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(s, "library_for", lambda *a: pytest.fail("unpersisted import"))
    assert s.import_finished() == []
    assert "fetch completed" in q.detail and "disk full" in q.detail
    assert s.import_finished() == [] and len(calls) == 1
    monkeypatch.setattr(c, "_write", write)
    monkeypatch.setattr(s, "library_for", lambda *a: None)
    assert s.import_finished()
    assert len(calls) == 1 and c._read()[0]["state"] == "done"


def test_failed_history_not_duplicated_after_restart(tmp_path):
    s, c = setup(tmp_path)
    grab(s)
    s.import_finished()
    restarted, client = setup(tmp_path)
    restarted.import_finished()
    assert len(failures(restarted)) == 1
    assert restarted.queue[0].state == "failed"


def test_concurrent_grabs_record_each_handoffs_id(tmp_path):
    s, c = setup(tmp_path)
    barrier = threading.Barrier(2)
    add = c.add
    def interleave(*a, **kw):
        ok = add(*a, **kw)
        barrier.wait(timeout=5)
        return ok
    c.add = interleave
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda name: s.grab(release("ia:" + name, name), name, "psx"),
                                ["A", "B"]))
    assert all(r["ok"] for r in results)
    assert {q.release: q.download_id for q in s.queue} == {r["name"]: r["id"] for r in c._read()}


def test_explicit_id_must_belong_to_selected_release(tmp_path):
    s, c = setup(tmp_path)
    first = grab(s)
    s.grab(release("ia:b", "B"), "B", "psx")
    first.download_id = s.queue[-1].download_id
    before = c._read()
    assert not s.queue_action(0, "remove", identity(first))["ok"]
    assert c._read() == before
