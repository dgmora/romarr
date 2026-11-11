from unittest.mock import Mock
import pytest
from romarr.downloaders import Transmission, TransmissionConfig, build_client

HASH = "a" * 40

def client():
    c = Transmission(TransmissionConfig(base_url="http://localhost:9091", category="romarr", save_path="/downloads/romarr"))
    c._rpc_version = 17
    return c

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


@pytest.mark.parametrize("version", [16, 17])
def test_concurrent_submissions_keep_their_own_identity(version):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    c = client()
    c._rpc_version = None
    barrier = Barrier(2)
    def call(method, arguments):
        if method == 'session-get':
            return success(**{'rpc-version': version})
        if method == 'torrent-get':
            return success(torrents=[torrent(hashString=arguments['ids'][0])])
        if method == 'torrent-set':
            return success()
        return success(**{'torrent-added': {'hashString': arguments['filename']}})
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


def success(**arguments):
    return {'result': 'success', 'arguments': arguments}


@pytest.mark.parametrize('kind', ['transmission', 'vuze', 'biglybt'])
@pytest.mark.parametrize('version', [16, 17])
def test_version_aware_labels(kind, version):
    c = build_client({'type': kind, 'host': 'localhost', 'save_path': '/downloads/romarr'})
    replies = [success(**{'rpc-version': version}), success(**{'torrent-added': {'hashString': HASH}})]
    if version == 16:
        replies.extend([success(), success(torrents=[torrent()])])
    c._call = Mock(side_effect=replies)
    assert c.add('magnet:demo', save_path='/downloads/romarr') and c.last_job_id == HASH
    calls = c._call.call_args_list
    assert calls[0].args == ('session-get', {})
    args = calls[1].args[1]
    assert args['download-dir'] == '/downloads/romarr'
    if version == 17:
        assert args['labels'] == ['romarr']
        assert [call.args[0] for call in calls] == ['session-get', 'torrent-add']
    else:
        assert 'labels' not in args
        assert calls[2].args == ('torrent-set', {'ids': [HASH], 'labels': ['romarr']})
        assert [call.args[0] for call in calls] == ['session-get', 'torrent-add', 'torrent-set', 'torrent-get']


@pytest.mark.parametrize('version', [16, 17])
def test_connection_check_caches_discovery_for_submission(version):
    c = client()
    c._rpc_version = None
    def call(method, arguments):
        if method == 'session-get':
            return success(**{'rpc-version': version})
        if method == 'torrent-add':
            return success(**{'torrent-added': {'hashString': HASH}})
        return success(torrents=[torrent()])
    c._call = Mock(side_effect=call)
    assert c.reachable()
    assert c.add('magnet:demo')
    assert c.add_torrent_file(b'torrent bytes')
    assert [call.args[0] for call in c._call.call_args_list].count('session-get') == 1
    import base64
    adds = [call.args[1] for call in c._call.call_args_list if call.args[0] == 'torrent-add']
    assert base64.b64decode(adds[1]['metainfo']) == b'torrent bytes'


def test_connection_check_still_probes_after_cached_success():
    c = client()
    c._call = Mock(return_value={'result': 'connection failed'})
    assert not c.reachable()
    c._call.assert_called_once_with('session-get', {})


@pytest.mark.parametrize('reply', [
    {}, {'result': 'error'}, success(), success(**{'rpc-version': None}),
    success(**{'rpc-version': '17'}), success(**{'rpc-version': True}),
    success(**{'rpc-version': 0}), success(**{'rpc-version': 15}),
    RuntimeError('disconnected'),
])
def test_failed_or_unsupported_discovery_refuses_submission(reply, caplog):
    c = client()
    c._rpc_version = None
    c.last_job_id = HASH
    c._call = Mock(side_effect=[reply])
    assert not c.add('magnet:demo')
    assert c.last_job_id == ''
    c._call.assert_called_once_with('session-get', {})
    assert 'add failed' in caplog.text


def test_failed_discovery_is_retried():
    c = client()
    c._rpc_version = None
    c._call = Mock(side_effect=[{'result': 'error'}, success(**{'rpc-version': 17}),
                               success(**{'torrent-added': {'hashString': HASH}})])
    assert not c.add('magnet:demo')
    assert c.add('magnet:demo')
    assert [call.args[0] for call in c._call.call_args_list] == ['session-get', 'session-get', 'torrent-add']


@pytest.mark.parametrize('version', [16, 17])
@pytest.mark.parametrize('changes,accepted', [({}, True), ({'labels': []}, False),
    ({'downloadDir': '/other'}, False), ({'hashString': 'b' * 40}, False)])
def test_version_aware_duplicates_are_only_inspected(version, changes, accepted):
    c = client()
    c._rpc_version = version
    c._call = Mock(side_effect=[success(**{'torrent-duplicate': {'hashString': HASH}}),
                               success(torrents=[torrent(**changes)])])
    assert c.add('magnet:demo') is accepted
    assert c.last_job_id == (HASH if accepted else '')
    assert [call.args[0] for call in c._call.call_args_list] == ['torrent-add', 'torrent-get']


@pytest.mark.parametrize('reply', [{'result': 'error'}, RuntimeError('disconnected')])
def test_post_add_labelling_failure_leaves_torrent_intact(reply, caplog):
    c = client()
    c._rpc_version = 16
    c._call = Mock(side_effect=[success(**{'torrent-added': {'hashString': HASH}}), reply])
    assert not c.add('magnet:demo')
    assert c.last_job_id == ''
    assert [call.args[0] for call in c._call.call_args_list] == ['torrent-add', 'torrent-set']
    assert 'torrent left intact' in caplog.text


@pytest.mark.parametrize('reply', [
    {'result': 'error'}, success(torrents=[]), success(torrents=[torrent(), torrent()]),
    success(torrents=[torrent(labels=[])]), success(torrents=[torrent(downloadDir='/other')]),
    success(torrents=[torrent(hashString='b' * 40)]), RuntimeError('disconnected'),
])
def test_post_add_verification_failure_leaves_torrent_intact(reply, caplog):
    c = client()
    c._rpc_version = 16
    c._call = Mock(side_effect=[success(**{'torrent-added': {'hashString': HASH}}), success(), reply])
    assert not c.add('magnet:demo')
    assert c.last_job_id == ''
    assert [call.args[0] for call in c._call.call_args_list] == ['torrent-add', 'torrent-set', 'torrent-get']
    assert 'torrent left intact' in caplog.text


def test_unlabelled_submission_does_not_require_label_capabilities():
    c = Transmission(TransmissionConfig('http://localhost', category=''))
    c._call = Mock(return_value=success(**{'torrent-added': {'hashString': HASH}}))
    assert c.add('magnet:demo')
    c._call.assert_called_once_with('torrent-add', {'filename': 'magnet:demo'})


@pytest.mark.parametrize('status', [401, 409, 500])
def test_http_failure_cannot_confirm_capabilities(status):
    from tests.test_more_clients import FakeResponse, FakeSession

    session = FakeSession([FakeResponse(status, success(**{'rpc-version': 17})),
                           FakeResponse(status, success(**{'rpc-version': 17}))])
    c = Transmission(TransmissionConfig('http://localhost'), session)
    assert not c.add('magnet:demo')
    assert c.last_job_id == ''
    import json
    assert all(json.loads(call['data'])['method'] == 'session-get' for call in session.calls)
