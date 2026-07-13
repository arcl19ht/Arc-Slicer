# Arc Slicer Agent Handoff

Read this document before changing the project. V2.4-A and V2.4-B are merged into `main`; the UI clarity refresh has passed Windows source-environment visual acceptance.

## Current Baseline

- Stable branch: `main`
- Stable version: V2.3
- V2.3 closing commit: `8316bba feat(v2.3): add timeline quick draft gesture`
- Current feature branch: `feature/ui-clarity-refresh`
- Current task: V2.4-C Windows EXE/OGG stability acceptance.

V2.2 is complete: AFF/audio slicing, `current_export` and `library_export`, songlist/packlist export, fixed pack sections, per-segment speed overrides, duplicate output-ID blocking, copy segment, and safe external shell merge. External merge uses an explicit plan and confirmation, backs up affected content, writes a manifest, attempts recovery on failure, and remembers a verified target `songs` directory.

V2.3 is complete: waveform data and caching; waveform, time ruler, and timeline lanes; blank-area drag creation; endpoint editing; draft preview; Ctrl+click quick drafts; selected/hovered card-timeline linkage; automatic/manual sorting; `uid` and `link_group_id` grouping with break/rejoin and cascaded endpoint edits; undo/redo; and Delete, Backspace, Ctrl+S, and Ctrl+D shortcuts.

V2.4-A provides manual audition of a selected complete segment from source `base.ogg`. V2.4-B adds a default-off, non-persistent 200ms debounce. V2.4-C fixes explicit card/timeline selection so it refreshes the selected range and then schedules the same debounce; rapid selection leaves only the final segment pending. `textChanged` and timeline `mouseMove` do not schedule playback. Manual play/pause, input editing, and lifecycle changes cancel pending playback. Neither playback state nor the switch affects dirty state, history, or exports. EXE acceptance remains pending.

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

Next: V2.4-C Windows EXE/OGG stability. Windows source-environment UI acceptance is complete, but EXE validation remains pending. Outside an explicitly scoped task, do not add Combo snapping, multi-difficulty support, chart preview, a full DAW workflow, or a second playback engine.
