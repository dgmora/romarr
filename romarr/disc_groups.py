"""Numbered Archive.org results acquired as one explicit disc selection."""
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, unquote

from .platforms import resolve
from .selection import pick_all_rom_sets, _cue_and_gdi_names

DISC = re.compile(r"\(disc ([0-9]+)\)", re.I)


def identity(row):
    title = row.get("title", "")
    matches = list(DISC.finditer(title))
    platform = resolve(row.get("platform") or "")
    if (row.get("plugin") != "archive-org" or row.get("magnet") or len(matches) != 1
            or not platform or not platform.is_disc):
        return None
    number = int(matches[0][1])
    if number < 1:
        return None
    url = urlsplit(row.get("url") or "")
    if url.hostname != "archive.org":
        return None
    if url.path.startswith("/download/"):
        parent = str(PurePosixPath(unquote(url.path)).parent)
    elif url.path.startswith("/details/"):
        extra = row.get("extra") or {}
        path = PurePosixPath(extra.get("path") or "")
        if len(path.parts) < 2 or path.is_absolute() or ".." in path.parts:
            return None
        parent = url.path.rstrip("/") + "/" + str(path.parent)
    else:
        return None
    base = re.sub(r"\s+", " ", DISC.sub("", title)).strip()
    base = re.sub(r"\s+(\.[^ .]+)$", r"\1", base)
    if not base:
        return None
    suffix = PurePosixPath(unquote(url.path)).suffix.lower()
    return (platform.slug, parent, base.casefold(), suffix), number, base


def group_results(rows):
    groups = {}
    for row in rows:
        found = identity(row)
        if found:
            groups.setdefault(found[0], []).append(row)
    replacements, consumed = {}, set()
    for members in groups.values():
        unique = {}
        for member in members:
            unique.setdefault(member["source_id"], member)
        members = list(unique.values())
        numbers = [identity(r)[1] for r in members]
        if len(members) < 2 or len(set(numbers)) != len(numbers):
            continue
        first = members[0]
        replacements[id(first)] = dict(first, disc_set=members,
                                       disc_title=identity(first)[2])
        consumed.update(identity(r)[0] for r in members)
    out, emitted = [], set()
    for row in rows:
        if id(row) in replacements and id(row) not in emitted:
            out.append(replacements[id(row)])
            emitted.add(id(row))
        elif not identity(row) or identity(row)[0] not in consumed:
            out.append(row)
    return out


def fetch_group(row, destination, fetch):
    members = row.get("disc_set")
    if not isinstance(members, list) or len(members) < 2:
        raise ValueError("invalid disc selection")
    identities = [identity(member) for member in members]
    if (not all(identities) or len({i[0] for i in identities}) != 1
            or len({i[1] for i in identities}) != len(members)):
        raise ValueError("disc selection no longer matches one game")
    base = identities[0][2]
    if base != row.get("disc_title") or Path(base).name != base or "\\" in base:
        raise ValueError("invalid disc-set name")
    destination = Path(destination)
    platform = resolve(members[0]["platform"])
    files, playlist, used = [], [], set()
    for member in sorted(members, key=lambda r: identity(r)[1]):
        if "disc_set" in member:
            raise ValueError("nested disc selections are invalid")
        isolated = destination / f".disc-{identity(member)[1]}"
        outcome = fetch(dict(member, disc_exact=True), isolated)
        if not outcome.get("ok") or not outcome.get("files"):
            raise ValueError(outcome.get("error") or "disc fetch returned no files")
        paths = [Path(p) for p in outcome["files"]]
        if any(not p.is_file() or p.parent.resolve() != isolated.resolve() for p in paths):
            raise ValueError("disc fetch returned a file outside its directory")
        by_name = {p.name: p for p in paths}
        sets = pick_all_rom_sets(list(by_name), platform,
                                 read=lambda name: by_name[name].read_bytes())
        if len(sets) != 1 or Path(sets[0].primary).suffix.lower() == ".m3u":
            raise ValueError("each selected result must contain exactly one disc")
        primary_match = DISC.search(sets[0].primary)
        if not primary_match or int(primary_match[1]) != identity(member)[1]:
            raise ValueError("downloaded disc does not match the selected disc number")
        primary = sets[0].primary
        actual_base = re.sub(r"\s+", " ", DISC.sub("", Path(primary).stem)).strip()
        expected_base = Path(base).stem if Path(base).suffix.lower() in platform.extensions else base
        if actual_base.casefold() != expected_base.casefold():
            raise ValueError("downloaded disc does not match the selected game")
        if Path(primary).suffix.lower() in {".cue", ".gdi"}:
            references = _cue_and_gdi_names(by_name[primary].read_text(encoding="utf-8"))
            if not references or any(ref not in by_name for ref in references):
                raise ValueError("disc descriptor has missing tracks")
        for name in sets[0].members:
            if name.casefold() in used:
                raise ValueError(f"conflicting disc filename: {name}")
            used.add(name.casefold())
            target = destination / name
            by_name[name].replace(target)
            files.append(str(target))
        playlist.append(sets[0].primary)
    name = Path(base).stem if Path(base).suffix.lower() in platform.extensions else base
    target = destination / (name + ".m3u")
    if target.name.casefold() in used:
        raise ValueError("playlist conflicts with a downloaded file")
    target.write_text("\n".join(playlist) + "\n", encoding="utf-8")
    files.append(str(target))
    return {"ok": True, "error": "", "files": files}
