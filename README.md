# Arc Slicer 2.0

Arcaea 谱面切片工具。可将完整谱面按多个时间段导出为独立片段，支持任意正数倍率变速，并可按填写的元数据生成 songlist。

## 功能

- 拖拽谱面文件夹直接导入
- 自由添加多个切片时间段
- 支持任意正数倍率变速
- 自动切割 `.aff` 谱面和 `base.ogg` 音频
- 显式开启 Songlist 后，为每个片段生成合并 songlist
- 显式开启 Packlist 后，生成练习曲包、曲包封面与曲包资源
- 波形与时间线片段编辑：拖拽空白区创建、拖拽端点调整、草稿预览与 Ctrl+单击快速草稿
- 片段选择、自动/手动排序、级联链接组，以及撤销/重做快捷键

## 使用方法

### 直接使用

获取已打包的 `ArcSlicer.exe` 后，双击运行即可。

### 从源码运行

**环境要求**

- Python 3.10+
- PyQt6
- ffmpeg：放在项目根目录，或加入系统 `PATH`

安装依赖并启动：

```bash
python -m pip install PyQt6
python app.py
```

### 运行测试

```bash
python -m unittest discover -s tests -v
```

### 打包成 EXE

1. 安装构建依赖：

   ```bash
   python -m pip install PyInstaller
   ```

2. 将 `ffmpeg.exe` 放在项目根目录。
3. 运行：

   ```bat
   build.bat
   ```

生成的程序位于：

```text
dist\ArcSlicer.exe
```

打包后的 EXE 会携带构建时提供的 `ffmpeg.exe`。

## 谱面文件夹结构

输入的谱面文件夹需要包含：

```text
songs/
└── your_song_id/
    ├── 2.aff
    ├── base.ogg
    ├── 1080_base.jpg       （可选）
    ├── base.jpg            （可选）
    └── 1080_base_256.jpg   （可选）
```

## 输出结构

> 运行数据统一保存在 `ArcSlicerData/`：
>
> - 从源码运行时：项目根目录的 `ArcSlicerData/`
> - 从 `dist\ArcSlicer.exe` 运行时：`dist` 同级的 `ArcSlicerData/`
>
> 因此重新构建并清理 `dist/` 不会删除已保存的配置、歌曲链接或导出结果。
>
> 旧版本存放在项目根目录或 `dist/` 下的 `songs/`、`out/`、`config.json`、`slides.json` 会在首次启动时尝试迁移；旧文件不会被自动删除。

```text
ArcSlicerData/
├── config.json
├── slides.json
├── songs/
└── out/
    ├── current_export/
    │   └── songs/
    │       ├── songlist      （启用 Songlist 时）
    │       ├── packlist      （启用 Packlist 时）
    │       ├── pack/
    │       │   └── <pack_img>.png
    │       └── <segment_id>/
    │           ├── 2.aff
    │           ├── base.ogg
    │           ├── 1080_base.jpg
    │           ├── base.jpg
    │           └── 1080_base_256.jpg
    └── library_export/
        └── songs/
            ├── songlist
            ├── packlist
            ├── pack/
            └── <segment_id>/
```

`current_export` 每次导出安全重建，仅包含本次结果。`library_export` 是长期累计导出包：只有开启 Songlist 时才允许更新，按 `song.id` 合并歌曲，按 `pack.id` 合并曲包。它不是 Version 2.2 的“安全合并到外部目标壳 songs 根目录”功能。

## 外部目标壳合并

Version 2.2 已实现安全外部壳合并：选择外部目标壳的 `songs` 根目录后，先检查合并计划，再由用户明确确认执行。执行时会备份受影响内容、写入 manifest，并在失败时尝试恢复；已验证的目标目录会保存在配置中。

外部合并始终以 `current_export/songs/` 为本次输入，和长期累计的 `library_export` 保持独立。真实目标壳合并会写入用户选择的目录，应只在明确需要时执行。

## 波形选段与版本状态

`main` 当前稳定基线为 V2.3：已包含 `WaveformData` 与波形缓存、波形/时间标尺/timeline lanes、空白区拖拽建段、端点拖拽、草稿预览、Ctrl+单击快速草稿、卡片与时间线的 selected/hovered 联动、自动与手动排序、`uid`/`link_group_id` 级联编辑、撤销/重做，以及 Delete、Backspace、Ctrl+S、Ctrl+D 等快捷键。

