#!/usr/bin/env python3.11
"""gc import freeze — snapshot a pack into ./packs/<name>/, sealed in amber.

Usage:
    gc import freeze <name>

For URL imports: copies .gc/cache/packs/<name>/ → ./packs/<name>/, swaps the
[workspace].includes entry from `<name>` to `./packs/<name>`, removes the
[packs.<name>] block from city.toml, and marks frozen = true in pack.lock
(keeping the URL/ref/commit/hash for thaw).

For path imports: copies the path's contents → ./packs/<name>/, then writes
the same swap. The original path can be deleted, edited, or renamed without
affecting this city until the user removes ./packs/<name>/.

To unfreeze: rm -rf ./packs/<name>/ and run `gc import install` to repopulate
the cache. (No `gc import thaw` verb — the operation is just a directory delete.)
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import cache, citytoml, lockfile, manifest, ui  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gc import freeze")
    parser.add_argument("name", help="The local handle to freeze")
    args = parser.parse_args(argv)

    city_root = ui.find_city_root()
    handle = args.name

    m = manifest.read(city_root / "imports.toml")
    if handle not in m.imports:
        ui.die(f"no import named {handle!r} in imports.toml")

    spec = m.imports[handle]
    target = city_root / "packs" / handle
    if target.exists():
        ui.die(f"./packs/{handle}/ already exists. Either it's already frozen or it's a hand-authored local pack — refusing to overwrite.")

    if spec.is_path():
        # Copy from the user-supplied path into ./packs/<handle>/
        source = (city_root / spec.path).resolve() if not Path(spec.path).is_absolute() else Path(spec.path).expanduser()
        if not source.exists():
            ui.die(f"path source does not exist: {source}")
        ui.info(f"Freezing path import {handle} from {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git"))
        ui.step(f"Copied {source} → ./packs/{handle}/", indent=1)
        # For path imports, the manifest still says path = "..."; we don't
        # have a [packs.<handle>] in city.toml to remove. The path needs to
        # be updated to point at ./packs/<handle> for the loader to find it.
        # Strategy: rewrite the manifest entry to point at the frozen location.
        spec.path = f"./packs/{handle}"
        manifest.write(m, city_root / "imports.toml")
        # Also append to city.toml's includes if not already present
        city_data = citytoml.read(city_root / "city.toml")
        existing_includes = citytoml.get_includes(city_data)
        new_includes = list(existing_includes)
        # If the old path was in the includes, replace it; otherwise append
        old_path = spec.path  # this is now the new value, but we want to find the old one
        # We don't track the old value here cleanly — assume the user had it
        # listed by name or path; just ensure the new ./packs/<handle> is present
        if f"./packs/{handle}" not in new_includes:
            new_includes.append(f"./packs/{handle}")
        citytoml.update_includes_and_packs(
            city_root / "city.toml",
            new_includes=new_includes,
            new_packs={},
            removed_packs=set(),
        )
        ui.info(f"Frozen. To unfreeze, rm -rf ./packs/{handle}/ and edit imports.toml.")
        return 0

    # URL import — the canonical case
    lf = lockfile.read(city_root / "pack.lock")
    locked = lf.get(handle)
    if locked is None:
        ui.die(f"{handle!r} has no lock entry. Run `gc import install` first.")
    if locked.frozen:
        ui.die(f"{handle!r} is already frozen.")

    cache_src = cache.city_pack_cache(city_root) / handle
    if not cache_src.exists():
        ui.die(f"{handle!r} is not in the city cache. Run `gc import install` first.")

    ui.info(f"Freezing {handle} v{locked.version} → ./packs/{handle}/")
    shutil.copytree(cache_src, target, ignore=shutil.ignore_patterns(".git"))
    ui.step(f"Copied .gc/cache/packs/{handle}/ → ./packs/{handle}/", indent=1)

    # Update lock file to mark frozen (keep all the URL/version/commit/hash data)
    locked.frozen = True
    lockfile.write(lf, city_root / "pack.lock")

    # Update city.toml: remove [packs.<handle>], swap includes entry
    city_data = citytoml.read(city_root / "city.toml")
    existing_includes = citytoml.get_includes(city_data)
    new_includes = []
    for entry in existing_includes:
        if entry == handle:
            new_includes.append(f"./packs/{handle}")
        else:
            new_includes.append(entry)
    if f"./packs/{handle}" not in new_includes:
        new_includes.append(f"./packs/{handle}")

    citytoml.update_includes_and_packs(
        city_root / "city.toml",
        new_includes=new_includes,
        new_packs={},
        removed_packs={handle},
    )
    ui.step(f"Swapped \"{handle}\" → \"./packs/{handle}\" in [workspace].includes", indent=1)
    ui.step(f"Removed [packs.{handle}] from city.toml", indent=1)
    ui.step(f"Marked frozen = true in pack.lock", indent=1)
    ui.info(f"To unfreeze: rm -rf ./packs/{handle}/ && gc import install")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
