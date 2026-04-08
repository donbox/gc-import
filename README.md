# gc import

A URL-based package manager for Gas City packs.

`gc import` is the answer to "how do I add a pack to my city without hand-editing TOML?" It handles git URL identity, semver constraints, transitive dependency resolution, lock files, and a small implicit-imports baseline — in five verbs and zero third-party Python dependencies.

```
$ gc import add https://github.com/example/gastown
Resolving https://github.com/example/gastown...
  Selected: 1.4.0 (latest, default constraint ^1.4)
  Recursing into [imports]:
    polecat → https://github.com/example/polecat
      Selected: 0.4.1 (constraint ^0.4)
  Materialized → .gc/cache/packs/gastown/, .gc/cache/packs/polecat/
  Updated city.toml ([imports], [packs], includes) and pack.lock (2 entries)
```

That's the whole experience. One command, full transitive resolution, ready to run.

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [The five verbs](#the-five-verbs)
  - [`gc import add`](#gc-import-add)
  - [`gc import remove`](#gc-import-remove)
  - [`gc import install`](#gc-import-install)
  - [`gc import upgrade`](#gc-import-upgrade)
  - [`gc import list`](#gc-import-list)
- [Concepts](#concepts)
  - [Imports vs locks vs caches](#imports-vs-locks-vs-caches)
  - [Local handles vs URLs](#local-handles-vs-urls)
  - [Transitive resolution](#transitive-resolution)
  - [Implicit imports (the maintenance pack)](#implicit-imports-the-maintenance-pack)
- [Common workflows](#common-workflows)
- [Multi-pack monorepos](#multi-pack-monorepos)
- [Side-by-side versions](#side-by-side-versions)
- [Troubleshooting](#troubleshooting)
- [v1 vs v2 schema](#v1-vs-v2-schema)
- [How it works under the hood](#how-it-works-under-the-hood)

## Installation

`gc import` is itself a Gas City pack. To install it in a city, add it via the existing `gc pack` mechanism:

```toml
# city.toml
[packs.import]
source = "https://github.com/donbox/gc-import"
ref = "v0.1.0"

[workspace]
includes = ["import", ...]
```

Then run `gc pack fetch`. After that, `gc import` is available as a subcommand of `gc`.

**Requirements:**

- **Python 3.11 or later** in `PATH` as `python3.11`, `python3.12`, etc., or as `python3` if it's 3.11+. The scripts use `tomllib` from stdlib.
- **`git`** in `PATH`. All repository operations are subprocess calls.
- **No other dependencies.** No `pip install`, no virtualenv, no `tomlkit`. Just stdlib.

If `python3.11` isn't installed: `brew install python@3.11` (macOS) or your distro's equivalent.

Run `gc doctor` after installing to verify both requirements.

## Quick start

Five commands take you from an empty city to a working install with a transitive dependency:

```
# 1. Initialize a city if you don't have one already
$ gc init my-city
$ cd my-city

# 2. Add a pack
$ gc import add https://github.com/example/gastown
Resolving https://github.com/example/gastown...
  Selected: 1.4.0 (latest, default constraint ^1.4)
  Recursing into [imports]:
    polecat → https://github.com/example/polecat
      Selected: 0.4.1 (constraint ^0.4)
  Materialized → .gc/cache/packs/gastown/, .gc/cache/packs/polecat/
  Updated city.toml ([imports], [packs], includes) and pack.lock (2 entries)

# 3. See what you imported
$ gc import list
NAME     VERSION  CONSTRAINT  URL
gastown  1.4.0    ^1.4        https://github.com/example/gastown
polecat  0.4.1    ^0.4        https://github.com/example/polecat ← gastown

# 4. Commit city.toml and pack.lock
$ git add city.toml pack.lock
$ git commit -m "Add gastown"

# 5. Your teammate clones the city and runs install
$ git clone <your-city-repo>
$ cd my-city
$ gc import install
Installing from pack.lock (2 entries)...
  gastown v1.4.0 ✓
  polecat v0.4.1 ✓
```

That's the entire onboarding flow. There is no `gc import init`, no `gc import register`, no setup file to edit. The first `add` does everything that needs to happen.

## The five verbs

### `gc import add`

Add a pack to the city's imports.

```
gc import add <url|path> [--version <constraint>] [--name <handle>]
```

The argument shape selects the form:

- **URL** (`http://`, `https://`, `git@`, `ssh://`): fetches the repo, picks the highest tag matching the constraint, recurses into the pack's `[imports]` and resolves them, materializes everything into `.gc/cache/packs/`, and writes to `city.toml` (the new `[imports]` section, plus the machine-managed `[packs]` and `[workspace].includes`) and `pack.lock`.
- **Path** (`/`, `.`, `~` prefix): writes a `path =` import. No fetching, no lock entry, no recursion. The loader reads from the path directly.

If `--version` is omitted, the constraint defaults to `^<major>.<minor>` of the latest available tag (compatible updates within the major version).

If `--name` is omitted, the local handle is derived from the URL or path's last segment (`https://github.com/example/gastown` → `gastown`). If that handle already exists in the city's `[imports]`, `gc import add` errors and tells you to retry with `--name <alias>`. The resolver never auto-suffixes — when there's a collision, you pick the new name explicitly. (Same shape as `gc rig add` and `gc city register`.)

```
$ gc import add https://github.com/example/gastown
$ gc import add https://github.com/example/gastown --version "^1.5"
$ gc import add https://github.com/example/gastown --name gastown_v1
$ gc import add https://github.com/other-org/gastown --name other-gtwn  # alias to dodge a collision
$ gc import add ../my-local-pack
```

### `gc import remove`

Remove a pack from the city's imports. Garbage-collects transitive deps that are no longer needed.

```
gc import remove <name>
```

```
$ gc import remove gastown
Removed [imports.gastown] from city.toml
Garbage-collected transitive deps: polecat
Updated city.toml, pack.lock
```

Implicit imports (the maintenance pack and anything else in `~/.gc/implicit-import.toml`) cannot be removed via `gc import remove` — they aren't in `[imports]` to drop. To opt out of implicit imports for a city, set `implicit_imports = false` at the top of that city's `city.toml`. See [Implicit imports (the maintenance pack)](#implicit-imports-the-maintenance-pack) below.

### `gc import install`

Restore the city to the exact state recorded in `pack.lock`. The cold-clone / CI / teammate-onboarding command.

```
gc import install
```

In the common case, reads `pack.lock`, fetches each entry from its recorded URL at its recorded commit, materializes into `.gc/cache/packs/`, and verifies content hashes. Pure restore: does not modify `city.toml` or `pack.lock`.

```
$ gc import install
Installing from pack.lock (2 entries)...
  gastown v1.4.0 ✓
  polecat v0.4.1 ✓ (implicit)
```

If `pack.lock` doesn't exist, OR is missing entries that the resolver would compute (e.g. you ran `gc init` and never invoked `gc import add` directly, so the lock has no entries but the implicit list still wants to bring in the maintenance pack), `install` self-heals by doing a full resolve and writing a fresh lock. This is the load-bearing trigger that makes implicit imports work for users who never type `gc import add`.

Uses the hidden download accelerator (`~/.gc/cache/repos/`) so two cities pinning the same commit share one clone.

### `gc import upgrade`

Re-resolve the constraints in `[imports]` (in `city.toml`) against the latest available tags, pick higher versions where the constraint allows, and rewrite `pack.lock`.

```
gc import upgrade            # upgrade everything
gc import upgrade <name>     # upgrade just one pack and its transitive descendants
```

The constraint itself is **not** modified — only the resolved version. Bumping a constraint (e.g., `^1.2` → `^2.0`) requires editing the `[imports.<name>] version = "..."` line in `city.toml` by hand and then running `gc import upgrade`.

```
$ gc import upgrade gastown
Upgrading gastown...
  gastown: 1.4.0 → 1.5.0
Updated city.toml [packs] entries and pack.lock
```

Implicit imports are upgraded along with everything else; you can also `gc import upgrade <implicit-handle>` to bump just the maintenance pack.

### `gc import list`

Show what this city imports.

```
gc import list           # flat table
gc import list --tree    # indented import graph
```

Default: a flat table of every pack in `pack.lock` (direct + transitive), one row per pack.

```
$ gc import list
NAME         VERSION  CONSTRAINT  URL
gastown      1.4.0    ^1.4        https://github.com/example/gastown
polecat      0.4.1    ^0.4        https://github.com/example/polecat ← gastown
maintenance  1.5.0    ^1          https://github.com/gastownhall/maintenance ← (implicit)

$ gc import list --tree
└── gastown 1.4.0 (^1.4)  — https://github.com/example/gastown
    └── polecat 0.4.1 (^0.4)  — https://github.com/example/polecat
└── maintenance 1.5.0 (^1) (implicit)  — https://github.com/gastownhall/maintenance
```

## Concepts

### Imports vs locks vs caches

Three things to keep in your head, and they have different jobs:

| What | Where | Who edits it | Purpose |
|---|---|---|---|
| **`[imports]` in `city.toml`** | City root | The user (or `gc import add`/`remove`) | The city's *intent* — direct imports + version constraints |
| **`pack.lock`** | City root | `gc import` only — never by hand | The *exact* resolved transitive closure: every pack, its commit, its hash |
| **`city.toml`** [packs] + includes | City root | `gc import` writes; user reads (and writes [beads] etc.) | What the gascity loader actually consumes |
| **`.gc/cache/packs/`** | City root, gitignored | `gc import` only | Materialized pack directories the loader reads at startup |
| **`~/.gc/cache/repos/`** | User home, hidden | `gc import` only | Shared download accelerator across all cities on this machine |

The boundaries: **`[imports]` in `city.toml` is the user's intent**, **`pack.lock` is the truth**, the rest is derived. Commit `city.toml` and `pack.lock`. Gitignore `.gc/`. The `~/.gc/` cache is your machine's business and never enters version control.

### Local handles vs URLs

When you write `[imports.gastown] url = "..."` in `city.toml`, the word `gastown` is the **local handle** — the name this city uses for the pack internally. It becomes the directory name in `.gc/cache/packs/gastown/`, the namespace prefix for agents (`gastown.mayor`), and the includes-list entry in `city.toml`.

The URL is the pack's **global identity**. Two different URLs can have the same local handle in different cities (or even in the same city — see [side-by-side versions](#side-by-side-versions)). The handle is for *consumption*; the URL is for *resolution*.

You can override the default handle with `--name`:

```
$ gc import add https://github.com/example/gastown --name gtwn
```

Now the city refers to it as `gtwn`, and agents are qualified `gtwn.mayor`.

### Transitive resolution

When you `gc import add gastown`, the resolver doesn't stop at gastown. It reads gastown's own `pack.toml`, sees its `[imports]` block, fetches each dependency, reads *their* pack.toml files, and so on until everything is materialized. Every node in the transitive closure ends up in `pack.lock` with a `parent` field marking transitive entries.

You only think about your direct intent. The resolver handles the rest.

If two transitive constraints on the same URL meet, the resolver:

- **Same major** → unifies to the highest version satisfying both. polecat 1.2.3 and 1.5.0 → 1.5.0.
- **Different majors** → errors with a clear remediation hint asking you to disambiguate with explicit handles. The resolver never auto-suffixes.

### Implicit imports (the maintenance pack)

Every city automatically imports a small baseline set of packs, regardless of what's in `[imports]`. **In v1 the baseline is exactly one pack: `maintenance`.** A user who runs `gc init my-city && gc start` and never touches `gc import` still ends up with a working maintenance pack.

The mental model: think of implicit imports as `[imports.X]` blocks that have been lexically prepended to your `[imports]` section by the package manager. They go through the same resolver, end up in the same `pack.lock`, materialize into the same `.gc/cache/packs/`, and show up in `gc import list` — they just aren't *visible* in your `city.toml`'s `[imports]` section, because they're not your direct intent.

You'll see them tagged `(implicit)` in `gc import list`:

```
NAME         VERSION  CONSTRAINT  URL                                              PARENT
gastown      1.4.0    ^1.4        https://github.com/example/gastown               —
maintenance  1.5.0    ^1          https://github.com/gastownhall/maintenance       ← (implicit)
```

And tagged `parent = "(implicit)"` in `pack.lock`. That `parent` field is what `gc import remove` checks when you try to remove an implicit handle:

```
$ gc import remove maintenance
error: 'maintenance' is an implicit import (every city gets it automatically). It's
not in city.toml's [imports] to remove. To disable implicit imports in this city,
set `implicit_imports = false` at the top of city.toml.
```

**Three knobs**, all in your city's `city.toml`:

- **Default** (do nothing): every city gets the implicit baseline.
- **Opt-out**: set `implicit_imports = false` at the top of `city.toml`. The resolver skips the implicit list entirely; the maintenance pack is not fetched, locked, or materialized. Use this for embedded / minimal / specialized cities.
- **Override**: add an explicit `[imports.maintenance]` block to your `city.toml` pointing at a different URL or version. The merge rule (city wins on collision) means your version wins and the implicit one is silently dropped. No auto-suffixing, no parallel installs.

**Where the implicit list lives**: `~/.gc/implicit-import.toml`. This file is set by `gc-import` on first run and is not user-facing configuration — there are no commands to manage it, and the expected state is "the file exists with whatever we shipped, and nobody touches it." Think of it less like `~/.bashrc` and more like a vendor-installed config under `/etc/`. If you need a different maintenance pack (a fork, an internal version, a pinned older version), the user-facing way to do that is to add an explicit `[imports.maintenance]` block to your `city.toml`, not to edit the implicit file.

## Common workflows

### Adding a pack and a teammate cloning it

```
# You
$ gc import add https://github.com/example/gastown
$ git add city.toml pack.lock
$ git commit -m "Add gastown"
$ git push

# Teammate
$ git pull
$ gc import install        # one command, exact reproduction
```

### Bumping a pack to the latest minor version

```
$ gc import upgrade gastown
gastown: 1.4.0 → 1.5.0
$ git add pack.lock city.toml
$ git commit -m "Upgrade gastown 1.4.0 → 1.5.0"
```

### Bumping a constraint to a new major version

The constraint isn't bumped automatically — that's a deliberate choice. Edit `city.toml`:

```toml
[imports.gastown]
url = "https://github.com/example/gastown"
version = "^2.0"        # was "^1.4"
```

Then re-resolve:

```
$ gc import upgrade gastown
gastown: 1.5.0 → 2.0.0
```

### Iterating on a local pack

```
$ gc import add ../my-pack       # writes [imports.my-pack] path = "../my-pack"
# Edit ../my-pack — changes are picked up immediately, no install needed
```

### Removing a pack

```
$ gc import remove gastown
Removed [imports.gastown] from city.toml
Garbage-collected transitive deps: polecat
Updated city.toml, pack.lock
```

If polecat was only there because gastown needed it, it's gone too.

## Multi-pack monorepos

If a team wants to ship several related packs from one git repo, they can use **subpath URLs** the way Go modules support multi-module repos:

```
$ gc import add https://github.com/example/multi-pack/gastown
$ gc import add https://github.com/example/multi-pack/maintenance
```

The resolver clones the repo once into `~/.gc/cache/repos/<hash>/` and reads `gastown/pack.toml` (or `maintenance/pack.toml`) at the requested subpath. Tags for subpath packs are prefixed with the subpath (Go modules style):

```
gastown/v1.0.0
gastown/v1.1.0
gastown/v1.2.3          ← gastown pack at version 1.2.3
maintenance/v1.0.0
maintenance/v2.0.1      ← maintenance pack at version 2.0.1
```

The resolver filters tags by subpath prefix and strips it before parsing as semver. Subpath URLs are an authoring convenience for monorepo maintainers — from a consumer's POV, every import is just a URL.

## Side-by-side versions

Three cases, all resolved by the principle that **the local handle is the namespace key**.

### Case 1: Different versions in different cities on the same machine

Trivial. The hidden accelerator is keyed by URL+commit, so different commits get different clones. Each city has its own `pack.lock` and its own pack cache. They never interfere.

### Case 2: Within-city transitive conflict

If gastown's deps want polecat ^1.2 and maintenance's deps want polecat ^1.5, the resolver unifies them to the highest common version (1.5.x). Same major, no problem.

If gastown wants polecat ^1.2 and maintenance wants polecat ^2.0, the resolver errors with a remediation hint:

```
Conflict: polecat is required at incompatible majors.
  - gastown wants polecat ^1.2 (would resolve 1.5.0)
  - maintenance wants polecat ^2.0 (would resolve 2.0.1)

Add explicit imports to disambiguate. In city.toml:

  [imports.polecat_v1]
  url = "https://github.com/example/polecat"
  version = "^1.2"
  [imports.polecat_v2]
  url = "https://github.com/example/polecat"
  version = "^2.0"
```

You add the two explicit handles, the resolver binds the transitive references to the matching one, and both versions coexist.

### Case 3: Intentional dual-import

You *want* two versions (migration, A/B testing). Just write two `[imports]` blocks with different local handles pointing at the same URL:

```toml
[imports.gastown_v1]
url = "https://github.com/example/gastown"
version = "^1.5"

[imports.gastown_v2]
url = "https://github.com/example/gastown"
version = "^2.0"
```

Both get fetched, both get cache directories at `.gc/cache/packs/gastown_v1/` and `.gc/cache/packs/gastown_v2/`, agents become `gastown_v1.mayor` and `gastown_v2.mayor`. The loader treats them as completely independent packs that happen to share an upstream.

## Troubleshooting

### "no version of … matches constraint"

Your constraint excludes every available tag. Check the constraint with `cat city.toml`, run `git ls-remote --tags <url>` to see what's actually published, and either:

- Loosen the constraint (e.g., `^1.0` instead of `^1.5`).
- Check that the upstream repo uses semver tags (`v1.2.3` or `1.2.3`, optionally prefixed for subpath URLs).

### "no version tags found for …"

The repo has no git tags at all, or no tags matching the subpath prefix (for subpath URLs). The package manager refuses to install untagged code — version pinning requires tags. If you really need a specific commit, file an issue and we'll consider a `--commit <sha>` escape hatch.

### "hash mismatch for …"

`gc import install` checked the content hash and got something different from what `pack.lock` recorded. This usually means:

- Someone ran `gc import upgrade` and forgot to commit `pack.lock`.
- A pack repo was force-pushed and the commit has new content under the same SHA (rare; mostly impossible).
- Manual editing of `.gc/cache/packs/<name>/`.

Run `gc import upgrade <name>` to re-resolve and refresh the hash, or `gc import install --force` (planned) to override.

### "cross-major version conflict for …"

See [Case 2](#case-2-within-city-transitive-conflict) above. Add explicit `[imports.X_v1]` and `[imports.X_v2]` blocks to coexist them.

### "not in a Gas City — no city.toml found"

`gc import` walks up from the current working directory looking for the nearest `city.toml`. Make sure you're inside a city directory (or one of its subdirectories).

## v1 vs v2 schema

`gc import` ships against the **v1 schema** today: `[imports]`, `[packs]`, and `[workspace].includes` all live inline in `city.toml`. The `[imports]` section is the user-facing surface; `[packs]` and `[workspace].includes` are machine-managed mirrors that the gascity loader reads. This works with the gascity loader as it exists right now — no Go changes required. (`[imports]` is a section the v1 loader doesn't recognize, so it's silently ignored by gascity until v2 lands.)

The **v2 schema** is the long-term destination: a top-level `pack.toml` at the city root with `[imports]` blocks directly, no sidecar, no separate `[packs]` and `includes` constructs. The v2 schema needs three small additions to the gascity loader (read pack.toml at city root, recognize `[imports]` blocks, prefer `./packs/` over `.gc/cache/packs/`). When those land, `gc import` will gain a one-shot `gc import migrate` command that converts a v1 city to v2 mechanically.

Until then, the user-visible mechanics are:

- Edit the `[imports]` section of `city.toml` to express intent (or let `gc import add` write it).
- Read the `[imports]` section of `city.toml` to see your direct imports and constraints.
- Read `pack.lock` to see the full transitive closure.
- Treat `[packs]` and `[workspace].includes` in `city.toml` as machine-managed — `gc import` writes them; you don't.

## How it works under the hood

For the curious, here's the machinery.

### The hidden download accelerator

`~/.gc/cache/repos/<sha256(url+commit)>/` is a per-(URL, commit) git clone, populated as a side effect of `gc import add`/`upgrade`/`install`. It is never user-visible — there are no commands to inspect or manipulate it. Wiping `~/.gc/cache/` costs nothing except the next fetch being slower. This is the Go modules model.

Two cities pinning the same commit share one clone. Two cities pinning different commits get two clones. Within a single city, only the *latest* relevant commit is fetched (the lock file determines what install needs).

### The implicit-imports splice

Before `add` / `install` / `upgrade` hands its imports to the resolver, it does a small dict merge:

```
spliced = read implicit imports from ~/.gc/implicit-import.toml
spliced.merge(city's [imports])     # city wins on collision
implicit_handles = {h for h in implicit if h not in city imports}
hand spliced to the resolver
```

After the resolver returns a closure, the lock-writer marks any closure entry whose handle is in `implicit_handles` (and which has no transitive parent of its own) with `parent = "(implicit)"`. That marker is what `gc import list` reads to display the `(implicit)` tag and what `gc import remove` reads to refuse removal.

The splice runs once per resolver invocation, costs nothing perceptible, and is bypassed entirely if the city has `implicit_imports = false` set at the top of its `city.toml`.

### `gc import install` self-heals

`gc import install` checks whether the city's `pack.lock` already accounts for the city's `[imports]` plus the implicit list. If yes, it does the pure-restore path (read lock, fetch each entry, materialize, verify hash). If no — pack.lock is missing entries the resolver would compute — it falls through to a full resolve + lock + materialize + city.toml mirror. This is the load-bearing trigger that makes implicit imports work for users who never type `gc import add` directly: a fresh `gc init` followed by `gc start` triggers an `install` which detects the missing maintenance entry and self-heals.

### The resolution algorithm

```
resolve(direct_imports):
    queue = direct_imports.copy()
    closure = {}
    while queue:
        spec = queue.pop()
        if spec.path:
            continue  # path imports don't recurse, no lock entry
        tags = git ls-remote --tags <url>
        version = pick highest semver matching the constraint
        commit = sha of that tag
        check for cross-major conflict against closure entries with same URL
        clone to ~/.gc/cache/repos/<hash>/ if not present
        read pack.toml at the resolved commit
        for each [imports.X] block in that pack.toml:
            queue.append(spec for X with parent = current handle)
        closure[handle] = ResolvedPack(...)
    return closure
```

No SAT solver. Cross-major conflicts surface as errors with the parent chain. Same-major conflicts unify to the highest common version.

### The materializer

After resolution, each pack in the closure is copied from the accelerator into the city's `.gc/cache/packs/<handle>/`. The copy strips `.git/`. A content hash (`sha256` of the file tree, sorted, with relative paths and bytes) is computed and recorded in `pack.lock`.

### The city.toml editor

`lib/citytoml.py` does surgical text edits to `city.toml` instead of using a full TOML rewriter. This preserves user formatting, comments, and section ordering. Specifically:

- `[packs.X]` blocks are detected by header regex and rewritten/inserted/deleted in place.
- `[workspace].includes = [...]` is rewritten by replacing the array literal with a freshly-formatted one.
- All other sections (`[beads]`, `[rigs]`, etc.) and all user comments are left untouched.

The deletion logic only removes lines that look like `key = value` after a `[packs.X]` header — comments and other content terminate the block.

### Stdlib only

No `tomlkit`, no `tomli_w`, no `packaging`, no `gitpython`. The TOML reader is `tomllib` (stdlib in 3.11+); writers are hand-rolled because the package manager fully owns `pack.lock` and does surgical text edits to the `[imports]`, `[packs]`, and `[workspace].includes` sections of `city.toml`. Git operations are subprocess calls.

The motivation: zero install friction. A user running `gc import add` for the first time should not need to `pip install` anything.

---

## Project layout

```
gc-import/
├── pack.toml                   # declares the [[commands]] entries
├── README.md                   # this file
├── doctor/
│   └── check-python.sh         # verifies Python 3.11+ is available
├── commands/
│   ├── add.py                  # gc import add
│   ├── remove.py               # gc import remove
│   ├── install.py              # gc import install (and the self-healing first-run path)
│   ├── upgrade.py              # gc import upgrade
│   └── list.py                 # gc import list
└── lib/
    ├── semver.py               # constraint parsing and matching
    ├── git.py                  # subprocess wrappers around git
    ├── lockfile.py             # pack.lock read/write
    ├── manifest.py             # [imports] section read from city.toml
    ├── citytoml.py             # surgical edits to city.toml
    ├── cache.py                # cache management
    ├── implicit.py             # ~/.gc/implicit-import.toml splice
    ├── resolver.py             # transitive resolution
    └── ui.py                   # consistent output formatting
```

## License

Same as Gas City. See `gascity/LICENSE` for details.

## See also

- [doc-packman.md](https://github.com/donbox/gc-import/blob/main/docs/design.md) — the full design document for `gc import`, including the journey from the initial tap-based design through the no-tap rewrite to the current model.
- [doc-registry.md](https://github.com/donbox/gc-registry/blob/main/docs/design.md) — the companion design for `gc registry`, the local pack store + discovery surface that pairs with `gc import`. Discovery and curation live there; `gc import` stays focused on resolution and lock-file management.
- [`gc-registry`](https://github.com/donbox/gc-registry) — the implementation of the registry commands, shipped as a separate Gas City pack.
- [Gas City](https://github.com/gastownhall/gascity) — the main project.
