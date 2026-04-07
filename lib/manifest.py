"""imports.toml read/write — the user-facing manifest of direct imports.

Format:
    [imports.gastown]
    url = "https://github.com/example/gastown"
    version = "^1.2"

    [imports.local]
    path = "./packs/local"

This is the v1 sidecar file. In v2 it gets folded into pack.toml.
The package manager owns this file fully and can rewrite it without
preserving formatting. Users edit it by hand to bump constraints, etc.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ImportSpec:
    handle: str
    url: Optional[str] = None
    version: Optional[str] = None  # the constraint string, not the resolved version
    path: Optional[str] = None

    def is_url(self) -> bool:
        return self.url is not None

    def is_path(self) -> bool:
        return self.path is not None

    def validate(self) -> None:
        if self.is_url() and self.is_path():
            raise ValueError(f"import {self.handle!r} has both url and path")
        if not self.is_url() and not self.is_path():
            raise ValueError(f"import {self.handle!r} has neither url nor path")


@dataclass
class Manifest:
    imports: dict[str, ImportSpec]


def read(path: Path) -> Manifest:
    """Read imports.toml. Returns an empty manifest if the file doesn't exist."""
    if not path.exists():
        return Manifest(imports={})
    with open(path, "rb") as f:
        data = tomllib.load(f)
    imports = {}
    for handle, entry in data.get("imports", {}).items():
        spec = ImportSpec(
            handle=handle,
            url=entry.get("url"),
            version=entry.get("version"),
            path=entry.get("path"),
        )
        spec.validate()
        imports[handle] = spec
    return Manifest(imports=imports)


def write(m: Manifest, path: Path) -> None:
    """Write imports.toml. Atomic, no formatting preservation."""
    lines = [
        "# gc import — direct pack imports for this city.",
        "# Edit by hand to bump constraints, then run `gc import upgrade`.",
        "",
    ]
    for handle in sorted(m.imports.keys()):
        spec = m.imports[handle]
        lines.append(f"[imports.{handle}]")
        if spec.is_url():
            lines.append(f'url = "{spec.url}"')
            if spec.version:
                lines.append(f'version = "{spec.version}"')
        else:
            lines.append(f'path = "{spec.path}"')
        lines.append("")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(lines))
    tmp.replace(path)
