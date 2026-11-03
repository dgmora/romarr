import pytest
from romarr.app import ROMarr
from romarr.library import import_rom
from romarr.platforms import resolve


def test_profile_is_opt_in(tmp_path):
    s=ROMarr({"ROMARR_DATA":str(tmp_path/"state.json")})
    assert not s.store.settings["standalone_export"]

def test_profile_normalizes_settings_and_cleans_only_import_scratch(tmp_path):
    library=tmp_path/"outgoing"; library.mkdir()
    scratch=library/"psx/.romarr-import-dead";scratch.mkdir(parents=True)
    (scratch/"game.bin").write_bytes(b"partial")
    published=library/"psx/Demo.bin"; published.write_bytes(b"complete")
    receiver=tmp_path/"receiver/.romarr-incoming"; receiver.mkdir(parents=True)
    (receiver/"retained.bin").write_bytes(b"retry")
    s=ROMarr({"ROMARR_DATA":str(tmp_path/"state.json"),"LIBRARY_KIND":"folder", "LIBRARY_PATH":str(library),"ROMARR_STANDALONE_EXPORT":"1"})
    assert s.store.settings["acquisition_only"] and s.store.settings["standalone_export"]
    assert s.store.settings["library_layout"]=="flat"
    assert not scratch.exists() and published.read_bytes()==b"complete"
    assert (receiver/"retained.bin").exists()

@pytest.mark.parametrize("options", [{"layout":"nested"},{"overwrite":True}])
def test_export_profile_refuses_incompatible_imports(tmp_path, options):
    source=tmp_path/"Demo.sfc";source.write_bytes(b"ROM")
    result=import_rom(source,resolve("snes"),tmp_path/"outgoing",export_only=True,**options)
    assert not result[0].ok
