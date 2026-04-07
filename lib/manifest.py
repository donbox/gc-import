"""Read/write the [imports] section of city.toml.

The user-facing manifest of direct imports lives inline in city.toml as:

    [imports.gastown]
    url = "https://github.com/example/gastown"
    version = "^1.2"

    [imports.local]
    path = "./packs/local"

This is the v1 schema. In v2, the same syntax moves to pack.toml at the
city root. The package manager owns the [imports] section but does not own
the rest of city.toml — surgical text edits in lib/citytoml.py preserve
the user's other sections, comments, and formatting.

Read here is straight tomllib. Write here delegates to citytoml.update_imports.
"""

import tomllib
from dataclasses import dataclass, field
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
    imports: dict[str, ImportSpec] = field(default_factory=dict)


def read(city_toml_path: Path) -> Manifest:
    """Read the [imports] section out of a city.toml file.

    Returns an empty manifest if city.toml doesn't exist or has no [imports].
    """
    if not city_toml_path.exists():
        return Manifest()
    with open(city_toml_path, "rb") as f:
        data = tomllib.load(f)
    imports: dict[str, ImportSpec] = {}
    for handle, entry in data.get("imports", {}).items():
        if not isinstance(entry, dict):
            continue
        spec = ImportSpec(
            handle=handle,
            url=entry.get("url"),
            version=entry.get("version"),
            path=entry.get("path"),
        )
        spec.validate()
        imports[handle] = spec
    return Manifest(imports=imports)


def write(m: Manifest, city_toml_path: Path) -> None:
    """Write the [imports] section back into city.toml.

    Delegates to citytoml.update_imports for the surgical text edit.
    """
    # Imported lazily to avoid a circular import (citytoml may want manifest types)
    from . import citytoml
    citytoml.update_imports(city_toml_path, m.imports)
