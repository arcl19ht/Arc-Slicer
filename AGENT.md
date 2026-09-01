# Arc Slicer Agent Guide

Read this document before changing the project. Arc Slicer is a PyQt6 desktop tool that slices Arcaea AFF charts and OGG audio into independently exportable practice-song directories. `app.py` is the compatibility/startup entry, `arc_slicer/` contains the implementation, and JSON songlist/packlist plus AFF are the main external formats. V2.4 is the accepted stable product; V2.5-B has passed Windows source acceptance, and V2.5-C has passed disposable Windows NTFS shell compatibility acceptance. V2.5 EXE acceptance remains pending.

## Development Environment

- Supported Python: 3.10 or newer. On Windows prefer `.venv\Scripts\python.exe`; never reuse `.venv/bin/python`, `/private/tmp`, or a user-specific macOS path.
- The repository has no dependency manifest or lock file. PyQt6 is required at runtime; pytest is required for the pytest suite. Report a missing dependency and ask before installing or upgrading it.
- Standard Windows validation:
  - `.venv\Scripts\python.exe -m pytest -q tests/test_v22_external_merge_plan.py tests/test_v22_external_merge_execute.py tests/test_v22_external_merge_ui.py`
  - `.venv\Scripts\python.exe -m pytest -q`
  - `.venv\Scripts\python.exe -m compileall -q app.py external_merge.py arc_slicer`
  - `.venv\Scripts\python.exe -c "import app, external_merge, arc_slicer"`
  - `git diff --check`
- If the repository venv lacks pytest, do not install it silently. A separately discovered Python may be used only after recording its executable and imports. `python -m unittest discover -s tests -q` is not equivalent here: one real-Qt isolation test deliberately launches pytest in a subprocess.
- Never commit local songs, AFF/OGG/jacket assets, `ArcSlicerData/`, `out/`, build products, caches, external shells, or machine-specific paths.

## Dated Handoff Snapshot

This section is a 2026-09-01 snapshot, not a permanent invariant. Refresh it after later commits or validation.

- Branch: `feature/v2.5-multi-difficulty-export`. V2.5-C acceptance started at `034d280775cfa39f208c0db36e4f64a45d55dd80`; the documentation commit containing this snapshot is the current repository HEAD, so use `git rev-parse HEAD` for its exact SHA.
- Product-code baseline: `7ac8c127138ca862466dfd00cd8a2bf98be3e0ea` (`7ac8c12`).
- No product code or tests changed during V2.5-C acceptance. After the local evidence commit, the branch tracks `origin/feature/v2.5-multi-difficulty-export` at 2 ahead / 0 behind. Both `1a613b0` and product baseline `7ac8c12` are present on that remote branch.
- `main` and `origin/main` are at `9044148`; `main` is the product baseline's merge base, and that product baseline is 21 commits ahead, 0 behind `main`. Continue V2.5 work on the feature branch, not `main`.
- Worktree before V2.5-C contained only the pre-existing untracked `test_shell_songs/`. It was inspected read-only, remained unchanged by exact stat/metadata snapshots, and was not staged or committed. The writable acceptance copy and synthetic assets are retained under the user's TEMP directory and must not enter Git.
- Windows interpreters: repository venv Python 3.13.9 imports PyQt6 but lacks pytest. System Python 3.12.7 imports PyQt6 and pytest 9.0.3.
- 2026-09-01 system-Python pytest: external-merge focus `92 passed, 8 skipped, 21 subtests passed`; V2.5-related matrix `76 passed, 14 subtests passed`; full suite `437 passed, 15 skipped, 89 subtests passed`. All exited 0.
- System-Python compileall and `app`/`external_merge`/`arc_slicer` imports passed. Windows source acceptance also passed. Two real formal-export/formal-merge rounds against a disposable NTFS shell copy both completed with verified independent backups/manifests and no staging/swap residue: first add FTR/BYD with `3.ogg`, then same-ID update to FTR-only removed stale `3.aff`/`3.ogg`. The original shell template, packlist, and unrelated sentinel remained unchanged.
- This does not cover a V2.5 EXE, a real game directory, FAT/exFAT, network volumes, or broad third-party shell variants.
- Stable version: V2.4. V2.3 closed at `8316bba`; V2.4 merged at `d7bbaed` and closed in `9ff4f05`.

