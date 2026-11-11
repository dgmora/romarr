from pathlib import Path

import pytest

from romarr import hub
from romarr.disc_groups import group_results, fetch_group
from romarr.library import import_rom
from romarr.platforms import resolve


def row(n, title=None, parent='dreamcast.zip', **changes):
    name = title or f'Shenmue (USA) (Disc {n}).chd'
    return dict(source_id=f'{parent}/{name}', title=name, platform='dc',
                plugin='archive-org', url=f'https://archive.org/download/set/{parent}/{name}',
                size_bytes=100, **changes)


def download(member, dest):
    dest = Path(dest)
    dest.mkdir(parents=True)
    path = dest / member['title']
    path.write_bytes(b'disc data')
    return {'ok': True, 'files': [str(path)]}


def test_groups_sort_numbers_and_preserve_representative():
    rows = [row(3), row(1), row(10)]
    grouped = group_results(rows)
    assert len(grouped) == 1
    assert grouped[0]['title'] == rows[0]['title']
    assert grouped[0]['disc_set'] == rows
    assert grouped[0]['disc_title'] == 'Shenmue (USA).chd'


@pytest.mark.parametrize('other', [
    row(2, 'Shenmue (Europe) (Disc 2).chd'),
    row(2, parent='other.zip'), row(2, 'Shenmue (USA) (Disk 2).chd'),
    row(2, 'Shenmue (USA) (Disc 0).chd'), row(2, 'Shenmue (USA).chd'),
    row(2, 'Shenmue (USA) (Rev 1) (Disc 2).chd'),
])
def test_unmatched_results_stay_separate(other):
    rows = [row(1), other]
    assert group_results(rows) == rows


def test_ambiguous_disc_number_stays_separate():
    rows = [row(1), row(2), dict(row(2), source_id='alternate')]
    assert group_results(rows) == rows


def test_case_insensitive_and_duplicate_sources():
    rows = [row(1), row(2, 'Shenmue (USA) (dIsC 2).chd')]
    grouped = group_results(rows + [rows[0]])
    assert len(grouped) == 1
    assert len(grouped[0]['disc_set']) == 2


def test_group_roundtrip_fetch_and_atomic_import(tmp_path):
    grouped = group_results([row(3), row(1)])[0]
    grouped = hub.decode_result(hub.encode_result(grouped))
    result = fetch_group(grouped, tmp_path / 'download', download)
    assert result['ok']
    playlist = tmp_path / 'download/Shenmue (USA).m3u'
    assert playlist.read_text().splitlines() == [row(1)['title'], row(3)['title']]
    imported = import_rom(tmp_path / 'download', resolve('dc'), tmp_path / 'library')
    assert len(imported) == 1 and imported[0].ok
    assert imported[0].destination.name == 'Shenmue (USA)'
    assert {p.name for p in imported[0].destination.iterdir()} == {
        row(1)['title'], row(3)['title'], playlist.name}


def test_member_failure_never_completes_group(tmp_path):
    grouped = group_results([row(1), row(2)])[0]
    def fail(member, dest):
        if member == row(2):
            return {'ok': False, 'error': 'injected failure'}
        return download(member, dest)
    with pytest.raises(ValueError, match='injected failure'):
        fetch_group(grouped, tmp_path / 'download', fail)
    assert not list(tmp_path.rglob('*.m3u'))


def test_missing_identity_is_not_grouped():
    rows = [dict(row(n), url='https://archive.org/details/set') for n in (1, 2)]
    assert group_results(rows) == rows


def test_candidate_and_persisted_job(tmp_path, monkeypatch):
    from test_hub_acquisition import _service, _hub_client
    from romarr.downloaders import HubDownloader, HubConfig
    from romarr.selection import judge
    rows = [row(3), row(1)]
    client = _hub_client(tmp_path)
    service = _service(tmp_path, monkeypatch, rows, [client])
    monkeypatch.setattr(service.prowlarr, 'search', lambda *a: [])
    service.indexers = []
    releases = service._hub_releases('Shenmue', resolve('dc'))
    assert releases[0].size == 100
    candidate = service.candidates('Shenmue', 'dc')['items'][0]
    assert candidate['title'] == 'Shenmue (USA)'
    assert candidate['disc_numbers'] == (1, 3)
    assert candidate['size'] == 200
    assert candidate['reasons'] == judge(releases[0], 'Shenmue', resolve('dc'),
        profile=service.profile_for(resolve('dc')), blocklist=service.blocklist).why()
    assert service.grab_candidate(candidate['id'], 'dc')['ok']
    monkeypatch.setattr(hub, '_fetch_one', download)
    restarted = HubDownloader(HubConfig(save_path=str(tmp_path / 'hub')))
    completed = restarted.completed()
    assert len(completed) == 1
    assert Path(completed[0]['content_path']).is_dir()
    assert (Path(completed[0]['content_path']) / 'Shenmue (USA).m3u').exists()


