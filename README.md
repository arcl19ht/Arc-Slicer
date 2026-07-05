# Arc Slicer 2.0

Arc Slicer is a local PyQt6 desktop tool for slicing an Arcaea song chart into
smaller practice segments. Gate 0 currently focuses on FTR (`2.aff`) chart
slicing, audio slicing/speed changes, and basic songlist output.

## Runtime Requirements

- Python 3.10+
- PyQt6
- ffmpeg

For source runs, place `ffmpeg.exe` in the project root or make sure `ffmpeg`
is available from `PATH`.

## Run From Source

```powershell
python app.py
```

## Test

```powershell
python -m unittest discover -s tests -v
```

## Build

Install PyInstaller, place `ffmpeg.exe` in the project root, then run:

```powershell
.\build.bat
```

The build output is `dist\ArcSlicer.exe`.

## Current Architecture

- The formal UI is native PyQt6.
- The application entry point is `app.py`.
- WebView / pywebview is not part of the current runtime path.
- `ui.html` is not the current application entry point.

## Current Gate 0 Scope

- Songs listed in the UI must contain both `base.ogg` and `2.aff`.
- Chart slicing is currently fixed to FTR (`2.aff`).
- Speed must be a finite positive number.
- AFF event times are scaled by speed, and Timing BPM is scaled by speed.
- Nonlinear Arc boundary cuts are shown as a PyQt status indicator and info card.
- AudioOffset alignment and Camera/Scenecontrol duration scaling are not solved in
  Gate 0.

## Notes

Runtime outputs such as `out/`, `songs/`, `config.json`, and `slides.json` are
local data and are not part of the source baseline.
