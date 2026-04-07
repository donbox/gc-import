#!/usr/bin/env python3.11
"""gc import remove — drop a pack from the city's imports.

Usage:
    gc import remove <name>

- Removes [imports.<name>] from imports.toml.
- Garbage-collects transitive deps that are no longer needed.
- Removes the corresponding [packs.X] blocks from city.toml and entries
  from [workspace].includes.
- Prunes the city pack cache for everything that was removed.
- Errors with a thaw hint if the pack is currently frozen.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import cache, citytoml, lockfile, manifest, ui  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gc import remove")
    parser.add_argument("name", help="The local handle of the pack to remove")
    args = parser.parse_args(argv)

    city_root = ui.find_city_root()
    handle = args.name

    manifest_path = city_root / "imports.toml"
    m = manifest.read(manifest_path)

    if handle not in m.imports:
        ui.die(f"no import named {handle!r} in imports.toml")

    spec = m.imports[handle]
    if spec.is_path():
        # Path imports just need to be dropped from the manifest — no lock entry, no cache
        del m.imports[handle]
        manifest.write(m, manifest_path)
        ui.info(f"Removed [imports.{handle}] (path import) from imports.toml")
        return 0

    # URL import — check freeze state
    lock_path = city_root / "pack.lock"
    lf = lockfile.read(lock_path)
    locked = lf.get(handle)
    if locked and locked.frozen:
        ui.die(
            f"{handle!r} is currently frozen in ./packs/{handle}/. "
            f"Run `gc import thaw {handle}` first, then `gc import remove {handle}`."
        )

    # Drop from manifest
    del m.imports[handle]

    # Compute the new closure (everything reachable from remaining imports)
    # — anything in the lock that's no longer reachable is GC'd
    from lib import resolver
    direct = resolver.pending_from_manifest(m)
    accelerator = cache.user_accelerator_root()
    accelerator.mkdir(parents=True, exist_ok=True)
    try:
        new_closure = resolver.resolve(direct, accelerator)
    except resolver.ResolveError as e:
        ui.die(f"resolver error after removal: {e}")

    # Decide what to remove from the lock and from city.toml
    keep_handles = set(new_closure.keys()) | {h for h, p in lf.packs.items() if p.frozen}
    to_remove = set(lf.packs.keys()) - keep_handles
    to_remove.add(handle)  # explicitly remove the requested handle even if it stayed reachable somehow

    removed_from_lock = []
    for h in to_remove:
        if h in lf.packs and not lf.packs[h].frozen:
            del lf.packs[h]
            cache.remove_pack_from_cache(city_root, h)
            removed_from_lock.append(h)

    # Update lock entries with the new closure (in case constraints/versions changed)
    # Preserve frozen entries — they're sealed.
    for h, rp in new_closure.items():
        existing = lf.packs.get(h)
        if existing and existing.frozen:
            continue
        target = cache.city_pack_cache(city_root) / h
        if not target.exists():
            from lib import git as gitlib
            gitlib.materialize(rp.accelerator_path, target, subpath=rp.subpath)
        content_hash = cache.hash_directory(target)
        lf.packs[h] = lockfile.LockedPack(
            handle=h,
            url=rp.url,
            version=str(rp.version),
            constraint=rp.constraint,
            commit=rp.commit,
            hash=content_hash,
            parent=rp.parent,
            frozen=False,
            subpath=rp.subpath,
        )
    lockfile.write(lf, lock_path)

    # Update city.toml
    from lib import git as gitlib
    city_data = citytoml.read(city_root / "city.toml")
    existing_includes = citytoml.get_includes(city_data)
    frozen_handles = {h for h, p in lf.packs.items() if p.frozen}
    managed_handles = set(new_closure.keys()) | frozen_handles
    user_includes = [
        e for e in existing_includes
        if e not in managed_handles
        and e not in to_remove
        and not any(e == f"./packs/{h}" for h in to_remove)
        and not any(e == f"./packs/{h}" for h in managed_handles)
    ]
    new_includes = list(user_includes)
    for h in sorted(new_closure.keys()):
        if h in frozen_handles:
            entry = f"./packs/{h}"
        else:
            entry = h
        if entry not in new_includes:
            new_includes.append(entry)

    new_packs = {}
    for h, rp in new_closure.items():
        # Skip frozen — they don't get [packs.X] blocks
        if h in frozen_handles:
            continue
        repo_url, _ = gitlib.split_url_and_subpath(rp.url)
        ref = f"v{rp.version}" if rp.subpath == "" else f"{rp.subpath}/v{rp.version}"
        new_packs[h] = citytoml.PacksBlock(
            name=h,
            source=repo_url,
            ref=ref,
            path=rp.subpath,
        )

    citytoml.update_includes_and_packs(
        city_root / "city.toml",
        new_includes=new_includes,
        new_packs=new_packs,
        removed_packs=to_remove,
    )

    manifest.write(m, manifest_path)

    ui.info(f"Removed [imports.{handle}] from imports.toml")
    if len(removed_from_lock) > 1:
        gc = sorted(set(removed_from_lock) - {handle})
        ui.info(f"Garbage-collected transitive deps: {', '.join(gc)}")
    ui.info(f"Updated city.toml, pack.lock")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
