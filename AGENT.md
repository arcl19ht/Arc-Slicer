# Arc Slicer Agent Handoff

This file is for a new coding agent that has not seen the prior conversation. Read this before changing code.

## 1. Project overview

Arc Slicer is a PyQt6 desktop tool for slicing Arcaea song folders into practice clips.

Main runtime entry/facade:

- `app.py`

Real PyQt main-window implementation:

- `arc_slicer/ui/main_window.py`

`app.py` intentionally remains as the compatibility facade and startup entry:

- re-exports legacy public names used by tests and older scripts
- provides `main()` / `if __name__ == "__main__"`
- keeps `app.MainWindow` as a thin subclass that injects facade dependencies
- should not grow a second real `MainWindow` implementation

External shell merge engine:

- `external_merge.py`

The current runtime UI is pure PyQt6. `ui.html` is obsolete reference and must not be modified.

The project currently focuses on:

- slicing `base.ogg` and `2.aff`
- generating practice clips
- generating `songlist` / `packlist`
- exporting to `current_export`
- optionally merging `current_export/songs` into an external target shell `songs` directory
- V2.3 waveform-based segment editing

## 2. Current known release state

`main` has local tag:

- `v2.2.0-rc1`
- commit: `f99d52a`

V2.2 includes:

- AFF/audio slicing
- `current_export` and `library_export`
- `songlist` / `packlist` export
- external target shell merge
- merge plan confirmation
- backup / manifest
- external merge target directory memory
- per-segment speed override
- duplicate segment ID blocking
- copy segment
- pack section selector

V2.3 work is on:

- `feature/v2.3-waveform-selection`

Do not assume the exact latest V2.3 commit hash. Inspect the actual cloned repository with:

```powershell
git log --oneline --decorate --max-count 20
```

Known V2.3 completed or in progress:

- `WaveformData`
- waveform cache
- split waveform area and timeline lanes
- waveform drag selection / endpoint editing
- draft segment preview
- segment uid, selected / hovered linkage
- auto sorting and visual groups
- explicit `link_group_id` cascade groups with break / rejoin UX
- modularization into `arc_slicer/` core, UI component, export, persistence, worker, and main-window modules

Before coding, inspect current implementation and tests.

## 2.1 Module routing

Use these modules as the current source of truth:

- `app.py`: compatibility facade, re-exports, startup only
- `arc_slicer/ui/main_window.py`: real `MainWindow`, high-level UI orchestration
- `arc_slicer/ui/segment_row.py`: segment card widgets and row-level UI behavior
- `arc_slicer/ui/waveform_panel.py`: waveform/timeline painting and interactions
- `arc_slicer/playback.py`: selected-segment audition controller; never imports `app` or UI classes
- `arc_slicer/ui/segment_history.py`: immutable segment snapshots and undo/redo commands
- `arc_slicer/ui/metadata_panel.py`: songlist / packlist metadata UI
- `arc_slicer/segments.py`: segment parsing, validation, ids, speed tokens, group helpers
- `arc_slicer/waveform.py`: waveform data, cache, decoding helpers
- `arc_slicer/aff.py`: AFF slicing / warning helpers
- `arc_slicer/audio.py`: ffmpeg / ffprobe and audio slicing helpers
- `arc_slicer/exports.py`: current/library export, songlist/packlist, cover rendering helpers
- `arc_slicer/persistence.py`: config and runtime data migration
- `arc_slicer/workers.py`: Qt worker classes

Do not import `app` from inside `arc_slicer/`. If compatibility behavior is needed, pass dependencies from `app.py` into `MainWindowDependencies`.

Segment edits must enter history through `MainWindow` transactions. Do not push history from
`textChanged` or timeline `mouseMove`; input and endpoint drags each commit one snapshot command.
Loading, source switching, and snapshot restoration suspend and reset segment history.
Playback state, position, and loop state are runtime-only: they do not enter segment history or
mark the current export dirty. Extend audition behavior in `playback.py`, with main-window
selection coordination and waveform-panel playhead drawing kept separate.

