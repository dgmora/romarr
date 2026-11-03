from unittest.mock import Mock
from romarr.app import ROMarr
from romarr.store import Store, QueueItem


def test_settings_api_accepts_and_persists_acquisition_mode(tmp_path):
    state=tmp_path/"state.json"; store=Store(state)
    store.update_settings({"acquisition_only":True,"reconcile_after_import":False})
    loaded=Store(state)
    assert loaded.settings["acquisition_only"] is True
    assert loaded.settings["reconcile_after_import"] is False

def test_default_remains_full_library_management(tmp_path):
    assert Store(tmp_path/"state.json").settings["acquisition_only"] is False

def test_delivery_removal_and_restart_do_not_reimport_or_requeue(tmp_path):
    state=tmp_path/"state.json"; library=tmp_path/"outgoing"
    source=tmp_path/"Demo.sfc"; source.write_bytes(b"ROM"*512)
    env={"ROMARR_DATA":str(state),"LIBRARY_KIND":"folder","LIBRARY_PATH":str(library)}
    s=ROMarr(env)
    s.store.update_settings({"acquisition_only":True})
    s.store.want("Demo","snes")
    s.store.enqueue(QueueItem("Demo","snes","Demo.sfc",1,"grabbed",release_id="btih:"+"a"*40))
    class Client:
        configured=True
        def completed(self):
            return [{"name":"Demo.sfc","hash":"a"*40,"content_path":str(source)}]
    s.clients=[Client()]
    s.game_libraries[0][1].rescan=Mock(side_effect=AssertionError("spool must not trigger rescan"))
    s.reconcile_platform=Mock(side_effect=AssertionError("spool must not reconcile"))
    result=s.import_finished(retry_failed=False)
    assert result[0]["ok"]
    assert s.queue[0].state=="imported" and s.store.missing()==[]
    # A separate receiver removes only the imported spool copy, never seeding data.
    (library/"snes/Demo.sfc").unlink()
    restarted=ROMarr(env); restarted.clients=[Client()]
    assert restarted.import_finished(retry_failed=False)==[]
    assert restarted.queue[0].state=="imported"
    assert restarted.store.missing()==[]
    assert source.exists() and not (library/"snes/Demo.sfc").exists()
    assert restarted.reconcile_platform("snes")["skipped"]
