# Arc Slicer 2.0

Arcaea 谱面切片工具。可将完整谱面按多个时间段导出为独立片段，支持任意正数倍率变速，并可按填写的元数据生成 songlist。

## 功能

- 拖拽谱面文件夹直接导入
- 自由添加多个切片时间段
- 支持任意正数倍率变速
- 自动切割 `.aff` 谱面和 `base.ogg` 音频
- 填写 Songlist 信息后，为每个片段生成 songlist，并在输出目录生成合并 songlist

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
    └── base.jpg   （可选）
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
    ├── songlist              -> 合并 songlist（填写 Songlist 信息时生成）
    └── songs/
        ├── your_song_id_0_30000/
        │   ├── 2.aff
        │   ├── base.ogg
        │   ├── base.jpg      （源文件存在时复制）
        │   └── songlist      （填写 Songlist 信息时生成）
        └── your_song_id_30000_60000/
            ├── 2.aff
            ├── base.ogg
            └── songlist      （填写 Songlist 信息时生成）
```

## Songlist 填写说明

展开界面中的 **Songlist** 面板，填写以下字段。面板未展开或字段无效时，不生成手填 songlist。

| 字段 | 说明 |
|------|------|
| Title Base | 曲目名称基础，片段会自动追加编号 |
| Artist | 曲师 |
| BPM | 显示 BPM 字符串，例如 `180` 或 `120-180` |
| BPM Base | 基准 BPM 数值，用于计算变速后的 `bpm_base` |
| Set | 曲包 ID，留空默认 `single` |
| Purchase | 购买字段，可留空 |
| Side | 0 = 光，1 = 对立，2 = 消色，3 = Lephon |
| BG | 背景 ID |
| Version | 游戏版本号，例如 `5.0` |
| Chart Designer | 谱师 |
| Jacket Designer | 封面画师 |
| Rating | 定数整数 |
| Rating+ | 勾选表示 `ratingPlus: true` |

当前难度固定为 FTR，即 `ratingClass = 2`。

## 当前架构

- 正式 UI 为 PyQt6 原生界面。
- 程序入口为 `app.py`。
- 当前运行路径不使用 WebView / pywebview。
- `ui.html` 不是当前运行入口。

## 注意事项

- 源码运行时，ffmpeg 需自行准备并放在项目根目录，或加入系统 `PATH`。
- `base.jpg` 为可选封面；当前导出逻辑仅在源文件存在时复制。
- 当前固定处理 `2.aff`，即 FTR 谱面。
- 非线性 Arc 在片段边界被截断时，界面会显示提示：边界坐标会按原缓动计算，但 Arc 片段内部轨迹可能与原谱存在轻微差异。
- 非零 AudioOffset、以及部分 Camera / Scenecontrol 持续时间在变速切片时，仍建议人工复核。
