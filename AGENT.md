# Arc Slicer Agent Handoff

Read this document before changing the project. V2.4 is complete and has passed Windows source-environment and final EXE acceptance.

## Current Baseline

- Stable branch: `main`
- Stable version: V2.4
- V2.3 closing commit: `8316bba feat(v2.3): add timeline quick draft gesture`
- Main stable baseline: `d7bbaed` (V2.4 PR #4 merge)
- V2.4 closing documentation: `9ff4f05 docs: close v2.4 and plan multi-difficulty slicing`
- Current feature branch: `feature/v2.5-multi-difficulty-export`
- Current task: V2.5-B multi-difficulty export manual acceptance preparation. Travel handoff: `docs/status/travel-handoff-2026-07-14.md`.

V2.2 is complete: AFF/audio slicing, `current_export` and `library_export`, songlist/packlist export, fixed pack sections, per-segment speed overrides, duplicate output-ID blocking, copy segment, and safe external shell merge. External merge uses an explicit plan and confirmation, backs up affected content, writes a manifest, attempts recovery on failure, and remembers a verified target `songs` directory.

V2.3 is complete: waveform data and caching; waveform, time ruler, and timeline lanes; blank-area drag creation; endpoint editing; draft preview; Ctrl+click quick drafts; selected/hovered card-timeline linkage; automatic/manual sorting; `uid` and `link_group_id` grouping with break/rejoin and cascaded endpoint edits; undo/redo; and Delete, Backspace, Ctrl+S, and Ctrl+D shortcuts.

V2.4-A provides manual audition of a selected complete segment from source `base.ogg`. V2.4-B adds a default-off, non-persistent 200ms debounce. V2.4-C makes explicit card/timeline selection refresh the selected range and schedule that debounce; rapid selection leaves only the final segment pending. A second click on an already selected timeline body seeks and plays from that point without changing its range, dirty state, or history. Dragging that selected body past the platform drag threshold translates its full interval, preserves its duration, and commits one history entry; linked members move together. Endpoint handles retain priority, and a first click on an unselected body only selects it. Looping always returns to the original segment start, never the last seek position. `textChanged` and timeline `mouseMove` do not schedule playback. Manual play/pause, input editing, drag start, and lifecycle changes cancel pending playback. Neither playback state nor the switch affects dirty state, history, or exports. V2.4 source and EXE acceptance are complete.

The UI clarity refresh corrected interactive control rendering without changing behavior: auto sort, loop, and auto audition use true switches; form and export choices use square checkboxes; primary enabled/disabled states are visually distinct. `arc_slicer.ui.styles` is the sole global QSS source; `app.QSS` and `main_window.QSS` remain compatibility aliases.

## Module Routing

- `app.py`: compatibility facade and startup entry. It re-exports legacy public names and injects dependencies; do not grow a second real main window here.
- `arc_slicer/ui/main_window.py`: real `MainWindow` and UI orchestration.
- `arc_slicer/ui/segment_row.py`: segment-card widgets and row behavior.
- `arc_slicer/ui/waveform_panel.py`: waveform/timeline painting, mouse interactions, and playhead display only.
- `arc_slicer/ui/segment_history.py`: immutable snapshots and undo/redo commands.
- `arc_slicer/ui/metadata_panel.py`: songlist/packlist metadata UI.
- `arc_slicer/playback.py`: the only audition controller. It must not import `app` or UI classes.
- `arc_slicer/segments.py`: segment parsing, validation, IDs, speed tokens, and group helpers.
- `arc_slicer/waveform.py`: waveform data, cache, and decoding helpers.
- `arc_slicer/aff.py`: AFF slicing and warnings.
- `arc_slicer/audio.py`: ffmpeg/ffprobe helpers and audio slicing.
- `arc_slicer/exports.py`: current/library exports, songlist/packlist, and cover rendering.
- `arc_slicer/persistence.py`: config and runtime-data migration.
- `arc_slicer/workers.py`: Qt worker classes.
- `external_merge.py`: external target-shell merge engine with strict safety boundaries.

Never import `app` from inside `arc_slicer/`; pass compatibility dependencies through `MainWindowDependencies` instead.

## Segment, History, And Playback Rules

Segment export IDs use:

```text
<source_song_id>_<start_ms>_<end_ms>_x<speed_token>
```

`speed_override = null` inherits the default speed. `uid` and `link_group_id` are UI-only fields and must never affect exported IDs.

All user-visible segment edits must use `MainWindow` history transactions. Do not push history from `textChanged` or timeline `mouseMove`; input edits and endpoint drags each commit one snapshot command. Loading, source switching, and snapshot restoration suspend/reset history as appropriate.

Playback state, position, loop state, automatic-audition switch, and pending timer are runtime-only. They must not enter undo history or mark exports dirty. `AudioPlaybackController` owns separate boundary and automatic-audition timers; do not add a second player, use ffmpeg temporary audition clips, or repeatedly restart playback from drag `mouseMove`. MainWindow coordinates selection/source/UI; WaveformPanel only draws the playhead.

## Safety And Scope

Do not change external merge, backup/manifest handling, `current_export` safety, or `library_export` behavior unless the task explicitly requires it. Never run a real external merge without explicit user instruction.

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

V2.5-B wires the same model into the main window and formal exporter: only discovered standard AFF files are selectable; selection and per-difficulty metadata are song-level slides state; an empty or missing saved selection blocks export, and a visible action can remove only unavailable saved selections while preserving metadata. A header-only but legal AFF, including `AudioOffset:-30\n-\n`, remains selectable and exportable. A preview source selector is runtime-only and can choose `base.ogg` or a usable `N.ogg`; canonical segment bounds remain based on `base.ogg`, while playback uses a separately probed preview duration. Waveform workers must remain strongly referenced until `QThread.finished`; `done_signal` only delivers a result. Formal export validates each used source audio once before staging, then creates one directory per segment, slices `base.ogg` once, then selected override audio and selected charts, and writes one aggregated songlist entry. Current/library replacement and external-merge safety keep treating that directory as one song ID. The compatibility facade now uses explicit slot signatures; its subprocess regression includes the external-merge target chooser cancel click without contaminating Gate0's fake Qt process. Manual source/UI and real-song acceptance, including a Windows recheck of that chooser, are still required; do not claim V2.5-B is accepted merely because automated tests pass. `jacketOverride`, combo snapping, chart preview, a second playback engine, and DAW-style workflows remain out of scope.
