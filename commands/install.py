#!/usr/bin/env python3.11
"""gc import install — restore the city to the exact state in pack.lock.

Usage:
    gc import install

Reads pack.lock, fetches every entry from its recorded URL at the recorded
commit, materializes each pack into .gc/cache/packs/, and verifies the
content hash. Does NOT modify city.toml or pack.lock.

Frozen entries are skipped — they're already in ./packs/<name>/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import cache, git as gitlib, lockfile, ui  # noqa: E402


def main(argv: list[str]) -> int:
    if argv:
        ui.die("gc import install takes no arguments")

    city_root = ui.find_city_root()
    lock_path = city_root / "pack.lock"
    if not lock_path.exists():
        ui.die("no pack.lock found in this city. Run `gc import add` first.")

    lf = lockfile.read(lock_path)
    if not lf.packs:
        ui.info("Nothing to install — pack.lock is empty.")
        return 0

    accelerator = cache.user_accelerator_root()
    accelerator.mkdir(parents=True, exist_ok=True)
    pack_cache_root = cache.city_pack_cache(city_root)
    pack_cache_root.mkdir(parents=True, exist_ok=True)

    ui.info(f"Installing from pack.lock ({len(lf.packs)} entries)...")
    failed = []
    for handle in sorted(lf.packs.keys()):
        p = lf.packs[handle]
        if p.frozen:
            ui.step(f"{handle} v{p.version} (frozen, in ./packs/) — skipped", indent=1)
            continue

        # Fetch into the accelerator (no-op if already present)
        repo_url, _ = gitlib.split_url_and_subpath(p.url)
        try:
            accel_path = gitlib.fetch_to_accelerator(repo_url, p.commit, accelerator)
        except gitlib.GitError as e:
            ui.warn(f"failed to fetch {handle}: {e}")
            failed.append(handle)
            continue

        # Materialize into the city cache
        target = pack_cache_root / handle
        gitlib.materialize(accel_path, target, subpath=p.subpath)

        # Verify hash
        actual = cache.hash_directory(target)
        if p.hash and actual != p.hash:
            ui.warn(f"hash mismatch for {handle}: lock says {p.hash}, got {actual}")
            failed.append(handle)
            continue

        ui.step(f"{handle} v{p.version} ✓", indent=1)

    if failed:
        ui.die(f"install failed for: {', '.join(failed)}", code=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