V2.2 is complete: AFF/audio slicing, `current_export` and `library_export`, songlist/packlist export, fixed pack sections, per-segment speed overrides, duplicate output-ID blocking, copy segment, and safe external shell merge. External merge uses an explicit plan and confirmation, backs up affected content, writes a manifest, attempts recovery on failure, and remembers a verified target `songs` directory.

V2.3 is complete: waveform data and caching; waveform, time ruler, and timeline lanes; blank-area drag creation; endpoint editing; draft preview; Ctrl+click quick drafts; selected/hovered card-timeline linkage; automatic/manual sorting; `uid` and `link_group_id` grouping with break/rejoin and cascaded endpoint edits; undo/redo; and Delete, Backspace, Ctrl+S, and Ctrl+D shortcuts.

V2.4-A provides manual audition of a selected complete segment from source `base.ogg`. V2.4-B adds a default-off, non-persistent 200ms debounce. V2.4-C makes explicit card/timeline selection refresh the selected range and schedule that debounce; rapid selection leaves only the final segment pending. A second click on an already selected timeline body seeks and plays from that point without changing its range, dirty state, or history. Dragging that selected body past the platform drag threshold translates its full interval, preserves its duration, and commits one history entry; linked members move together. Endpoint handles retain priority, and a first click on an unselected body only selects it. Looping always returns to the original segment start, never the last seek position. `textChanged` and timeline `mouseMove` do not schedule playback. Manual play/pause, input editing, drag start, and lifecycle changes cancel pending playback. Neither playback state nor the switch affects dirty state, history, or exports. V2.4 source and EXE acceptance are complete.

The UI clarity refresh corrected interactive control rendering without changing behavior: auto sort, loop, and auto audition use true switches; form and export choices use square checkboxes; primary enabled/disabled states are visually distinct. `arc_slicer.ui.styles` is the sole global QSS source; `app.QSS` and `main_window.QSS` remain compatibility aliases.

## Current Development Status

| Area | Status | Evidence and remaining boundary |
| --- | --- | --- |
| V2.2 export, current/library publication, songlist/packlist | Complete with automated coverage | Existing V2.1/V2.2 suites cover staging, replacement, rollback, metadata, covers, and fixed pack sections. |
| V2.3 waveform, selection, history, linking | Complete with automated coverage | Timeline/card selection, endpoint edits, group cascades, sorting, shortcuts, drafts, and undo/redo are covered. |
| V2.4 playback and timeline seek/translation | Complete and previously accepted on Windows source and EXE | Manual/automatic audition, debounce, loop, pause/resume, seek, translation, and runtime-only state have regression coverage. |
| V2.5 difficulty discovery and compatibility model | Complete with automated coverage | Readable regular `0.aff` through `4.aff` files define availability; any subset is valid. New songs select all; legacy slides prefer FTR when present; explicit empty/missing selections remain blocking states. |
| V2.5 dedicated audio | Complete with automated coverage | `base.ogg` is always exported once per segment. A usable selected `N.ogg` produces one additional audio operation and derived `audioOverride: true`; orphan/unusable audio is warned or rejected, never silently substituted. |
| V2.5 metadata and formal export | Complete with automated and Windows source acceptance | Per-song selection and per-difficulty metadata persist in slides; selected AFF/OGG files share one segment directory and one aggregated songlist entry. Optional distinct difficulty titles serialize as `title_localized`; `jacketOverride` is not implemented. |
| External merge canonical-root binding | Complete with automated coverage; committed and on origin | `1a613b0` fixes post-plan ancestor/root redirection. |
| External merge temporary/action identity binding | Complete with automated coverage and disposable Windows NTFS acceptance; committed and on origin | `7ac8c12` binds staging, backup, manifest, swaps, installed/action targets, exposes cleanup-incomplete/unverified-backup states, and fails closed if identity cannot be proved. FAT/exFAT and network volumes remain unverified. |
| V2.5-C compatibility and acceptance | Windows source and disposable NTFS shell phase complete; EXE pending | Formal exporter and merge add/update paths, reduced-difficulty cleanup, metadata replacement, sentinel isolation, backup/manifest, and residue cleanup passed. Real game directories and broad third-party shells were not used. |
| Combo snapping | Cancelled | Do not revive combo parsing, endpoint snapping, UI, or configuration without a new explicit requirement. |
| Chart preview, official pack/topbar library, second player, DAW workflow | Out of scope / future candidates | They are not part of V2.5-B/C. |