## 3. Important project rules

### 3.1 Slicing and segment IDs

Segment ID format:

```text
<source_song_id>_<start_ms>_<end_ms>_x<speed_token>
```

Example:

```text
song_120000_140000_x0p75
```

`speed_override = null` means inherit default speed.

Effective segment speed is:

```text
speed_override or default_speed
```

Duplicate output ID must be blocked before staging, ffmpeg, or writing files.

### 3.2 Segment data

Each segment may have:

```json
{
  "s": 120000,
  "e": 140000,
  "speed_override": null
}
```

or:

```json
{
  "s": 120000,
  "e": 140000,
  "speed_override": 0.75
}
```

Old data without `speed_override` is treated as `null`.

V2.3 stores UI-only fields such as `uid` and `link_group_id` for selection, sorting, and cascade editing. They must not change the exported song id or `build_segment_id` output.

### 3.3 External merge

Do not change external merge logic unless explicitly asked.

Do not modify these areas unless the task explicitly says so:

- `external_merge.py`
- external merge plan / execute logic
- backup / manifest behavior
- `current_export` safety logic
- `library_export` logic

### 3.4 Packlist

Pack section is selectable from fixed options. Do not restore the old hardcoded-only behavior unless explicitly requested.

### 3.5 AFF reference

`affintro.md` is an AFF chart format reference. It can be useful for AFF parsing or slicing tasks.

Rules:

- If `affintro.md` exists locally, treat it as reference material.
- Do not modify it unless explicitly asked.
- If it is not present in a fresh clone, do not block UI or waveform work.
- For AFF behavior changes, ask the user whether to provide or commit a reference copy.

## 4. Files and paths that must not be touched

Never modify, delete, stage, or commit unless explicitly asked:

- `affintro.md`
- `test_shell_songs/`
- `ArcSlicerData/`
- `out/`
- `build/`
- `dist/`

Also do not run real external merge unless explicitly requested.

Do not run PyInstaller or `build.bat` unless explicitly requested.

Never use:

```powershell
git add .
git add -A
```

Only stage exact modified files.

## 5. User preferences

The user prefers:

- restrained, elegant UI
- low visual noise
- low friction
- minimal configuration
- no fake-looking static labels that resemble input boxes
- no sudden layout jumps while typing
- keyboard-friendly workflows
- workflows that avoid constantly switching between mouse and keyboard

Be direct. Do not overbuild. Split risky work into small commits.

## 6. Required working style for a new agent

Before making changes:

```powershell
git branch --show-current
git status --short
git log --oneline --decorate --max-count 15
python -m unittest discover -s tests -v
python -m py_compile app.py external_merge.py
git diff --check
```

Then read relevant code and tests. Only after that implement the requested task.

If the working tree has unexpected tracked modifications or unexpected untracked files, stop and report.

Allowed local untracked items are usually:

```text
?? affintro.md
?? test_shell_songs/
```

but always verify with the user if unsure.

## 7. V2.3 design direction

Waveform must not be treated as a passive display. It should become a timeline-based segment editor.

The waveform area should participate in:

- locating time
- selecting segments
- creating segments
- editing segment boundaries
- showing draft segments
- showing segment grouping
- later managing cascade-linked practice variants

The card area should become the precise editing and properties area.

The shared model should be:

```text
segment cards = structured property editors
waveform timeline = primary time selection canvas
both edit the same segment data
```

## 8. V2.3 current problem summary

Current or recently observed problems:

- start/end validation may appear too early while the user is still typing
- pressing Enter does not naturally move to the next empty field
- incomplete segments are treated as errors instead of drafts
- typing only a start time does not give a helpful waveform preview
- waveform overlays do not clearly separate multiple same-time segments
- waveform and cards need hover/click selection linkage
- future cascade UI should not be messy connector lines

