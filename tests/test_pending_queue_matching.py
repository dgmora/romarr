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