`README.md`, `docs/status/current-development-status.md`, and `docs/plans/v2.5-multi-difficulty-slicing.md` were synchronized with this acceptance snapshot. Historical requirements and travel handoffs may still describe earlier planning states and are not current completion evidence.

## Module Routing

- `app.py`: compatibility facade and startup entry. It re-exports legacy public names and injects dependencies; do not grow a second real main window here.
- `arc_slicer/ui/main_window.py`: real `MainWindow` and UI orchestration.
- `arc_slicer/ui/segment_row.py`: segment-card widgets and row behavior.
- `arc_slicer/ui/waveform_panel.py`: waveform/timeline painting, mouse interactions, and playhead display only.
- `arc_slicer/ui/segment_history.py`: immutable snapshots and undo/redo commands.
- `arc_slicer/ui/metadata_panel.py`: songlist/packlist metadata UI.
- `arc_slicer/playback.py`: the only audition controller. It must not import `app` or UI classes.
- `arc_slicer/segments.py`: segment parsing, validation, IDs, speed tokens, and group helpers.
- `arc_slicer/difficulties.py`: canonical 0–4 definitions, directory discovery, selection migration/validation, dedicated-audio discovery, and per-difficulty metadata serialization.
- `arc_slicer/waveform.py`: waveform data, cache, and decoding helpers.
- `arc_slicer/aff.py`: AFF slicing and warnings.
- `arc_slicer/audio.py`: ffmpeg/ffprobe helpers and audio slicing.
- `arc_slicer/exports.py`: segment and multi-difficulty operation plans, pre-staging duration validation, AFF/OGG execution, current/library publication, songlist/packlist, and cover rendering.
- `arc_slicer/persistence.py`: config and runtime-data migration.
- `arc_slicer/workers.py`: Qt worker classes.
- `external_merge.py`: external target-shell merge engine with strict safety boundaries.
- `tests/`: unittest-style tests collected by pytest. V2.1 covers export/metadata, V2.2 external merge, V2.3 waveform/history/selection, V2.4 playback/timeline interaction, and V2.5 difficulty/UI/export/lifecycle boundaries.
- `build.spec` and `build.bat`: Windows PyInstaller entry. Building is an explicit task only; `build.bat` may install dependencies and delete build outputs, so never run it during ordinary validation.

Never import `app` from inside `arc_slicer/`; pass compatibility dependencies through `MainWindowDependencies` instead.

## Segment, History, And Playback Rules

Segment export IDs use:

```text
<source_song_id>_<start_ms>_<end_ms>_x<speed_token>
```

`speed_override = null` inherits the default speed. `uid` and `link_group_id` are UI-only fields and must never affect exported IDs.

All user-visible segment edits must use `MainWindow` history transactions. Do not push history from `textChanged` or timeline `mouseMove`; input edits and endpoint drags each commit one snapshot command. Loading, source switching, and snapshot restoration suspend/reset history as appropriate.

Delete and Backspace operate on `selected_segment_uid`, not visual row position, hover, or a stale index. Selection-only, hover, seek, playback, loop, and preview-source changes are runtime state: they must not create history entries, persist into slides unless explicitly documented, or mark `current_export` dirty. Export-affecting changes must mark it dirty and invalidate any checked `ExternalMergePlan`; a plan is never reusable after its inputs, target snapshot, or bound identities change.

Playback state, position, loop state, automatic-audition switch, and pending timer are runtime-only. They must not enter undo history or mark exports dirty. `AudioPlaybackController` owns separate boundary and automatic-audition timers; do not add a second player, use ffmpeg temporary audition clips, or repeatedly restart playback from drag `mouseMove`. MainWindow coordinates selection/source/UI; WaveformPanel only draws the playhead.

## Safety And Scope

Do not change external merge, backup/manifest handling, `current_export` safety, or `library_export` behavior unless the task explicitly requires it. Never run a real external merge without explicit user instruction.