## 9. V2.3 implementation roadmap

### V2.3.3: input experience and draft segment model

Implement:

1. delayed validation
2. Enter navigation to next empty field
3. waveform hover time cursor
4. incomplete segment draft visualization
5. draft anchor behavior

Do not implement link groups yet.

#### 9.1 Delayed validation

While the user is actively typing:

- do not immediately show red errors like `终点不能为空`
- do not immediately show red errors like `起点不能为空`
- update neutral preview only

Show hard validation only when:

- input loses focus
- user presses Enter
- user clicks away
- user runs slicing

Before slicing, all fields must still be strictly validated.

Conceptual split:

```text
soft validation:
  during active editing; update preview, no red error

hard validation:
  editingFinished / Enter / click away / run slicing; show blocking errors
```

#### 9.2 Enter navigation

Expected behavior:

- start field Enter:
  - if end is empty, focus end
  - otherwise focus next useful empty field
- end field Enter:
  - move to speed field or next segment start
- speed field Enter:
  - move to next segment's first empty field
- Ctrl+Enter may later run slicing, but is not required immediately

Avoid forcing the user to switch constantly between mouse and keyboard.

#### 9.3 Draft segments

A segment can be:

- complete:
  - start exists
  - end exists
  - start < end
- start draft:
  - start exists
  - end empty
- end draft:
  - start empty
  - end exists
- empty draft:
  - both empty

Drafts should not be treated as red errors while editing.

Waveform visualization:

- start draft:
  - show vertical start anchor
  - show faint arrow or dashed guide to the right
- end draft:
  - show vertical end anchor
  - show faint arrow or dashed guide to the left
- empty draft:
  - no strong waveform element

Drafts become hard errors only on commit/export if incomplete.

#### 9.4 Waveform cursor

When hovering waveform:

- show a thin vertical time line
- show current time in `m:ss.mmm` or ms
- do not mutate data

Click behavior should not accidentally create data unless the user is clearly in creation mode.

Possible future behavior:

- Ctrl+Click creates a draft anchor
- Ctrl+Drag creates a complete segment preview
- plain drag on empty area creates a complete segment

### V2.3.4: selection, hover, sorting, and visual grouping

Implement later:

1. `selected_segment_id`
2. `hovered_segment_id`
3. card hover/click linked to waveform clip hover/click
4. automatic sorting
5. visual segment group cards / group lanes

#### 9.5 Selection and hover

Rules:

- hover card:
  - waveform clip lightly highlights
- click card:
  - segment becomes selected
  - waveform clip strongly highlights
- hover waveform clip:
  - card lightly highlights
- click waveform clip:
  - segment becomes selected
  - card scrolls into view and highlights
- click empty waveform area:
  - clear selected

`hovered` is temporary. `selected` is persistent.

#### 9.6 Sorting

Default:

- auto sort enabled
- sort mode: time-first

Sort modes:

1. time-first:
   - group_start
   - group_end
   - group_min_effective_speed
   - created_order

2. speed-first:
   - group_min_effective_speed
   - group_start
   - group_end
   - created_order

3. manual:
   - no auto reordering
   - copy inserts after original
   - new segment appends to end

Do not reorder on every keystroke.

Sort only on:

- add segment
- copy segment
- delete segment
- waveform endpoint drag release
- editingFinished
- default speed editingFinished
- before slicing

Card order, waveform lane order, and songlist export order should match.

#### 9.7 Visual grouping

Use group cards, not messy connector lines.

Visual style:

- subtle background
- thin border
- same color for same group
- group title like:
  `片段组 120000-140000 · 3 个速度`
- group members remain individually editable

Visual grouping may initially be based on identical start/end. Later it should use explicit `link_group_id`.

### V2.3.5: explicit cascade link groups

Implement later:

- segment `uid`
- `link_group_id`
- copy segment auto creates or joins a group
- endpoint drag cascades only within same `link_group_id`
- chain icon breaks link
- open-lock icon rejoins compatible group
- hover preview shows possible rejoin

