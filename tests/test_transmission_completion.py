from unittest.mock import Mock
import pytest
from romarr.downloaders import Transmission, TransmissionConfig, build_client

HASH = "a" * 40

def client():
    return Transmission(TransmissionConfig(base_url="http://localhost:9091", category="romarr", save_path="/downloads/romarr"))

def torrent(**changes):
    return {"hashString": HASH, "name": "Demo.sfc", "labels": ["romarr"], "downloadDir": "/downloads/romarr", "leftUntilDone": 0, "percentDone": 1, "totalSize": 100, **changes}

def test_configured_directory_and_identity():
    c = client()
    c._call = Mock(return_value={"result": "success", "arguments": {"torrent-added": {"hashString": HASH}}})
    assert c.add("magnet:demo") and c.last_job_id == HASH
    assert c._call.call_args.args[1]["download-dir"] == "/downloads/romarr"
    assert build_client({"type":"transmission", "host":"localhost", "port":9091, "save_path":"/downloads/romarr"})._config.save_path == "/downloads/romarr"

@pytest.mark.parametrize("changes", [{"labels":[]}, {"downloadDir":"/downloads/tv"}, {"hashString":"b"*40}])
def test_foreign_duplicates_are_rejected_without_modification(changes):
    c = client()
    c._call = Mock(side_effect=[{"result":"success", "arguments":{"torrent-duplicate":{"hashString":HASH}}}, {"result":"success", "arguments":{"torrents":[torrent(**changes)]}}])
    assert not c.add("magnet:demo")
    assert c.last_job_id == ""
    assert [call.args[0] for call in c._call.call_args_list] == ["torrent-add", "torrent-get"]

@pytest.mark.parametrize("changes", [{"leftUntilDone":1}, {"percentDone":0.9}, {"totalSize":0}, {"labels":[]}, {"downloadDir":"/downloads/tv"}])
def test_polling_filters_incomplete_and_foreign_downloads(changes):
    c = client()
    c._call = Mock(return_value={"result":"success", "arguments":{"torrents":[torrent(**changes), torrent()]}})
    rows = c.completed()
    assert len(rows) == 1
    assert rows[0]["id"] == HASH
    assert rows[0]["content_path"] == "/downloads/romarr/Demo.sfc"

def test_failed_submission_clears_previous_identity():
    c = client(); c.last_job_id = HASH
    c._call = Mock(return_value={"result":"error"})
    assert not c.add("magnet:demo") and not c.last_job_id

def test_failed_polling_is_not_silently_reported_as_empty():
    c = client(); c._call = Mock(return_value={"result":"error"})
    with pytest.raises(RuntimeError): c.completed()


def test_concurrent_submissions_keep_their_own_identity():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    c = client()
    barrier = Barrier(2)
    def call(method, arguments):
        return {"result": "success", "arguments": {"torrent-added": {"hashString": arguments["filename"]}}}
    c._call = call
    def submit(identity):
        assert c.add(identity)
        barrier.wait()
        return c.last_job_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(submit, ["a" * 40, "b" * 40])) == ["a" * 40, "b" * 40]
