# AGENTS_LOOK_HERE.md

> **Read this before changing how MiniWind uses Fio.**
>
> This is the implementation brief and decision record for separating the MiniWind game from its copied Fio engine/editor. It sets the **ultimate target**, the **first engineering milestone**, the ordered migration, and the rules that keep both repositories working while the transition is underway.
>
> **Status:** planning document. The presence of this file does **not** mean that the proposed launcher API, Git submodule, extension hooks, or automated updates already exist.

## 1. The end goal — Fio is the engine; MiniWind is a project built on it

Fio (https://github.com/ViciousSquid/Fio) must remain a self-contained, independently evolving **generic world editor and runtime**. MiniWind (https://github.com/ViciousSquid/MiniWind) must become a **downstream fantasy RPG project**, not a modified distribution or manually synchronised fork of Fio.

When the migration is complete:

1. **One source of truth for the engine.** Fio owns its engine, renderer, editor, project/runtime infrastructure, generic plugin APIs, and shared systems. MiniWind does not carry independent copies of Fio's `engine/`, `editor/`, or generic `plugins/` source.
2. **One source of truth for the game.** MiniWind owns its maps, sprites, sounds, RPG rules, quests, weapons and magic semantics, factions, NPC personalities, living-world simulation, game-specific UI and presentation, and game integration layer. None of these become hardcoded behaviour inside Fio.
3. **MiniWind consumes upstream Fio as a dependency.** The initial target is `vendor/fio/`, a Git submodule pinned to an exact, tested Fio commit. A versioned Python dependency may be evaluated later if packaging/import and asset paths support it more cleanly.
4. **Updating Fio does not mean copying or merging engine files into MiniWind.** A scheduled or explicitly requested update process advances the dependency reference, tests the combined game, and proposes a MiniWind PR. A compatible update can be adopted automatically according to repository policy; a breaking update is rejected or held for repair.
5. **Reproducible and reversible releases.** A MiniWind build identifies the exact Fio SHA that produced it. Rollback is a dependency-pointer change, not a manual reconstruction of copied engine code.
6. **Fio remains usable on its own.** Standalone Fio must continue to launch, edit, play, package, and operate across supported desktop/player targets without knowing MiniWind exists.

**Interpret “without anything breaking” operationally:** upstream Fio changes cannot be guaranteed compatible forever. The requirement is to **detect incompatibility before it lands in MiniWind** and preserve the last known-good pinned Fio revision. Do not automatically point shipped MiniWind builds to an untested moving branch tip.

### Target repository layout (future, not yet implemented)

~~~text
Fio/                              # independently maintained upstream
  main.py / fio_app.py             # standalone entry + generic launch API
  engine/
  editor/
  plugins/
  player/
  tests/

MiniWind/
  main.py                         # very thin downstream launcher
  game/                           # RPG rules, simulation, Fio adapters
  assets/                         # game assets
  maps/                           # game maps/world content
  settings.ini                    # game settings / project descriptor
  tests/
  vendor/
    fio/                          # pinned, UNMODIFIED Git submodule
  .github/workflows/              # test + reviewed/guarded upstream updates
~~~

The exact file layout can be adjusted during implementation. Ownership and reproducibility cannot.

## 2. Why this work is necessary

As inspected on 30 October 2026:

- Fio's default branch is `3.0.0.3010_Latest`; MiniWind's default branch is `main`. Check both again at the start of implementation rather than assuming these branch names are permanent.
- Both repositories currently contain top-level `engine/`, `editor/`, and `plugins/` directories. A previous Git-blob comparison found **51 differing shared engine files** and **18 differing shared editor files**, in addition to files present in only one repository. These are baseline audit figures, **not** a definitive live diff.
- MiniWind already keeps much RPG/game logic in `game/` (notably `game/rpg/`, `game/sim/`, `game/host.py`, `game/fio.py`, and `game/integration.py`).
- MiniWind's current `main.py` supports `[Startup] game_module`, imports that module, and calls its `install()` before creating the editor. MiniWind's `game/__init__.py` registers its native game using `get_manager().register_builtin_game(GAME)` and applies MiniWind editor integration.
- Fio's current `main.py` instead derives a single `root_directory` from its own source or executable, changes the working directory to it, loads settings with `editor.user_paths.settings_path(root_directory)`, prepares asset archives there, and creates `MainWindow(root_directory)`. There is no established public external-project launch API yet.
- MiniWind presently carries integration code that monkeypatches editor internals, and `game/fio.py` sometimes replaces private engine functions. These seams need stable upstream extension points **before** duplicated engine/editor source can be removed.

**The architectural blockage:** embedding a checkout at `MiniWind/vendor/fio` today would make Fio assume the vendored Fio folder is the project directory. MiniWind's settings, assets, maps, packages, and game module cannot safely depend on that assumption.

## 3. Non-negotiable design principles

- **Fio knows projects, not MiniWind.** Never add `import game`, `import miniwind`, hardcoded RPG defaults, faction/hostility semantics, spells, quests, or MiniWind resource paths to Fio.
- **Generic mechanisms upstream; game policies downstream.** Expose a generic extension point in Fio where required. Implement the fantasy behaviour in MiniWind.
- **No permanent local engine fork.** During migration, existing copied code may remain temporarily to preserve the playable game; track and eliminate the divergences rather than silently preserving them indefinitely.
- **Fio's renderer remains swappable.** No migration may bind MiniWind to a particular Fio renderer or require macOS-specific renderer APIs.
- **Keep existing platform obligations.** Preserve Fio's Python, Qt, OpenGL, player/Android, and low-power ARM constraints. Do not turn a bootstrap change into a renderer or framework rewrite.
- **No surprise current-working-directory dependencies.** Prefer explicit paths and a defined project context. Avoid global `chdir` as the mechanism for finding the game.
- **Do not mix architecture work with unrelated gameplay changes.** Every stage needs a limited diff, regression tests, and a rollback path.
- **No claim of tested behaviour without test results.** Distinguish proposals, implemented functionality, headless test results, and manually verified GUI/player behaviour.

## 4. Milestone 1 — Generic, project-root-aware Fio bootstrap

### Objective

Make an ordinary unmodified Fio checkout able to launch **either itself** or an **external project with its own root directory and optional built-in game module**, while keeping standalone Fio behaviour intact.

**This is Milestone 1 only.** It does **not** delete MiniWind's copied engine/editor, add the Fio submodule, remove every MiniWind monkeypatch, or finish the automatic update pipeline.

### Proposed public contract (not yet implemented)

Add a documented, testable Fio entry point along these lines:

~~~python
# Illustrative API proposal: not existing Fio code.
from pathlib import Path
from typing import Sequence

def launch(
    *,
    project_root: str | Path | None = None,
    game_module: str | None = None,
    argv: Sequence[str] | None = None,
) -> int:
    """Start Fio for itself or an external project."""
    ...
~~~

The name and module may be refined in the Fio PR; a dedicated `fio_app.py` or `engine/bootstrap.py` is preferable to importing a script-only `main.py`. Publish the final callable as a supported API with clear documentation.

**Required semantics:**

- `engine_root` is Fio's own install/source resource root.
- `project_root` is the external game's content and configuration root. When omitted, it defaults to `engine_root` so Fio's current standalone experience remains the default.
- `game_module` is an optional Python import path. An explicit argument takes precedence; absent that, a generic `[Startup] game_module` project setting may select one. Empty means there is no game module.
- For a configured game, import it and invoke `install()` **once**, at the correct lifecycle point before menus/windows that rely on registration are built. Provide actionable errors if the module or `install` entry point is invalid.
- External projects must be importable without relying on the shell's starting directory; path insertion/module loading must be explicit, deterministic and tested.
- The project is the authority for project data: authored maps/worlds, game assets, its packages, startup map and game settings. Fio's own built-in editor/core assets, shaders, fonts and defaults remain available as fallback.
- User-modified settings and autosaves must not be written into a read-only vendored/installed Fio tree. Preserve Fio's current writable-path / per-user fallback behaviour, but design for independent per-project settings where needed.
- The working directory must not be permanently changed to Fio just to locate its files. If preserving an existing `chdir` is temporarily essential for standalone compatibility, isolate, document and test it rather than extending the assumption to external projects.
- Importing the bootstrap module alone must not create `QApplication`, start the game loop, write files or import PyQt unnecessarily.
- Retain the existing platform-specific early player entry point (`ANDROID_ARGUMENT` / `FIO_PLAYER`) and bundled/frozen executable behaviour. Do not accidentally route Android through the PyQt editor.
- Avoid multiple QApplication instances and prevent partial registration/side effects after a failed bootstrap.

### File-level implementation plan — Fio repository

1. **Inventory startup paths.** Trace `main.py`, `editor/main_window.py`, `editor/user_paths.py`, `engine/asset_archives.py`, splash/icon/font/shader loading, world/map lookup, editor save/autosave, settings and packaged/player startup. Record which paths are engine-owned and which are project-owned. Search for hardcoded `__file__`, `sys.executable`, `os.getcwd()`, and `root_directory` dependencies.
2. **Introduce a minimal immutable project/engine context.** Give bootstrap and the required services explicit `engine_root` and `project_root`, with narrow documented path resolution. Avoid scattering fallback logic through dozens of call sites. Do not substitute project assets for core engine assets indiscriminately; define which classes of resource can override Fio defaults.
3. **Extract the launch lifecycle from `main.py`.** Preserve supported Python checks, early Android/player selection, OpenGL format setup before QApplication construction, editor styling, splash and error handling, and window construction. Keep `python main.py` as a thin standalone compatibility entry point. Preserve source, frozen and bundled paths.
4. **Generalise project settings.** Revisit `editor/user_paths.settings_path` for a project-scoped settings identity and fallback while preserving existing Fio migrations and macOS read-only bundle behaviour. Do not share a single mutable per-user `Fio/settings.ini` across unrelated games without an explicit design decision.
5. **Add optional game-module installation.** Adapt the already-proven MiniWind `[Startup] game_module` semantics into a Fio-owned generic startup hook. Keep MiniWind's `game/__init__.py`, `MiniwindGame`, RPG editor integration and launcher inside MiniWind.
6. **Make resource ownership visible.** Provide small helper methods, tests and documentation for game paths vs engine paths. Ensure `.fiopak` and blank asset-folder conventions remain compatible; do not introduce extraction of archives into the vendor checkout as a side effect.
7. **Document how a downstream project launches Fio.** A future MiniWind launcher might look like the following **after** Fio has an agreed API and vendor import path:

~~~python
# Illustrative future MiniWind/main.py — do NOT replace the current launcher yet.
from pathlib import Path
from fio_app import launch

if __name__ == "__main__":
    raise SystemExit(
        launch(project_root=Path(__file__).resolve().parent, game_module="game")
    )
~~~

That example assumes the downstream has put its pinned Fio source on Python's import path (or installed it as a package). **Do not copy it verbatim before dependency/import design is complete.**

### Milestone 1 test plan

Write deterministic tests before migrating the game:

| Test | Expected behaviour |
| --- | --- |
| Default standalone launch | No external root or game module; existing Fio root/settings/resources are used. |
| External project root | External maps/assets/settings are resolved from the chosen project, not the vendored Fio directory. |
| Engine fallback resources | Engine-owned shaders/editor assets remain available if not provided by the project. |
| Config precedence | Explicit `game_module` overrides project configuration; empty/absent values behave as documented. |
| Module lifecycle | A dummy game module's `install()` runs once before the editor needs it. |
| Failure paths | Missing module, missing `install`, and installation exceptions produce clear errors and avoid partial startup. |
| Import and cwd independence | Launch succeeds when invoked from an unrelated directory without relying on inherited `PYTHONPATH`. |
| Settings isolation | Two project roots do not overwrite each other's settings or silently alter Fio's settings. |
| Read-only project/engine | Per-user fallback is safe and project-scoped; no writes into vendor or bundle directories. |
| Archive and asset paths | Built-in Fio resources and external `.fiopak` assets are read from the intended roots without accidental extraction. |
| Platform gating | Android/player path stays ahead of PyQt imports; desktop source/frozen paths still resolve correctly. |
| Integration smoke | An external toy project loads; normal standalone Fio can open a world and enter play mode. |

Use headless/unit tests wherever possible; mark Qt/OpenGL smoke tests separately and run on supported systems. A `compileall` success is not proof that GUI startup or rendering works.

### Milestone 1 definition of done

- [ ] A generic public Fio launch API exists and is documented in Fio.
- [ ] Fio standalone startup is unchanged to users, with tests and desktop smoke validation.
- [ ] An **external fixture project**, outside Fio's checkout, can boot with its own settings/assets, a dummy game module, and engine-resource fallbacks.
- [ ] The integration works independently of the shell's current working directory.
- [ ] No MiniWind-specific import, asset path, feature, or RPG rule is introduced into Fio.
- [ ] Fio's supported desktop and player launch paths remain intact.
- [ ] Fio tests and newly added startup/path tests pass; actual results and platform gaps are recorded.
- [ ] The new Fio feature is merged (or available as a reviewed branch/commit) before MiniWind is made to depend on it.
- [ ] MiniWind continues to function with its current copied engine during this milestone. **No premature deletion or submodule switchover.**

## 5. Subsequent milestones — ordered path to the end goal

### Milestone 2 — Establish generic extension seams upstream

Audit MiniWind's divergence from Fio and replace bespoke engine/editor modifications with **generic Fio APIs**. Prioritise Fio-hosted registration and callback surfaces for game input, combat fire/damage filtering, hostility policy, NPC state, optional HUD suppression, game-owned UI/editor menus, toolbar configuration, loading/startup hooks, world/terrain data, camera configuration, and resource packages — only where the codebase actually needs each surface.

Replace fragile monkeypatches in MiniWind's `game/integration.py` and private function replacements in `game/fio.py` with explicit supported hooks. Avoid API explosion; each hook must have a clear user, ownership contract and regression test. Fio contains the **extension point**; MiniWind contains the **RPG policy**.

### Milestone 3 — Reconcile every source divergence

Generate a fresh file-by-file diff of MiniWind's and Fio's `engine/`, `editor/` and `plugins/`. Classify every difference as:

- **Upstream generic fix** → merge into Fio.
- **Game-specific behaviour** → move into `game/` and call through an upstream hook.
- **Obsolete/local workaround** → remove after validation.
- **Unclear** → investigate; never discard blindly.

Track for each changed file: reason, ownership, target upstream PR/commit, dependent MiniWind code, test coverage, and retirement status. Test old saves, streamed worlds, maps, cameras, terrain, gameplay simulation, plugins, and graphical presentation throughout.

### Milestone 4 — Switch MiniWind to a pinned Fio dependency

Only after the compatibility seams and diverged features are reconciled:

1. Add `vendor/fio` as a Git submodule at a known-good Fio SHA.
2. Reduce MiniWind's top-level `main.py` to a thin project launcher using the Milestone 1 API.
3. Make import and resource precedence explicit. Assert that `engine`, `editor`, and `plugins` imports originate from the vendor Fio checkout, **not** a leftover MiniWind local package.
4. Remove the duplicated Fio trees only once the combined tests, world loading, saves, editor/play smoke tests, and packaging paths pass.
5. Verify a fresh clone works with `git clone --recurse-submodules` or `git submodule update --init --recursive`. Keep the submodule checkout clean at runtime.

### Milestone 5 — CI-tested upstream updates

Create a GitHub Actions workflow in MiniWind that, on a schedule and manual dispatch, discovers the current Fio upstream default or approved release branch, proposes an updated submodule SHA, and tests the combined product. Run Fio core tests, MiniWind headless RPG tests, cross-repository boundary tests, startup/editor/play smoke tests where runners permit, and map/save/package compatibility checks.

Use PRs and required checks as the gate. Updates can auto-merge only if policy permits and all required checks pass; otherwise stay pinned to the previous commit and surface diagnostics. **Important:** a PR created by the default `GITHUB_TOKEN` may not trigger a second PR-check workflow. Use a suitable GitHub App/PAT identity or run required checks within the update workflow and verify branch protection before enabling auto-merge.

### Milestone 6 — Stable versioning, distribution and rollback

Publish MiniWind releases with the exact Fio SHA, game revision, plugin/API compatibility contract, and tested platforms. Keep a simple recovery procedure that restores the prior submodule commit and rebuilds. Consider a packaged/versioned Fio dependency only after import paths and asset/resource lookup make it safe.

## 6. Ownership rules and anti-leakage checks

| Concern | Correct owner |
| --- | --- |
| Renderer, RenderTable/EntityTable, generic entity I/O, project/load/save framework | **Fio** |
| General editor framework, extension registry, common tooling and generic plugin host | **Fio** |
| Generic player/game lifecycle, input and combat hooks | **Fio APIs** |
| RPG combat rules, magic classes, weapons, spells, damage balancing | **MiniWind/game** |
| Quests, factions, NPC motivations, dialogue, inventories, economy and emergent-world rules | **MiniWind/game** |
| Map assets, sound, authored world data, sprite heads and `.fiopak` game content | **MiniWind** |
| Game-specific menus, character sheets, RPG HUD/launcher implementation | **MiniWind**, through generic Fio hooks |
| Pinning Fio SHA and compatibility-test automation | **MiniWind CI** |

Add or preserve boundary tests ensuring that Fio production modules do not import MiniWind's `game` package; `vendor/fio` is not modified by a MiniWind build; and game code reaches Fio through approved public APIs. A test that only passes because both repos still contain separate `engine/` directories is not a useful migration test.

## 7. Instructions for coding agents

Before opening an implementation PR:

1. Read this document and inspect the **current** default branches of both repositories.
2. Run a current engine/editor/plugin divergence audit. Save a clear checklist, not just a percentage similarity summary.
3. State the milestone being implemented; keep changes within that milestone unless a dependency is necessary.
4. When changing Fio, submit generic mechanisms **to Fio**, not to MiniWind's copied engine. When changing game behaviour, implement it in `MiniWind/game/`.
5. Establish a baseline test result before changes, then run the smallest relevant tests throughout and the full available suite before completion.
6. For Milestone 1, land or propose the bootstrap **in Fio first**. Keep MiniWind playable on its existing integration while Fio's generic contract is established.
7. Record exact commits, tests run, skipped GUI/platform checks, known limitations, and rollback instructions in the PR.
8. Never claim “future Fio updates cannot break MiniWind”. The intended guarantee is *pinning + compatibility checks + controlled adoption*.

### Immediate next engineering action

**Open a Fio feature branch for Milestone 1: project-root-aware external-game bootstrapping.** Start with a small extraction of its existing `main.py` lifecycle and a test-only external fixture project. Prove standalone Fio and the fixture work before touching MiniWind's duplicated engine/editor. This planning document itself is kept in MiniWind to guide the downstream migration.

### Useful current entry points

- Fio `main.py` — source/compiled root selection, current `chdir`, archive setup, settings and QApplication lifecycle.
- Fio `editor/user_paths.py` — settings and writable fallback.
- Fio `editor/main_window.py` — root-dependent editor initialization.
- Fio `plugins/manager.py` — `register_builtin_game` game lifecycle.
- MiniWind `main.py` — existing `[Startup] game_module` bootstrap.
- MiniWind `game/__init__.py` — `install()` and game registration.
- MiniWind `game/fio.py` — compatibility adapter/private engine hooks.
- MiniWind `game/integration.py` — editor integration and monkeypatches.
- MiniWind `tests/integration/test_miniwind_boundaries.py` — current boundary invariants.

---

**North star:** update Fio independently; have MiniWind adopt *tested compatible* Fio versions as a dependency update — not as another hand-merged engine fork — while maintaining a clean boundary between generic engine technology and MiniWind's RPG world.
