from threading import Barrier
from types import SimpleNamespace

from romarr.app import ROMarr
from romarr.platforms import resolve
from romarr.selection import Release


def release(title, url):
    return Release(title=title, download_url=url, size=1, seeders=1,
                   categories=(1000,), protocol="torrent", indexer="test")


def test_three_searches_overlap_and_preserve_duplicate_precedence(tmp_path):
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "state.json")})
    barrier = Barrier(3, timeout=5)
    first = release("Game", "same")
    duplicate = release("Game", "same")
    qualified = release("Qualified", "qualified")
    hub = release("Hub", "hub")

    def search(term):
        barrier.wait()
        return [first] if term == "Game" else [duplicate, qualified]

    def hub_search(*args):
        barrier.wait()
        return [hub]

    service.prowlarr = SimpleNamespace(search=search)
    service.indexers = []
    service._hub_releases = hub_search
    results = service._search_releases("Game", resolve("psx"))
    assert results == [first, qualified, hub]
    assert results[0] is first


def test_failed_query_and_hub_leave_successful_results(tmp_path):
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "state.json")})
    found = release("Game", "game")

    def search(term):
        if term == "Game":
            raise TimeoutError("source timeout")
        return [found]

    def hub_search(*args):
        raise RuntimeError("hub failure")

    service.prowlarr = SimpleNamespace(search=search)
    service.indexers = []
    service._hub_releases = hub_search
    assert service._search_releases("Game", resolve("psx")) == [found]


def test_worker_clients_isolate_sessions_and_mutable_state(tmp_path, monkeypatch):
    from romarr import app

    service = ROMarr({"ROMARR_DATA": str(tmp_path / "state.json")})
    barrier = Barrier(2, timeout=5)
    sessions = []

    class Session:
        closed = False

        def __enter__(self):
            sessions.append(self)
            return self

        def __exit__(self, *args):
            self.closed = True

    class Source:
        _owns_session = True
        _session = object()
        _privacy = None

        def search(self, term):
            assert isinstance(self._session, Session)
            self._privacy = {1: True}
            barrier.wait()
            if term == "Game":
                raise TimeoutError("timeout")
            return [release("Game", "game")]

    source = Source()
    service.prowlarr = source
    service.indexers = []
    service._hub_releases = lambda *args: []
    monkeypatch.setattr(app.requests, "Session", Session)
    assert len(service._search_releases("Game", resolve("psx"))) == 1
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert all(session.closed for session in sessions)
    assert source._privacy is None
    assert not isinstance(source._session, Session)


def test_failed_direct_indexer_does_not_hide_other_sources(tmp_path):
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "state.json")})
    found = release("Game", "game")
    direct = release("Direct", "direct")

    def broken(term):
        raise RuntimeError("direct source failure")

    service.prowlarr = SimpleNamespace(search=lambda term: [found])
    service.indexers = [SimpleNamespace(name="broken", search=broken),
                        SimpleNamespace(name="working", search=lambda term: [direct])]
    service._hub_releases = lambda *args: []
    assert service._search_releases("Game", resolve("psx")) == [found, direct]