External merge must bind and revalidate canonical roots, owned temporary objects (staging, backup, swap), and every destructive action target immediately before destructive work. Missing, replaced, linked, or identity-unavailable objects fail closed; do not weaken this invariant for a platform-specific temporary-path workaround.

`affintro.md` is a local AFF reference. Do not modify it unless explicitly asked; its absence in a clean clone must not block work.

Never modify, delete, stage, or commit these paths unless explicitly asked:

- `affintro.md`
- `test_shell_songs/`
- `ArcSlicerData/`
- `out/`
- `build/`
- `dist/`

Do not run `build.bat` or PyInstaller unless explicitly requested. Stage files explicitly; never use `git add .` or `git add -A`. Do not push by default.

## UI And Product Boundaries

Prefer restrained, low-noise PyQt UI with stable layouts and minimal configuration. Keep selection, endpoint dragging, resize grips, and waveform/timeline division consistent with existing behavior.

The V2.3 plan is historical. Use `README.md` and `docs/status/current-development-status.md` for current product status. Work beyond V2.3 must state clearly whether it is implemented, in development, awaiting manual acceptance, or not implemented.

V2.5-B wires the same model into the main window and formal exporter: only discovered standard AFF files are selectable; selection and per-difficulty metadata are song-level slides state; an empty or missing saved selection blocks export, and a visible action can remove only unavailable saved selections while preserving metadata. A header-only but legal AFF, including `AudioOffset:-30\n-\n`, remains selectable and exportable. A preview source selector is runtime-only and can choose `base.ogg` or a usable `N.ogg`; canonical segment bounds remain based on `base.ogg`, while playback uses a separately probed preview duration. Waveform workers must remain strongly referenced until `QThread.finished`; `done_signal` only delivers a result. Formal export validates each used source audio once before staging, then creates one directory per segment, slices `base.ogg` once, then selected override audio and selected charts, and writes one aggregated songlist entry. Current/library replacement and external-merge safety keep treating that directory as one song ID. The compatibility facade uses explicit slot signatures; its subprocess regression includes the external-merge target chooser cancel click without contaminating Gate0's fake Qt process. Windows source/UI acceptance and the disposable NTFS shell add/update matrix are complete. `jacketOverride`, combo snapping, chart preview, a second playback engine, and DAW-style workflows remain out of scope.

## Recommended Next Work

1. **Windows V2.5 EXE build and acceptance.** As a separately authorized task, build from the accepted source baseline and verify multi-difficulty discovery/metadata, `base.ogg`/`N.ogg` playback, add/update exports, and the external-target chooser. Record the artifact hash. Do not reuse the V2.4 EXE evidence.
2. **Optional real-game-shell acceptance.** Only with explicit authorization and a recoverable disposable target, repeat the checked-plan/confirm/backup/manifest workflow. The NTFS test-shell result does not authorize writes to a real game directory.
3. **Filesystem compatibility decisions.** FAT/exFAT and network volumes currently fail closed when stable identity is unavailable. Test them only as an explicit safety task; do not add an inode/stat bypass.
4. **Release documentation.** After EXE acceptance, decide whether V2.5 is ready to close and then update version/release wording and the dated snapshot together.

## Standard Working Flow

1. Before editing, run `git rev-parse --show-toplevel`, `git branch --show-current`, `git status --branch --short`, `git branch -vv`, and fetch when remote accuracy matters. Preserve all pre-existing changes and untracked user data.
2. Read the relevant module, tests, current status, and recent commits. Prefer a small, explicit patch; do not change `main`, external data, or unrelated files.
3. Run the narrowest relevant pytest modules first, then the full pytest suite, compileall, imports, and `git diff --check`. Record the interpreter, command, exit code, pass/skip/subtest counts, and first meaningful error. Never add skips, xfails, or test changes merely to obtain green output.
4. Inspect `git diff -- <explicit files>` and `git status --short`. Stage only named files with `git add <path>`; never use `git add .` or `git add -A`.
5. After an authorized commit, run `git status --short`, `git log -1 --oneline --decorate`, and `git show --check --stat HEAD`. Never push, merge, rebase, reset, amend, force-push, build an EXE, or run a real external merge without explicit user authorization.
