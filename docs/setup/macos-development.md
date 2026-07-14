# macOS 开发环境

本项目的正式界面是 PyQt6 原生桌面程序，入口为 `app.py`。本说明只覆盖源码开发与测试，不覆盖 Windows EXE 构建。

## 系统要求

- macOS 上可用的 Git。
- Python 3.10 或更高版本。
- 系统 `PATH` 中可调用的 `ffmpeg` 和 `ffprobe`。Arc Slicer 会先查找同目录的 Windows `ffmpeg.exe`，macOS 源码环境应使用 PATH 中的工具。
- PyQt6；测试还需要 pytest。仓库当前没有 `requirements.txt`、`pyproject.toml` 或 lock 文件。

可使用 [Homebrew](https://brew.sh/) 安装系统工具。请以 Homebrew 的官方安装说明为准；安装后确认 `git`、`python3`、`ffmpeg` 与 `ffprobe` 可在终端执行。

## 获取代码

```bash
git clone https://github.com/arcl19ht/Arc-Slicer.git
cd Arc-Slicer
git switch feature/v2.5-multi-difficulty-export
git pull --ff-only origin feature/v2.5-multi-difficulty-export
git rev-parse HEAD
git status --short
```

## Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install PyQt6 pytest
```

若需要构建平台对应的应用，再按当时的构建任务单独安装 PyInstaller；不要把 Windows 的 `build.bat` 当作 macOS 构建方式。

## 验证与启动

```bash
python -m pytest -q
python -m compileall -q app.py external_merge.py arc_slicer
python app.py
```

macOS 没有 Windows 的 `CREATE_NO_WINDOW` 行为，也不使用 `ffmpeg.exe` 或 `ArcSlicer.exe`。源码运行时，`ffmpeg`/`ffprobe` 必须由 PATH 提供。真实歌曲、运行数据和导出结果不随仓库同步；请在应用中重新选择自己的本地歌曲目录，且不要提交这些资产。

## 当前交接状态

V2.5-B 仍在人工验收阶段。开始新功能前，请阅读 [旅行交接](../status/travel-handoff-2026-07-14.md)、`AGENT.md` 和 [当前开发状态](../status/current-development-status.md)，先完成其中列出的真实歌曲与 Windows 验收缺口。
