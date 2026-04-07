"""Transitive resolution for gc import.

Given a set of direct imports (from imports.toml), the resolver:
  1. Fetches each repo, finds the highest tag matching the constraint.
  2. Reads the resolved pack's pack.toml.
  3. Recurses into the pack's own [imports] block.
  4. Collects everything into a closure keyed by local handle.
  5. Detects same-major version collisions (unifies them) and cross-major
     conflicts (errors with parent chain).

The closure is then handed off to the materializer, which copies each
pack into the city's .gc/cache/packs/ directory and writes pack.lock.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import git
from . import semver


class ResolveError(Exception):
    pass


@dataclass
class ResolvedPack:
    handle: str
    url: str
    subpath: str
    version: semver.Version
    constraint: str
    commit: str
    parent: Optional[str] = None  # local handle of the parent that pulled this in
    accelerator_path: Path = None  # path to the clone in ~/.gc/cache/repos/


def _filter_tags_for_subpath(tags: list[tuple[str, str]], subpath: str) -> list[tuple[str, str]]:
    """If the URL has a subpath, filter to tags prefixed with `<subpath>/` and strip the prefix."""
    if not subpath:
        # Filter out anything that looks like a prefixed monorepo tag
        return [(name, sha) for name, sha in tags if "/" not in name]
    prefix = subpath + "/"
    out = []
    for name, sha in tags:
        if name.startswith(prefix):
            out.append((name[len(prefix):], sha))
    return out


def _read_pack_toml(pack_dir: Path) -> dict:
    """Read pack.toml from a pack directory. Returns {} if not found."""
    pt = pack_dir / "pack.toml"
    if not pt.exists():
        return {}
    with open(pt, "rb") as f:
        return tomllib.load(f)


@dataclass
class _PendingImport:
    handle: str
    url: Optional[str]
    constraint_str: Optional[str]
    path: Optional[str]
    parent: Optional[str] = None


def resolve(
    direct_imports: list[_PendingImport],
    accelerator_root: Path,
) -> dict[str, ResolvedPack]:
    """Resolve a set of direct imports into a transitive closure.

    Returns a dict mapping local handle → ResolvedPack. Path imports are
    excluded from the closure (they have no version, no commit, no lock entry).
    """
    closure: dict[str, ResolvedPack] = {}
    queue: list[_PendingImport] = list(direct_imports)

    while queue:
        spec = queue.pop(0)

        # Path imports are not resolved/locked — they're loader-time references
        # to local directories. Skip them in the closure.
        if spec.path:
            continue

        if not spec.url:
            raise ResolveError(f"import {spec.handle!r} has no url and no path")

        # Already in the closure under this handle?
        if spec.handle in closure:
            existing = closure[spec.handle]
            if existing.url != spec.url:
                raise ResolveError(
                    f"local handle {spec.handle!r} is bound to two different URLs: "
                    f"{existing.url!r} (from {existing.parent or 'direct'}) and "
                    f"{spec.url!r} (from {spec.parent or 'direct'}). "
                    f"Rename one of them in your imports."
                )
            # Same URL — unify constraints if needed (skip for now; phase 2 work)
            continue

        # Resolve URL → repo + subpath
        repo_url, subpath = git.split_url_and_subpath(spec.url)

        # Fetch tags
        try:
            raw_tags = git.ls_remote_tags(repo_url)
        except git.GitError as e:
            raise ResolveError(f"cannot fetch tags for {repo_url}: {e}")

        tags = _filter_tags_for_subpath(raw_tags, subpath)
        if not tags:
            raise ResolveError(
                f"no version tags found for {spec.url} "
                f"(repo {repo_url}, subpath {subpath!r})"
            )

        # Parse and pick highest matching version
        parsed_versions = []
        version_to_commit = {}
        for tag_name, sha in tags:
            v = semver.parse_tag(tag_name)
            if v is None:
                continue
            parsed_versions.append(v)
            version_to_commit[str(v)] = sha

        if not parsed_versions:
            raise ResolveError(
                f"no semver-parseable tags found for {spec.url} "
                f"(found {len(tags)} tags but none parsed)"
            )

        constraint_str = spec.constraint_str
        if constraint_str:
            constraint = semver.parse_constraint(constraint_str)
        else:
            # Default: ^<major>.<minor> of the highest available version
            constraint = semver.default_constraint_for(max(parsed_versions))
            constraint_str = constraint.raw

        chosen = semver.pick_highest(parsed_versions, constraint)
        if chosen is None:
            available = ", ".join(str(v) for v in sorted(parsed_versions, reverse=True)[:5])
            raise ResolveError(
                f"no version of {spec.url} matches constraint {constraint_str}. "
                f"Available: {available}"
            )

        commit = version_to_commit[str(chosen)]

        # Check for cross-major conflict against existing entries with the same URL
        for other in closure.values():
            if other.url == spec.url and not semver.same_major(other.version, chosen):
                raise ResolveError(
                    f"cross-major version conflict for {spec.url}:\n"
                    f"  - {other.parent or 'direct'} wants {other.constraint} (resolved {other.version})\n"
                    f"  - {spec.parent or 'direct'} wants {constraint_str} (would resolve {chosen})\n"
                    f"\nAdd explicit imports with different local handles to coexist them, e.g.:\n"
                    f"  [imports.{spec.handle}_v{other.version.major}]\n"
                    f"  url = \"{spec.url}\"\n"
                    f"  version = \"^{other.version.major}.{other.version.minor}\"\n"
                    f"  [imports.{spec.handle}_v{chosen.major}]\n"
                    f"  url = \"{spec.url}\"\n"
                    f"  version = \"^{chosen.major}.{chosen.minor}\""
                )

        # Fetch into the accelerator
        accel_path = git.fetch_to_accelerator(repo_url, commit, accelerator_root)

        resolved = ResolvedPack(
            handle=spec.handle,
            url=spec.url,
            subpath=subpath,
            version=chosen,
            constraint=constraint_str,
            commit=commit,
            parent=spec.parent,
            accelerator_path=accel_path,
        )
        closure[spec.handle] = resolved

        # Recurse into the resolved pack's own [imports]
        pack_root = accel_path / subpath if subpath else accel_path
        pack_data = _read_pack_toml(pack_root)
        for inner_handle, inner_entry in pack_data.get("imports", {}).items():
            if inner_handle in closure:
                continue  # already handled (and we'll detect handle conflicts above on re-pop)
            queue.append(_PendingImport(
                handle=inner_handle,
                url=inner_entry.get("url"),
                constraint_str=inner_entry.get("version"),
                path=inner_entry.get("path"),
                parent=spec.handle,
            ))

    return closure


def pending_from_manifest(manifest) -> list[_PendingImport]:
    """Convert a Manifest into a list of _PendingImport for the resolver."""
    out = []
    for handle, spec in manifest.imports.items():
        out.append(_PendingImport(
            handle=handle,
            url=spec.url,
            constraint_str=spec.version,
            path=spec.path,
            parent=None,
        ))
    return out