def test_descriptor_collision_and_missing_tracks(tmp_path):
    def descriptor(member, dest):
        dest = Path(dest)
        dest.mkdir(parents=True)
        cue = dest / member['title']
        cue.write_text('FILE "track.bin" BINARY\n')
        track = dest / 'track.bin'
        track.write_bytes(b'track')
        return {'ok': True, 'files': [str(cue), str(track)]}
    grouped = group_results([row(n, f'Shenmue (USA) (Disc {n}).cue') for n in (1, 2)])[0]
    with pytest.raises(ValueError, match='conflicting disc filename'):
        fetch_group(grouped, tmp_path / 'collision', descriptor)
    def missing(member, dest):
        result = descriptor(member, dest)
        result['files'].pop()
        return result
    with pytest.raises(ValueError, match='missing tracks'):
        fetch_group(grouped, tmp_path / 'missing', missing)


def test_details_url_with_explicit_source_path():
    rows = [dict(row(n), url='https://archive.org/details/set',
                 extra={'path': f'dreamcast.zip/{row(n)["title"]}'}) for n in (1, 2)]
    assert len(group_results(rows)) == 1


def test_search_renderer_disc_labels_and_grab_request():
    import shutil
    import subprocess
    from romarr.ui import page
    node = shutil.which('node')
    if not node:
        pytest.skip('node required for search renderer')
    source = page().split('RENDER.search=', 1)[1].split('RENDER.missing=', 1)[0]
    script = r'''
const assert=require('node:assert/strict');
const nodes={};
const $=k=>nodes[k]??={innerHTML:'',value:''};
const PLATFORMS=[],enhancePlatformSelect=()=>{},esc=s=>String(s),toast=()=>{},refreshCounts=()=>{};
const button={dataset:{grab:'group-id',plat:'dc'}};
const document={querySelectorAll:()=>[button]};
let request;
const j=async(url,options)=>{
 if(options){request=JSON.parse(options.body);return {ok:true,release:'Shenmue'}};
 return {found:1,accepted:1,items:[{id:'group-id',title:'Shenmue (USA)',disc_numbers:[1,3],
  platform:'dc',size:200,seeders:0,indexer:'hub:archive-org',reasons:['first reason'],grabbable:true,accepted:true}]};
};
const render=RENDERER;
(async()=>{
 await render();
 $('#s-name').value='Shenmue';$('#s-plat').value='dc';
 await $('#s-go').onclick();
 assert.match($('#s-out').innerHTML,/Discs 1, 3/);
 assert.match($('#s-out').innerHTML,/Grab 2 discs/);
 assert.match($('#s-out').innerHTML,/first reason/);
 await button.onclick();
 assert.deepEqual(request,{id:'group-id',platform:'dc'});
})().catch(e=>{console.error(e);process.exitCode=1});
'''.replace('RENDERER', source.strip().rstrip(';'))
    subprocess.run([node, '-e', script], check=True, capture_output=True, text=True)


@pytest.mark.parametrize('changes', [
    {'plugin': 'other'}, {'platform': 'psx'}, {'platform': None},
    {'magnet': 'magnet:?xt=urn:btih:example'}, {'size_bytes': None},
])
def test_source_platform_and_unknown_size(tmp_path, monkeypatch, changes):
    other = dict(row(2), **changes)
    if 'size_bytes' not in changes:
        assert group_results([row(1), other]) == [row(1), other]
    else:
        from test_hub_acquisition import _service, _hub_client
        service = _service(tmp_path, monkeypatch, [row(1), other], [_hub_client(tmp_path)])
        assert service._hub_releases('Shenmue', resolve('dc'))[0].disc_size == 0


def test_failed_group_is_a_failed_hub_job(tmp_path, monkeypatch):
    from romarr.downloaders import HubDownloader, HubConfig
    import json
    grouped = group_results([row(1), row(2)])[0]
    client = HubDownloader(HubConfig(save_path=str(tmp_path)))
    assert client.add(hub.encode_result(grouped), name='Shenmue')
    def fail(member, dest):
        return {'ok': False, 'error': 'member unavailable'}
    monkeypatch.setattr(hub, '_fetch_one', fail)
    assert client.completed() == []
    ledger = json.loads((tmp_path / client.LEDGER).read_text())
    assert ledger[0]['state'] == 'failed'
    assert 'member unavailable' in ledger[0]['detail']