音频试听不在 `main` 中。独立分支 `feature/v2.4-audio-audition` 正在开发 V2.4-A：可对当前选中的完整片段使用源 `base.ogg` 手动试听，支持播放/暂停/恢复、循环开关、空格快捷键、片段实际有效倍速、波形播放头，以及切换片段时停止旧播放；不会生成临时试听切片。

V2.4-B 已加入默认关闭的“自动试听”：当前选中片段的有效区间或继承的有效倍速在正式提交后，会以 200ms 防抖自动试听；输入和拖动过程中不会反复重启。手动播放优先并会取消等待中的自动试听。自动试听仍使用源 `base.ogg`，不会生成临时音频，也不影响导出、dirty 状态或撤销历史。

V2.4 尚待人工验收：连续切点修改的真实听感、倍速与循环边界听感、快速操作时是否意外出声，以及打包 EXE 的 OGG 自动试听。

## Songlist 填写说明

勾选 **生成 songlist** 后，可展开 Songlist 项填写以下字段。未勾选时只保存表单，不输出 songlist。

| 字段 | 说明 |
|------|------|
| Title Base | 曲目名称基础；默认展示标题会追加 `[起点–终点ms · 倍率×]` |
| Artist | 曲师 |
| BPM | 显示 BPM 字符串，例如 `180` 或 `120-180` |
| BPM Base | 基准 BPM 数值，用于计算变速后的 `bpm_base` |
| Set | 曲包 ID，留空默认 `single`；启用 Packlist 时会使用 `pack_id` |
| Purchase | 购买字段，可留空 |
| Side | 0 = 光，1 = 对立，2 = 消色，3 = Lephon |
| BG | 背景 ID |
| Version | 游戏版本号，例如 `5.0` |
| Chart Designer | 谱师 |
| Jacket Designer | 封面画师 |
| Rating | 定数整数 |
| Rating+ | 勾选表示 `ratingPlus: true` |

当前实际切片固定为 `2.aff` / FTR。为兼容目标壳，每个工具输出片段的 songlist `difficulties` 会统一写入 `ratingClass 0 / 1 / 2`：其中 0、1 的 `rating = -1`，2 使用当前填写的 FTR 实际定数。这只是无谱面难度占位，不表示已支持 PST / PRS 切片。

## Packlist 填写说明

Packlist 依赖 Songlist。Songlist 未勾选时，Packlist 项隐藏且不生效；重新勾选 Songlist 后，此前保存的 Packlist 偏好和字段会恢复。

启用 Packlist 后会生成：

```text
ArcSlicerData/out/<export_target>/songs/packlist
ArcSlicerData/out/<export_target>/songs/pack/<img>
```

曲包封面输出为 PNG，尺寸固定 `374×750`。自动生成时按以下顺序选择来源：

```text
1080_base.jpg → base.jpg → 1080_base_256.jpg
```

也可以选择用户上传的 PNG / JPG / JPEG 图片，工具会统一居中裁切为 `374×750` PNG。

## 片段校验

- 起点 / 终点必须为非负整数毫秒。
- 终点必须大于起点。
- 起点必须小于当前 OGG 时长，终点不得超过当前 OGG 时长。
- 音频时长读取成功时，界面显示 `音频时长` 与 `终点上限`。
- 终点超时时，界面提供显式的“设为上限”操作；工具不会在输入、切换歌曲、加载方案或导出时静默改写用户输入。

## 当前架构

- 正式 UI 为 PyQt6 原生界面。
- 程序入口为 `app.py`。
- 当前运行路径不使用 WebView / pywebview。
- `ui.html` 不是当前运行入口。

## 注意事项

- 源码运行时，ffmpeg 需自行准备并放在项目根目录，或加入系统 `PATH`。
- 歌曲曲绘按源文件存在情况迁移：`1080_base.jpg`、`base.jpg`、`1080_base_256.jpg`。
- 当前固定处理 `2.aff`，即 FTR 谱面。
- 非线性 Arc 在片段边界被截断时，界面会显示提示：边界坐标会按原缓动计算，但 Arc 片段内部轨迹可能与原谱存在轻微差异。
- 非零 AudioOffset、以及部分 Camera / Scenecontrol 持续时间在变速切片时，仍建议人工复核。
- 尚未实现多难度切片、官方曲包封面 / topbar 资源库、Combo snapping 与谱面预览。
- `main` 尚不包含音频试听；V2.4-A 的真实倍速、循环边界和 EXE OGG 播放仍待人工验收。