Important distinction:

```text
same start/end does not necessarily mean linked
linked means same link_group_id
```

#### 9.8 Link rules

Copy segment:

- if original has group, new segment joins it
- if original has no group, create group for original and copy

Break link:

- current segment gets `link_group_id = null`
- moves out of group
- start/end/speed unchanged

Rejoin:

- only possible if start/end matches an existing group
- hover previews possible group
- click open-lock actually rejoins

## 10. What not to do yet

Do not implement unless explicitly requested:

- playback
- loop audition
- note snapping
- combo snapping
- chart preview
- full DAW-style editing
- external merge changes
- build / release changes

## 11. First prompt for a new agent

Use this as the first message after cloning. The agent should only audit, not modify files.

```text
You are taking over the Arc Slicer project. Do not modify files yet.

Please complete a context audit:

1. Confirm current branch, HEAD, and working tree state.
2. Read AGENTS.md.
3. Read docs/plans/v2.3-timeline-interaction.md if it exists.
4. Read these areas in the current modules:
   - SegmentRow
   - WaveformData
   - WaveformPanel
   - MainWindow segment / waveform related methods in `arc_slicer/ui/main_window.py`
   - do_slice
   - build_segment_export_plan
5. Read these tests if present:
   - tests/test_waveform.py
   - tests/test_waveform_ui.py
   - tests/test_waveform_interaction.py
   - tests/test_segment_speed.py
   - tests/test_segment_row_ui.py
6. Run:
   python -m unittest discover -s tests -v
   python -m py_compile app.py external_merge.py
   git diff --check

Then output an audit report only. Do not modify files.

The report must include:

- current branch and HEAD
- V2.2 completed capabilities
- V2.3 completed capabilities
- what WaveformPanel interaction already supports
- current SegmentRow input / validation behavior
- whether drag selection and endpoint dragging already exist
- whether selected / hovered / auto sort / draft segment already exist
- the smallest safe next step for V2.3.3
- test results
- git status --short
```

## 12. Suggested first development task after audit

Use this only after the audit report confirms the current code state.

```text
Current task: implement V2.3.3 first step: input experience and draft segment foundation.

Goals:

1. Delayed start/end empty-field errors:
   - while the user is actively typing, do not immediately show red errors like "终点不能为空" or "起点不能为空"
   - show hard validation only on editingFinished / Enter / click away / run slicing
   - before slicing, still strictly block incomplete segments

2. Enter jumps to the next empty input:
   - start Enter: if end is empty, focus end
   - end Enter: move to speed or next segment start
   - speed Enter: move to the next segment's first empty field
   - no complex shortcut system required

3. Waveform hover time cursor:
   - hovering waveform shows a thin vertical line
   - shows current time
   - does not modify data

4. Incomplete segment neutral preview:
   - only start: waveform shows start anchor plus rightward dashed/arrow guide
   - only end: waveform shows end anchor plus leftward dashed/arrow guide
   - this is draft preview, not a complete valid segment

Limits:

- do not implement selected / hovered segment linkage
- do not implement auto sort
- do not implement visual group cards
- do not implement link_group_id
- do not implement cascade
- do not implement playback, loop audition, note snapping, or chart preview
- do not modify external_merge.py

Modify the minimum necessary files and add tests.

Required validation:

python -m unittest tests.test_waveform tests.test_waveform_ui tests.test_segment_row_ui -v
python -m unittest discover -s tests -v
python -m py_compile app.py external_merge.py
git diff --check

Commit message:

feat(v2.3): improve segment draft editing
```

## 13. If `affintro.md` is needed

If the next task involves AFF syntax or slicing semantics, ask the user to provide `affintro.md` or commit a sanitized reference copy.

For V2.3 input, UI, waveform, sorting, grouping, or draft segment work, `affintro.md` is not required.
