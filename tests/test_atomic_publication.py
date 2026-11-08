from pathlib import Path
from unittest.mock import patch
import pytest
from romarr.library import _PathSource, import_rom
from romarr.platforms import resolve


def disc(tmp_path):
    source = tmp_path/"download"; source.mkdir()
    (source/"Demo.cue").write_text('FILE "Demo.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    (source/"Demo.bin").write_bytes(b"track"*128)
    return source

@pytest.mark.parametrize("layout,translation,folder", [("flat",False,"psx"), ("nested",False,"psx/roms"), ("flat",True,"psx/Translations"), ("nested",True,"psx/roms/Translations")])
@pytest.mark.parametrize("prefer_hardlinks", [False, True])
def test_disc_is_invisible_until_complete(tmp_path, layout, translation, folder, prefer_hardlinks):
    source = disc(tmp_path); library = tmp_path/"library"
    destination = library/folder/"Demo"
    original = _PathSource.copy; observed=[]
    def copy(self, member, target):
        observed.append(destination.exists())
        return original(self, member, target)
    rename = Path.rename
    def publish(staged, target):
        assert not destination.exists()
        assert {p.name for p in staged.iterdir()} == {"Demo.cue", "Demo.bin"}
        return rename(staged, target)
    with patch.object(_PathSource,"copy",copy), patch.object(Path, "rename", publish):
        result = import_rom(source,resolve("psx"),library,layout=layout,translation=translation,
                            prefer_hardlinks=prefer_hardlinks)
    assert result[0].ok and observed and not any(observed)
    assert {p.name for p in destination.iterdir()} == {"Demo.cue","Demo.bin"}
    assert not list(library.rglob(".romarr-import-*"))

def test_failed_copy_publishes_nothing_and_cleans_scratch(tmp_path):
    source=disc(tmp_path); library=tmp_path/"library"
    original=_PathSource.copy; count=0
    def copy(self, member, target):
        nonlocal count
        count+=1
        if count==2: raise OSError("disk full")
        return original(self,member,target)
    with patch.object(_PathSource,"copy",copy):
        result, = import_rom(source,resolve("psx"),library)
    assert not result.ok and "disk full" in result.reason
    assert not (library/"psx/Demo").exists()
    assert not list(library.rglob(".romarr-import-*"))

def test_empty_directory_can_be_reused_but_existing_set_is_preserved(tmp_path):
    source=disc(tmp_path); library=tmp_path/"library"; target=library/"psx/Demo"
    target.mkdir(parents=True)
    assert import_rom(source,resolve("psx"),library)[0].ok
    (target/"Demo.bin").write_bytes(b"original")
    assert not import_rom(source,resolve("psx"),library,overwrite=True)[0].ok
    assert (target/"Demo.bin").read_bytes()==b"original"

def test_custom_platform_folder(tmp_path):
    source=disc(tmp_path); library=tmp_path/"library"
    result=import_rom(source,resolve("psx"),library,platform_folders={"psx":"PlayStation"})
    assert result[0].ok and (library/"PlayStation/Demo/Demo.bin").exists()
