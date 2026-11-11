from unittest.mock import Mock
import pytest
from romarr.downloaders import Transmission, TransmissionConfig, build_client

HASH = "a" * 40

def client():
    return Transmission(TransmissionConfig(base_url="http://localhost:9091", category="romarr", save_path="/downloads/romarr"))

def torrent(**changes):
    return {"hashString": HASH, "name": "Demo.sfc", "labels": ["romarr"], "downloadDir": "/downloads/romarr", "leftUntilDone": 0, "percentDone": 1, "totalSize": 100, "metadataPercentComplete": 1, "files": [{"name": "Demo.sfc"}], **changes}

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


def test_transmission_file_stats_are_normalized_and_selections_are_explicit():
    c = client()
    c._call = Mock(return_value={"result": "success", "arguments": {"torrents": [{
        "hashString": HASH,
        "files": [{"name": "Set/A.bin", "length": 100}, {"name": "Set/B.bin", "length": 200}],
        "fileStats": [{"bytesCompleted": 100, "wanted": True, "priority": -1},
                      {"bytesCompleted": 50, "wanted": False, "priority": 1}]}]}})
    assert c.torrent_files(HASH) == [
        {"index": 0, "name": "Set/A.bin", "size": 100, "progress": 1.0, "priority": 2, "native_priority": -1},
        {"index": 1, "name": "Set/B.bin", "size": 200, "progress": 0.25, "priority": 0, "native_priority": 1}]
    c._call.return_value = {"result": "success"}
    assert c.set_file_priorities(HASH, {0: 2, 1: 0})
    assert c._call.call_args.args == ("torrent-set", {"ids": [HASH], "files-unwanted": [1],
                                                       "priority-low": [0], "files-wanted": [0]})


def test_transmission_rejects_unrepresentable_priority():
    c = client()
    with pytest.raises(ValueError, match="cannot represent"):
        c.set_file_priorities(HASH, {0: 7})


def test_transmission_waits_for_stop_before_selection(monkeypatch):
    c = client()
    c._call = Mock(side_effect=[{"result": "success"},
        {"result": "success", "arguments": {"torrents": [{"hashString": HASH, "status": 4}]}},
        {"result": "success", "arguments": {"torrents": [{"hashString": HASH, "status": 0}]}}])
    monkeypatch.setattr("romarr.downloaders.time.sleep", lambda _: None)
    assert c.pause_torrent(HASH)
    assert [call.args[0] for call in c._call.call_args_list] == ["torrent-stop", "torrent-get", "torrent-get"]


def test_invalid_saved_native_priority_does_not_send_request():
    c = client()
    c._call = Mock()
    with pytest.raises(ValueError, match="invalid saved"):
        c.set_file_priorities(HASH, {0: 1}, native_priorities={0: 9})
    c._call.assert_not_called()


@pytest.mark.parametrize('files,relative', [
    ([{'name': 'Actual.sfc'}], 'Actual.sfc'),
    ([{'name': 'Set/A.cue'}, {'name': 'Set/A.bin'}], 'Set'),
    ([{'name': r'Set\A.cue'}, {'name': r'Set\A.bin'}], 'Set'),
])
def test_completion_uses_actual_files(files, relative):
    c = client()
    c._call = Mock(return_value={'result': 'success', 'arguments': {'torrents': [
        torrent(name='Display title', files=files)]}})
    row, = c.completed()
    assert row['content_path'] == '/downloads/romarr/' + relative
    assert row['name'] == 'Display title'


@pytest.mark.parametrize('files', [
    [], [{'name': ''}], [{'name': '../Game.sfc'}], [{'name': '/Game.sfc'}],
    [{'name': r'C:\Game.sfc'}], [{'name': 'Set/./Game.sfc'}],
    [{'name': 'Set//Game.sfc'}], [{'name': 'Set/Game\x00.sfc'}],
    [{'name': 'A.cue'}, {'name': 'A.bin'}],
    [{'name': 'A/Game.sfc'}, {'name': 'B/Game.sfc'}],
])
def test_completion_rejects_unsafe_payload_paths(files):
    c = client()
    c._call = Mock(return_value={'result': 'success', 'arguments': {'torrents': [torrent(files=files)]}})
    assert c.completed() == []


@pytest.mark.parametrize('changes', [
    {'metadataPercentComplete': 0}, {'metadataPercentComplete': None}, {'hashString': ''},
])
def test_completion_requires_metadata_and_identity(changes):
    c = client()
    c._call = Mock(return_value={'result': 'success', 'arguments': {'torrents': [torrent(**changes)]}})
    assert c.completed() == []
