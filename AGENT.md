# Arc Slicer Agent Handoff

Read this document before changing the project. It describes the `main` V2.3 baseline, not a future roadmap.

## Current Baseline

- Stable branch: `main`
- Stable version: V2.3
- V2.3 closing commit: `8316bba feat(v2.3): add timeline quick draft gesture`
- The local `v2.2.0-rc1` tag remains at the earlier V2.2 release candidate.

V2.2 is complete: AFF/audio slicing, `current_export` and `library_export`, songlist/packlist export, fixed pack sections, per-segment speed overrides, duplicate output-ID blocking, copy segment, and safe external shell merge. External merge uses an explicit plan and confirmation, backs up affected content, writes a manifest, attempts recovery on failure, and remembers a verified target `songs` directory.

V2.3 is complete: waveform data and caching; waveform, time ruler, and timeline lanes; blank-area drag creation; endpoint editing; draft preview; Ctrl+click quick drafts; selected/hovered card-timeline linkage; automatic/manual sorting; `uid` and `link_group_id` grouping with break/rejoin and cascaded endpoint edits; undo/redo; and Delete, Backspace, Ctrl+S, and Ctrl+D shortcuts.

`main` does not include audio audition. V2.4-A is developed only on `feature/v2.4-audio-audition`. Do not temporarily copy a second playback implementation into `main`; follow-up audition work belongs on that branch and in `arc_slicer/playback.py` once present there.

## Module Routing

- `app.py`: compatibility facade and startup entry. It re-exports legacy public names and injects dependencies; do not grow a second real main window here.
- `arc_slicer/ui/main_window.py`: real `MainWindow` and UI orchestration.
- `arc_slicer/ui/segment_row.py`: segment-card widgets and row behavior.
- `arc_slicer/ui/waveform_panel.py`: waveform/timeline painting and mouse interactions.
- `arc_slicer/ui/segment_history.py`: immutable snapshots and undo/redo commands.
- `arc_slicer/ui/metadata_panel.py`: songlist/packlist metadata UI.
- `arc_slicer/segments.py`: segment parsing, validation, IDs, speed tokens, and group helpers.
- `arc_slicer/waveform.py`: waveform data, cache, and decoding helpers.
- `arc_slicer/aff.py`: AFF slicing and warnings.
- `arc_slicer/audio.py`: ffmpeg/ffprobe helpers and audio slicing.
- `arc_slicer/exports.py`: current/library exports, songlist/packlist, and cover rendering.
- `arc_slicer/persistence.py`: config and runtime-data migration.
- `arc_slicer/workers.py`: Qt worker classes.
- `external_merge.py`: external target-shell merge engine with strict safety boundaries.

Never import `app` from inside `arc_slicer/`; pass compatibility dependencies through `MainWindowDependencies` instead.

## Segment And History Rules

Segment export IDs use:

```text
<source_song_id>_<start_ms>_<end_ms>_x<speed_token>
```

`speed_override = null` inherits the default speed. `uid` and `link_group_id` are UI-only fields and must never affect exported IDs.

All user-visible segment edits must use `MainWindow` history transactions. Do not push history from `textChanged` or timeline `mouseMove`; input edits and endpoint drags each commit one snapshot command. Loading, source switching, and snapshot restoration suspend/reset history as appropriate.

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

Outside an explicitly scoped task, do not add Combo snapping, multi-difficulty support, chart preview, a full DAW workflow, or a second playback engine.
