# Arc Slicer 项目需求书

> 文档状态：设计基线（修订 1.4，替代 1.3）
> 项目名称：Arc Slicer
> 当前阶段：Gate 0 已正式关闭；运行数据目录稳定化已完成。当前主线为 Version 2.1「导出元数据、练习曲包与双层输出工作流」。
> 已锁定基线：
> - `c0f5d80 feat(gate0): complete stable PyQt slicing baseline`
> - `b6b1770 feat(runtime): stabilize persistent data directory`
>
> 更新原则：
> - 每个版本必须在完成后独立可用；
> - 游戏可读取数据与工具自身状态严格分离；
> - 任何未经过目标壳验证的格式、字段或行为不得写成既定事实；
> - 新功能不得破坏当前 Gate 0 的稳定切片链路。
>
> 本次修订重点：
> - Gate 0 状态改为正式关闭，更新 Arc 风险提示的实际交互；
> - 固化 `ArcSlicerData/` 运行数据目录；
> - 重写 Version 2.1 的导出规则：显式元数据开关、包含倍速的片段 ID、曲包输出、封面生成、双层导出包；
> - 明确歌曲曲绘三个标准文件全部迁移；
> - 将多难度读取与完整 difficulties 输出列入后续版本；
> - 将官方曲包封面 / topbar 本地资源选择列入后续功能。

---

## 1. 项目目标

Arc Slicer 是面向 Arcaea 自制壳 / 本地资源环境的谱面练习切分工具。

用户可从一首源歌曲中选择一个或多个时间段，以统一倍速导出独立练习片段。工具应能够：

* 切分 `base.ogg` 与选定难度的 `.aff`；
* 保持源歌曲已有的曲绘资源；
* 在用户显式启用元数据导出时生成可读 `songlist`；
* 在用户显式启用曲包导出时生成 `packlist`、曲包封面与归属关系；
* 同时生成“本次导出包”和“总导出包”，分别满足分享与长期累计两种需求；
* 最终使产物能够整体复制到目标壳的 `songs/` 根目录。

本项目不以谱面预览、波形、试听等体验功能为前置条件；稳定输出优先。

---

## 2. 核心设计原则

### 2.1 每个版本必须完整交付

每一版本必须完成一个可验证闭环，而不是只新增 UI、临时数据结构或半套文件写入。

例如：

* 有 songlist 开关时，开启后必须产生可导入的合法 songlist；
* 有 packlist 开关时，开启后必须产生完整 packlist 与其 `img` 所引用的封面文件；
* 有总导出包时，合并后的 songlist、packlist 与资源目录必须一致；
* 有导出目标选择时，不能因为目标未选中而悄悄丢失内容。

### 2.2 输出优先于展示

优先级：

1. AFF 与音频切片正确；
2. 元数据结构正确；
3. 资源目录正确；
4. 本次导出包与总导出包一致；
5. 安全写入目标壳目录；
6. 波形、试听、Combo 与谱面预览。

### 2.3 游戏数据与工具数据分离

游戏可读取的文件必须保持原生格式，例如：

* `songlist`
* `packlist`
* `.aff`
* `base.ogg`
* 歌曲曲绘
* `pack/` 曲包资源

工具自身的状态必须位于 `ArcSlicerData/` 中，例如：

* `config.json`
* `slides.json`
* 未来的导出记录、索引和缓存
* 总导出包重建所需的工具清单

不得向游戏 `songlist`、`packlist` 写入工具私有字段。

### 2.4 不依赖隐式行为

以下行为必须显式、可见、可验证：

* 是否生成 songlist；
* 是否生成 packlist；
* 是否生成本次导出包；
* 是否更新总导出包；
* 曲包封面来源；
* 目标曲包 ID、封面文件名与输出位置；
* 冲突或覆盖规则。

不得用“某字段非空”作为是否输出元数据的唯一判断。

### 2.5 本地官方资源只作参考

工具可以扫描用户自行提供的、本地可读取的官方资源，用于本地索引、模板填充、曲包封面选择或 topbar 选择。

工具不得：

* 下载、分发或打包官方资源；
* 处理加密内容；
* 绕过资源保护；
* 默认将整套官方曲包资源复制进输出。

---

## 3. 当前项目基线

### 3.1 已实现并验证的能力

当前程序已具备：

* 纯 PyQt6 桌面界面；正式运行路径不使用 WebView / pywebview；
* 原生 Qt 文件夹拖放与歌曲目录选择；
* 多时间段输入、空白新增段、删除与持久保存；
* `ffmpeg` 音频切片与任意正数全局倍速；
* Gate 0 FTR（`2.aff`）切片；
* Tap、Hold、Arc、Arctap、Timing、Timinggroup、Camera、Scenecontrol 的当前基础处理；
* Arc 端点按原 easing 重新计算；
* Arc 坐标强制输出带小数点的浮点字面量；
* 非线性 Arc 切点检测；
* 行内“起点截断 / 终点截断”状态与即时自绘说明卡；
* 非零 AudioOffset、Camera / Scenecontrol 持续时间未完全缩放等已知边界警告；
* PyInstaller 单文件 EXE 构建；
* `ArcSlicerData/` 运行数据目录，以及旧根目录 / `dist/` 数据的非破坏式迁移；
* 基础自动回归测试；
* 真实壳实机导入、进入歌曲与基础游玩验证；
* Gate 0 非线性 Arc 风险提示的实际 UI 验证。

### 3.2 当前明确限制

以下均不是 Gate 0 阻塞项，但必须在后续版本中保持边界清楚：

* 当前固定读取与输出 `2.aff`，即仅 FTR；
* 当前一个导出批次使用统一 speed，尚未支持逐片段 speed；
* AudioOffset 尚未完成音频切点与 AFF 时间的统一换算；
* Camera / Scenecontrol 部分持续时间参数尚未随 speed 完整处理；
* 非线性 Arc 中途截断仅保证切点端坐标正确，Arc 内部轨迹仍为近似；
* 当前 Timing 补齐策略不保留切片开始时的原始拍线 / 小节线相位；
* 仍未实现完整曲包导出、总导出包、曲包封面、packlist；
* 当前 songlist 的旧模板 fragment 路径必须在 Version 2.1 中退出正式输出链路。

---

## 4. 资源、运行数据与输出目录规范

### 4.1 运行数据目录

所有用户可变运行数据统一位于：

```text
ArcSlicerData/
├─ songs/
├─ out/
├─ config.json
└─ slides.json
```

规则：

* 源码运行时：`<项目根目录>/ArcSlicerData/`；
* EXE 位于 `dist/` 时：使用与 `dist/` 同级的 `ArcSlicerData/`；
* EXE 独立放置时：使用 EXE 所在目录下的 `ArcSlicerData/`；
* `build.bat` 可以清理 `build/` 与 `dist/`，不得清理 `ArcSlicerData/`；
* 旧根目录或旧 `dist/` 下的 `songs/`、`out/`、`config.json`、`slides.json` 可在首次启动时迁移；旧数据不得自动删除。

### 4.2 游戏 songs 根目录

目标壳的游戏资源根为：

```text
songs/
├── songlist
├── packlist
├── unlock
├── pack/
│   ├── <pack_img_name>.png
│   └── 1080/
├── <song_id_1>/
├── <song_id_2>/
└── ...
```

规则：

* `songlist` 与 `packlist` 均位于 `songs/` 根；
* `pack/` 是曲包资源目录，不是歌曲目录；
* `unlock` 当前不读取、不生成、不修改；
* 一首歌曲是否可作为源歌曲，必须由实际资源判断，而非仅由目录名判断；
* 当前 Gate 0 识别条件为同时存在 `base.ogg` 与 `2.aff`；
* 多难度阶段应改为“存在 `base.ogg` 且至少存在一个有效 `0.aff`–`4.aff`”。

### 4.3 标准歌曲目录与曲绘

标准歌曲目录可包含：

```text
songs/<song_id>/
├── base.ogg
├── 1080_base.jpg
├── 1080_base_256.jpg
├── base.jpg
├── 0.aff
├── 1.aff
├── 2.aff
├── 3.aff
└── 4.aff
```

难度编号：

| AFF 文件 | 难度 |
| --- | --- |
| `0.aff` | PST |
| `1.aff` | PRS |
| `2.aff` | FTR |
| `3.aff` | BYD |
| `4.aff` | ETR |

曲绘规则：

* `1080_base.jpg`：大曲绘；
* `1080_base_256.jpg`：缩略曲绘；
* `base.jpg`：旧资源兼容 / 低分辨率曲绘；
* Version 2.1 起，源歌曲存在的上述三个曲绘文件必须全部原样复制到每个输出片段目录；
* 不再只选一个文件并改名为 `base.jpg`；
* 曲包封面自动裁切的来源优先级单独规定为：

```text
1080_base.jpg → base.jpg → 1080_base_256.jpg
```

---

## 5. 统一数据模型

后续实现不得继续把核心状态散落在 UI 控件与临时字典中。至少应建立：

```text
SourceSong
SongTemplate
SegmentSpec
ChartSelection
OutputSongPlan
PackPlan
ExportPlan
ExportDestination
LibraryManifest
```

### 5.1 SourceSong

```text
song_id
song_dir
audio_path
jacket_paths
available_difficulties
source_songlist_entry
source_pack_info
audio_duration_ms
```

### 5.2 SongTemplate

SongTemplate 是所有 songlist 输出的唯一来源模型。

可由以下方式填充：

* 手动填写；
* 用户导入的 songlist JSON；
* 后续本地官方资料库匹配。

无论来源如何，最终都必须走同一套字段白名单、类型校验、songlist 输出逻辑。

旧 `songlist_example.json → songlist_fragment.json` 路径不得继续作为正式导出方式。

### 5.3 SegmentSpec

```text
start_ms
end_ms
speed
label_override
```

当前为时间模式与统一 speed。未来可扩展：

```text
mode: "time" | "combo"
start_combo
end_combo
per_segment_speed
```

### 5.4 OutputSongPlan

```text
song_id
display_title
segment_index
segment_spec
selected_chart
audio_output_path
chart_output_path
songlist_entry
resource_copy_plan
```

### 5.5 PackPlan

```text
pack_id
display_name
description
section
plus_character
img_name
cover_source
cover_output_path
packlist_entry
song_ids
```

已确认默认：

```text
pack_id       = 源歌曲目录名（source_song_id），允许编辑
section       = collab
plus_character = -1
img_name      = 由 pack_id 派生的 PNG 文件名，允许编辑；最终以 packlist.img 为准
```

### 5.6 ExportDestination

```text
write_current_export: bool
write_library_export: bool
```

默认两个目标均启用。

任一导出操作至少选择一个目标；两个都未选择时必须阻止导出并提示。

### 5.7 ExportPlan

导出必须先生成 ExportPlan，再执行文件写入：

```text
source_song
selected_chart
song_template
segments
output_songs
pack
metadata_flags
destinations
conflicts
warnings
```

### 5.8 LibraryManifest（后续）

总导出包的重建与一致性校验需要工具私有记录。该记录必须存放在 `ArcSlicerData/`，不能放入游戏 `songs/` 目录或写入 songlist / packlist。

首版可先完成总包合并；“从清单重建总导出包”作为后续独立功能。

---

## 6. 元数据开关、校验与 songlist 规则

### 6.1 显式开关

界面必须提供：

```text
[ ] 生成 songlist
    [ ] 生成 packlist 与曲包资源
```

规则：

* 两个开关默认关闭；
* `packlist_enabled` 依赖 `songlist_enabled`；
* 开启 packlist 时自动开启 songlist；
* 关闭 songlist 时必须同时关闭并禁用 packlist；
* 用户填写但未启用开关的元数据仍保存到 `slides.json`，但不得输出 songlist、packlist 或曲包资源；
* 普通切片不应因未填写元数据而受阻；
* 不得以“某字段非空”自动生成元数据文件；
* 不再输出 `songlist_fragment.json`。

### 6.2 Songlist 输出与字段校验

启用 songlist 后：

* 每个片段仅生成根 `songs/songlist` 中的一条 song 条目；
* 不再在每个歌曲目录中额外写 `songlist`；
* `songlist.id` 必须等于片段目录名；
* 输出必须是原生：

```json
{
  "songs": [
    { "id": "..." }
  ]
}
```

字段校验原则：

* 字段是否必填必须以目标壳已验证可读的样本为依据；
* 不得因为 UI 中存在某个字段，就机械要求它非空；
* 结构字段与已确认默认值可自动填充；
* 用户可选字段允许为空；
* 校验失败时必须在写入前阻止对应元数据输出，不得留下半残 JSON；
* `purchase`、`version`、`source_localized` 等兼容字段在未完成目标壳实测前不得擅自删除或假定可省略。

初始 songlist 基础字段模型：

```json
{
  "id": "",
  "title_localized": { "en": "" },
  "artist": "",
  "bpm": "",
  "bpm_base": 0,
  "set": "",
  "purchase": "",
  "audioPreview": 0,
  "audioPreviewEnd": 0,
  "side": 0,
  "bg": "",
  "date": 0,
  "version": "",
  "difficulties": []
}
```

当 packlist 已启用时：

```text
songlist.set = pack_id
```

当只启用 songlist 时：

```text
songlist.set 默认 single，允许用户明确修改
```

### 6.2.1 V2.1 固定 FTR 的 difficulty 兼容规则

当前 V2.1 固定切分并输出 FTR / `2.aff`。

已实机确认：目标壳中，新建曲包至少需要有一首归属该曲包的歌曲，在 songlist `difficulties` 中明确列出 `ratingClass = 0`、`1`、`2`，才能正常进入。

为了确保单曲导出也满足该条件，并保持同一曲包内切片歌曲结构一致，工具对每个输出切片歌曲统一写入：

* `ratingClass 0`：`rating = -1`；
* `ratingClass 1`：`rating = -1`；
* `ratingClass 2`：使用当前填写的实际 `rating`；
* 三项按 `0`、`1`、`2` 升序；
* 三项均保留 `chartDesigner` 与 `jacketDesigner`；
* `0` / `1` 的 `ratingPlus` 固定 `false`；
* `2` 的 `ratingPlus` 使用当前表单值。

这只是无谱面难度占位，不表示工具已经支持 PST / PRS 切片。实际 AFF 输出仍只有 `2.aff`。

`ratingClass 3` / `4` 与实际多难度读取、输出，仍属于后续 Version 2.5。

### 6.3 Packlist 输出与字段校验

启用 packlist 后：

* 必须同时生成 songlist；
* 当前一次导出的所有片段归属同一 `pack_id`；
* `songs/pack/<img_name>` 必须存在；
* `packlist.img` 必须与实际输出的封面文件名完全一致；
* `img_name` 仅允许文件名，不允许路径分隔符、`..` 或非 PNG 扩展名；
* `pack_id` 必须符合输出 ID 规则；默认源歌曲目录名不合法时，必须提示用户修改，不能静默改写；
* `section` 固定默认 `collab`；
* `plus_character` 固定默认 `-1`；
* 其他实际必填字段必须根据目标壳样本验证后再锁定。

V2.1 的最小目标条目：

```json
{
  "packs": [
    {
      "id": "pack_id",
      "section": "collab",
      "plus_character": -1,
      "name_localized": { "en": "..." },
      "description_localized": { "en": "..." },
      "img": "pack_image.png"
    }
  ]
}
```

不得默认添加未经验证的字段，例如：

```text
pack_parent
is_extend_pack
is_active_extend_pack
custom_banner
cutout_pack_image
small_pack_image
```

### 6.4 模板导入

用户导入 JSON songlist 时：

1. 文件必须是 UTF-8 JSON；
2. 顶层必须有 `songs` 数组；
3. 空数组报错；
4. 一个条目自动选中；多个条目显示选择列表；
5. 选中条目只用于填充 SongTemplate；
6. 不可识别字段只作为待审查信息，不得直接原样复制到输出；
7. 不得重新引入“模板 fragment 单独写文件”的第二输出路径。

---

## 7. 命名、标题与覆盖规则

### 7.1 片段歌曲 ID

每个片段输出 ID 固定为：

```text
<source_song_id>_<start_ms>_<end_ms>_x<speed_token>
```

示例：

```text
prelude_heavensdoor_21000_22000_x1
prelude_heavensdoor_21000_22000_x1p25
prelude_heavensdoor_21000_22000_x0p75
```

规则：

* `source_song_id` 为导入歌曲目录名；
* `speed_token` 为规范化十进制速度；去除无意义尾零，小数点使用 `p`；
* `1.0 → x1`、`1.25 → x1p25`、`0.75 → x0p75`；
* 不得直接使用 Python float 的原始字符串；
* `songlist.id`、输出歌曲目录名与 OutputSongPlan.song_id 必须完全一致；
* 同源曲、同区间、同倍速再次导出视为同一 ID，在所选输出目标中覆盖该 ID 的旧资源与 songlist 条目；
* 不同倍速自然拥有不同 ID；
* 当前 `source_song_id` 必须满足游戏输出 ID 的 ASCII / 路径安全规则；不符合时，应在导出前提示，而不是默默改变源目录名。

### 7.2 展示标题

展示标题必须包含与 ID 相同的可辨识信息：原曲标题、开始时间、结束时间、倍率。

默认格式：

```text
<source_title> [<start_ms>–<end_ms>ms · <speed>×]
```

示例：

```text
Prelude Heaven's Door [21000–22000ms · 1.25×]
```

规则：

* 标题不使用文件名式 `x1p25`，但必须表达同一倍率信息；
* 用户可覆盖默认标题；
* 未提供 source title 时，可回退为 `source_song_id`。

### 7.3 曲包 ID、显示名与图像名

```text
默认 pack_id      = source_song_id
默认 pack 显示名  = source title；不可用时回退 source_song_id
默认 img_name     = 由 pack_id 派生的 PNG 文件名
```

三者均允许用户修改，但：

* `pack_id` 是 songlist `set` 与 packlist `id` 的唯一关联键；
* `img_name` 是 `packlist.img` 与 `songs/pack/<img_name>` 的唯一关联键；
* `img_name` 不要求与 `pack_id` 同名；
* 同一个图像文件名允许被多个 pack 引用；但在总导出包中，若同名文件内容不同，必须报冲突，不得静默覆盖。

---

## 8. 曲包封面与 pack 资源

### 8.1 曲包封面输出

完整曲包导出时，曲包封面必须输出为：

```text
songs/pack/<img_name>
```

最终格式固定为：

```text
PNG，374 × 750 px
```

`packlist.img` 的值必须就是 `<img_name>`。

### 8.2 封面来源

V2.1 支持：

1. **自动生成**：从源歌曲曲绘按优先级裁切：

   ```text
   1080_base.jpg → base.jpg → 1080_base_256.jpg
   ```

2. **用户上传**：支持 PNG、JPG、JPEG；最终转换为 `374 × 750` PNG。

后续版本支持：

3. 从用户自行提供的本地官方曲包封面资源库中搜索、选择并复制。

### 8.3 裁切规则

统一采用：

```text
等比覆盖缩放（cover） + 居中裁切（center crop）
```

流程：

1. 读取源图；
2. 保持原比例缩放至完全覆盖 `374 × 750`；
3. 从中心裁掉溢出部分；
4. 输出为 PNG。

规则：

* 比例不符不是错误，不得仅因比例不符拒绝导出；
* 源图较小允许放大，但应提示可能模糊；
* 读取失败、损坏文件、无法编码或没有任何可用封面来源时，完整曲包导出报错；
* V2.1 不做手动拖拽裁切框；
* 后续可增加上 / 中 / 下焦点或手动裁切位置。

### 8.4 `pack/1080/` topbar

`pack/1080/` 用于曲包 topbar 资源。

规则：

* V2.1 不创建空的 `pack/1080/`；
* V2.1 不从歌曲曲绘自动生成 topbar；
* 后续可扫描用户本地官方 topbar 资源，供用户搜索 / 选择；
* 选中后必须原样复制到：

```text
songs/pack/1080/<官方资源原文件名>
```

---

## 9. AFF 切片正确性要求

### 9.1 基础规则

AFF 文件：

* 仅保存谱面事件；
* 不保存曲名、定数、谱师、曲包或解锁信息；
* 正文从第一个单独的 `-` 之后开始；
* 每个可读谱面必须在 Timinggroup 外存在 `timing(0,bpm,beats);`；
* Timinggroup 不可嵌套；
* Timinggroup 内必须保持有效 Timing。

### 9.2 切片时间、闭区间与倍速定义

切片时间窗口采用闭区间：

```text
[start_ms, end_ms]
```

位于 `start_ms` 或 `end_ms` 的 Tap、Hold 端点、Arc 端点和 Arctap 允许保留；相邻片段共享边界事件可以接受。

输入片段必须满足：

```text
end_ms > start_ms
```

输出事件时间：

```text
new_time = round((old_time - start_ms) / speed)
```

倍速规则：

```text
输出 Timing BPM = 原 Timing BPM × speed
输出 songlist bpm_base = 原 bpm_base × speed
Timing beats 保持不变
```

单一数值形式的 `bpm` 可同步缩放；复杂 BPM 字符串保留原样。

`AudioOffset` 的统一换算仍待后续实验。当前阶段应保留原 Header；检测到非零 `AudioOffset` 时只给出警告。

### 9.3 Hold 与 Arc

切到 Hold 或 Arc 中间时：

* Hold 必须裁切起止时间并换算；
* Arc 必须按 easing 计算切点真实坐标，再生成新端点；
* 附着 Arctap 只保留有效闭区间内的项；
* 不得因为切片产生非法 Arc；
* 正常持续 Arc 以 `t1 < t2` 为测试对象；
* 坐标递减不表示 Arc 在语句内部反向折返；
* 不得因为 x / y 坐标差为负而交换 `si` / `so`。

### 9.4 Arc easing 与坐标类型

基础 easing：

```text
s  = Linear
si = Sine Out = sin(πp / 2)
so = Sine In  = 1 - cos(πp / 2)
b  = Bézier   = 3p² - 2p³
```

二维映射：

| AFF easing | x 轴 | y 轴 |
| --- | --- | --- |
| `s` | s | s |
| `si` | si | s |
| `so` | so | s |
| `b` | b | b |
| `sisi` | si | si |
| `siso` | si | so |
| `sosi` | so | si |
| `soso` | so | so |

Arc 的 `x1/x2/y1/y2` 必须输出为带小数点的浮点字面量，例如：

```aff
arc(62,687,0.500000,-0.250000,si,0.000000,0.000000,0,none,false);
```

Arc 时间、Arctap 时间、Timing 时间、`color` 与 `smoothness` 不得误写成浮点。

### 9.5 非线性 Arc 截断近似与风险提示

线性 `s` Arc 中途截断后可保持严格一致。

以下非线性 easing：

```text
b
si
so
sisi
siso
sosi
soso
```

中途截断后，当前实现仅保证切片边界坐标正确；片段内部轨迹可能与原谱略有偏差。

风险条件：

```text
low < start_ms < high
low < end_ms < high
```

并且 easing 属于非线性集合、Arc 非零时长。

当前 UI 已实现：

* 常驻紧凑状态：`起点截断` / `终点截断`；
* 自绘 Arc 图标；
* 约即时出现的浅色说明卡；
* 说明卡解释“边界不突跳、内部近似”的原因；
* 汇总命中的 easing；
* 无风险时不占额外空间；
* 不使用阻塞确认框；
* 不阻断正常导出。

未来高精度分段拟合完成前，此提示必须保留。

### 9.6 当前 Timing 兼容策略

当前策略保证的是“BPM 与事件时间的局部可读性”，不保证切片开始时的小节线 / 拍线相位与原谱严格连续。

根层与 Timinggroup 分别补齐基础 Timing；两者不得互相替代。

### 9.7 未来：Timing 相位与原谱流速保真

独立正确性阶段，目标同时保持：

1. 音频对齐；
2. 根层小节线 / 拍线相位；
3. 各 Timinggroup 内 Note 初始流速与后续 Timing 变化。

优先验证负时间 Timing；若目标壳不接受，再通过经实测的前导时间与 AudioOffset / 等价机制兜底。

### 9.8 需要覆盖的语句

最终至少识别：

* `timing`
* Tap
* `hold`
* `arc`
* `arctap`
* `camera`
* `scenecontrol`
* `timinggroup`
* `AudioOffset`
* `TimingPointDensityFactor`

后续 Combo 计算还必须理解 `noinput`、`fadingholds`、`anglex`、`angley`、Arc 组、`true` Arc、`designant` Arc。

---

## 10. 功能版本规划

# Gate 0：切片核心与风险提示（已关闭）

已完成：

* FTR 基础切片；
* ffmpeg 音频切片与 speed；
* Arc / Hold 中途裁切；
* 浮点 Arc 坐标；
* 根层与 Timinggroup 基础 Timing；
* 非线性 Arc 风险检测；
* 轻量行内状态与自绘说明卡；
* 自动测试与真实壳实机验证；
* 纯 PyQt6 正式运行路径。

后续不得以“Gate 0 未完成”为由重做上述逻辑；如需变更，必须新增回归测试与实机验证。

# Version 2.1：导出元数据、练习曲包与双层输出工作流

## 目标

让用户可从一首源曲的一组切片中，按需生成：

* 普通切片资源；
* songlist；
* packlist 与曲包封面；
* 可单独分享的本次导出包；
* 可长期累计的总导出包。

## 范围

* 统一 SongTemplate 输出路径；
* 删除正式输出中的 `songlist_fragment.json`；
* `songlist_enabled` / `packlist_enabled` 显式开关与校验；
* FTR（`2.aff`）维持当前固定处理；
* 片段 ID 与展示标题包含开始、结束、倍率；
* `pack_id` 默认源歌曲目录名、允许编辑；
* `section = collab`；
* 复制所有现有歌曲曲绘文件；
* 自动裁切或上传曲包封面，输出 `374 × 750` PNG；
* 生成 `songs/songlist`、`songs/packlist`、`songs/pack/<img_name>`；
* 生成本次导出包并可选更新总导出包；
* 总导出包合并 songlist、packlist、歌曲资源、曲包封面；
* 导出前生成 ExportPlan、进行校验和冲突提示。

## 双层输出目录

```text
ArcSlicerData/out/
├─ current_export/                 # 本次导出包；每次重建
│  └─ songs/
│     ├─ songlist                  # 仅启用 songlist 时
│     ├─ packlist                  # 仅启用 packlist 时
│     ├─ pack/
│     │  └─ <img_name>
│     ├─ <segment_id_1>/
│     │  ├─ base.ogg
│     │  ├─ 2.aff
│     │  ├─ 1080_base.jpg          # 源文件存在才复制
│     │  ├─ 1080_base_256.jpg      # 源文件存在才复制
│     │  └─ base.jpg               # 源文件存在才复制
│     └─ <segment_id_2>/
└─ library_export/                 # 总导出包；长期累计
   └─ songs/
      ├─ songlist
      ├─ packlist
      ├─ pack/
      └─ <segment_id...>/
```

## 本次导出包规则

* 用户启用“生成本次导出包”时，先清空并重建 `current_export/`；
* 仅包含本次 ExportPlan 的资源与元数据；
* 用于直接分享给他人；
* 不应混入过去导出的孤儿歌曲、旧 songlist 条目或旧 pack 资源。

## 总导出包规则

* 用户启用“更新总导出包”时，更新 `library_export/`；
* 不清空已有库；
* songlist 按 `song.id` 合并：相同 ID 以本次条目与资源覆盖；
* packlist 按 `pack.id` 合并：相同 ID 以本次条目更新；
* 曲包封面按 `img_name` 合并：
  * 不存在则复制；
  * 同名且内容相同则复用；
  * 同名但内容不同则报冲突，要求用户修改 `img_name` 或封面来源；
* songlist 关闭时仍可生成普通本次资源包；但更新总导出包时必须明确提示其资源不会获得 songlist 索引；
* 后续可提供“总导出包完整性检查与重建”功能。

## 验收标准

* 普通切片不填写元数据也可正常导出；
* 开启 songlist 后，校验通过才生成合法 `songs/songlist`；
* 开启 packlist 后，自动绑定 `set = pack_id` 并生成合法 `songs/packlist` 与封面；
* 两个导出目标可独立选择，默认均开启；
* 两个目标都关闭时阻止导出；
* 本次导出包不会混入历史资源；
* 总导出包可累计多个源曲 / pack；
* 相同片段 ID 重导出时，总导出包保持元数据与资源一致；
* 当前导出包与总导出包都可整体复制其 `songs/` 目录到目标壳进行验证。

# Version 2.2：安全合并至目标目录

功能范围：

* 用户选择目标壳的 `songs/` 根；
* 读取目标 `songlist`、`packlist`、`pack/`；
* 生成增量 / 冲突预览；
* 使用 staging 临时目录；
* 用户确认后才写入；
* 默认不覆盖已有目标歌曲、曲包或曲包封面；
* 不修改 `unlock`；
* 失败时保持目标目录可用。

# Version 2.2.5：Timing 相位与原谱流速保真

功能范围：

* 保留根层小节线 / 拍线在切片起点处的相位；
* 保留 Timinggroup 内 Note 流速；
* 先以最小谱实测负时间 Timing；
* 若不可用，再完成经实测的前导时间与 AudioOffset 兜底；
* 覆盖 0.5x / 1.0x / 2.0x。

# Version 2.3：波形与双端拖拽选段

功能范围：

* 波形缓存；
* 双端拖拽选区；
* 数值输入与选区同步；
* 长曲定位、缩放或平移；
* 不在拖动时反复触发 ffmpeg。

# Version 2.4：循环试听

功能范围：

* 源音频当前选区循环试听；
* 调整结束后延迟启动；
* 自动试听开关；
* 选区变化时停止旧播放；
* 不依赖生成临时切片音频。

# Version 2.5：Combo 切片与多难度选择

功能范围：

* 扫描 `0.aff`–`4.aff`；
* 允许用户选择实际存在的源难度；
* 输出对应难度编号的 AFF，而不是始终写 `2.aff`；
* songlist 生成 `ratingClass = 0..4` 的完整 difficulties 列表；
* 源歌曲不存在的难度仍写出对应 `ratingClass`，并使用：

```json
{ "ratingClass": n, "rating": -1 }
```

* 选中难度填写实际 chart designer、rating、ratingPlus 等元数据；
* 支持时间模式与 Combo 模式；
* Combo 区间先解析为明确时间区间，再复用切片流程。

# Version 2.6：本地官方资料与曲包资源库

功能范围：

* 用户选择本地官方 songs 根；
* 扫描 songlist、packlist、歌曲目录；
* 建立本地索引；
* 本地搜索 / 选择歌曲元数据模板；
* 本地搜索 / 选择官方曲包封面；
* 本地搜索 / 选择 `pack/1080/` topbar；
* 选中官方封面或 topbar 时原样复制；
* 不复制完整官方 packlist 或其他无关资源。

# Version 3.0：谱面预览

功能范围：

* 独立 AFF 解析与渲染；
* 显示 Tap、Hold、Arc、Arctap；
* 与当前选区同步；
* 不作为导出核心依赖。

# Future 专项：总导出包重建与一致性检查

功能范围：

* 维护工具私有 LibraryManifest；
* 检查 library_export 的 songlist、packlist、资源目录和引用封面是否一致；
* 根据清单或现有库重建总导出包；
* 报告孤儿歌曲、孤儿 pack 封面、重复 song ID、冲突 pack img；
* 不修改目标壳目录。

# Future 专项：非线性 Arc 高精度分段拟合

目标：减少 `b / si / so / sisi / siso / sosi / soso` Arc 中途截断后的局部轨迹误差。

采用：

```text
自适应采样 + 多段短 Arc 逼近
```

在完成前，当前近似风险提示必须继续保留。

---

## 11. UI 要求

### 11.1 Gate 0 已有操作

* 选择 songs 根目录；
* 选择源歌曲；
* 新增、删除片段；
* 数字输入开始与结束时间；
* 设置全局 speed；
* 保存与加载切片方案；
* 查看日志；
* 查看非线性 Arc 截断说明卡。

### 11.2 Version 2.1 元数据与导出 UI

必须提供：

```text
[ ] 生成 songlist
    [ ] 生成 packlist 与曲包资源

[✓] 生成本次导出包
[✓] 更新总导出包
```

要求：

* songlist / packlist 开关默认关闭；
* 两个导出目标默认开启；
* packlist 依赖 songlist；
* 同一套元数据应用于本次所有片段；
* `pack_id` 默认源歌曲目录名，允许编辑；
* `section` 默认 `collab`；
* `img_name` 默认由 `pack_id` 派生，允许编辑；最终以 `packlist.img` 为准；
* 封面来源至少提供：自动裁切、上传图片；
* 元数据面板不能阻碍普通切片；
* 当前表单数据需写入 `slides.json`；
* UI 不引入多页向导或每段重复填写元数据。

### 11.3 导出前预览

导出前至少展示：

* 是否生成 songlist / packlist；
* 是否生成本次导出包 / 更新总导出包；
* pack_id、显示名、section、img_name；
* 输出歌曲数量；
* 每个 segment_id 与展示标题；
* 时间段与 speed；
* 将复制的曲绘；
* 曲包封面来源与裁切警告；
* 总导出包中的覆盖 / 冲突项。

### 11.4 未来多难度 UI

多难度阶段应提供：

* 可用难度列表；
* 选择源 AFF；
* 当前缺失难度提示；
* difficulties 输出预览；
* Combo / 时间模式切换。

---

## 12. 错误处理与安全要求

必须明确处理：

* 找不到 `base.ogg`；
* 找不到选定 AFF；
* AFF 无法解析；
* 结束时间小于等于开始时间；
* speed 非有限正数；
* songlist / packlist 开关依赖错误；
* SongTemplate 不合法；
* pack_id 或 segment_id 不合法；
* `img_name` 非法、带路径或不是 PNG；
* 曲包封面不存在、损坏或转换失败；
* 同名 pack img 内容冲突；
* 当前歌曲没有任一曲绘而又需自动生成 pack cover；
* 两个导出目标均未选择；
* 总导出包元数据读取不合法；
* ffmpeg 不存在或失败。

输出原则：

1. 先生成 ExportPlan；
2. 先校验；
3. 先写入 staging 或临时目录；
4. 再更新所选导出目标；
5. 失败时不留下半写入 JSON；
6. current_export 清空动作不得影响 library_export；
7. 不得修改目标壳目录；目标壳安全合并属于 Version 2.2。

---

## 13. 测试要求

### 13.1 AFF 回归测试

至少覆盖：

* Tap、Hold、Arc、Arctap；
* 多段 Timing 与 Timinggroup；
* 非零 AudioOffset；
* Camera / Scenecontrol；
* 不同 speed；
* 极短片段；
* 边界事件；
* 坐标递减的单向 Arc；
* `s` Arc 不显示非线性风险；
* 非线性 Arc start / end 风险分别显示；
* 说明卡 easing 汇总与编辑刷新；
* Timing 相位专项最小谱。

### 13.2 V2.1 元数据与导出测试

至少覆盖：

* songlist / packlist 开关默认关闭；
* 开启 packlist 自动启用 songlist；
* songlist 关闭时不产生 songlist、packlist；
* 填写表单但不开启时仅保存 slides，不输出元数据；
* `songlist_fragment.json` 不再生成；
* speed token 正规化；
* segment_id 与 songlist.id、目录名一致；
* 标题包含相同的起止时间与倍率信息；
* `pack_id` 默认源歌曲目录名，允许覆盖；
* `section = collab`；
* `packlist.img` 与实际输出文件一致；
* 曲绘三个文件存在时全部原样复制；
* 只存在部分曲绘时只复制存在项；
* 自动裁切优先级与 `374 × 750` 输出；
* 上传图片的中心裁切；
* current_export 每次重建；
* library_export 按 song ID / pack ID 合并；
* 同名 pack img 内容冲突阻止更新；
* 两个输出目标均未选择时报错；
* 失败时不留下半写入 songlist / packlist。

### 13.3 实机导入测试

至少验证：

* current_export/songs 可整体导入；
* library_export/songs 可整体导入；
* 单片段与多片段；
* 1.0x 与非 1.0x；
* 自动裁切封面与上传封面；
* songlist-only 与完整 packlist；
* 重导出同一 ID 后元数据与资源一致；
* Windows EXE 环境；
* ffmpeg 内置与 PATH 两种环境。

---

## 14. 非目标

在相应版本前，本项目不追求：

* 编辑或创作完整 AFF；
* 修改 `unlock`；
* 自动生成 World 解锁；
* 加密或不可读取官方谱面；
* 自动下载 / 分发官方资源；
* 自动从歌曲曲绘生成 topbar；
* 默认覆盖目标壳已有歌曲或曲包；
* 在高精度拟合完成前宣称非线性 Arc 严格等价；
* 用预览替代真实壳验证。

---

## 15. 已确认规则与仍待确认事项

### 15.1 已确认

* Gate 0 已关闭；
* 正式 UI 为 PyQt6，WebView / `ui.html` 不属于运行路径；
* 运行数据位于 `ArcSlicerData/`；
* songlist 与 packlist 使用显式开关，默认关闭；
* packlist 依赖 songlist；
* pack_id 默认源歌曲目录名，允许编辑；
* packlist `section = collab`；
* 片段 ID 包含源歌曲目录名、开始毫秒、结束毫秒、规范化 speed；
* 展示标题表达相同的区间与倍率信息；
* `idx` 不生成、不管理；
* 现有 `1080_base.jpg`、`1080_base_256.jpg`、`base.jpg` 全部迁移；
* 曲包封面输出为 `374 × 750` PNG；
* 曲包封面支持自动居中裁切与用户上传；
* packlist `img` 决定实际 `songs/pack/<img_name>` 文件名；
* `pack/1080/` topbar 为后续本地官方资源选择功能；
* 本次导出包每次重建，总导出包长期合并；
* V2.1 固定输出 FTR / `2.aff`，并为目标壳兼容在 `difficulties` 中写入 `ratingClass 0 / 1 / 2`；
* 多难度、Combo 与 `ratingClass 0..4` 完整 difficulties 输出归入后续 Version 2.5。

### 15.2 仍待验证或后续决定

* 目标壳对 songlist 中 `purchase`、`version` 等字段的最小兼容要求；
* packlist `name_localized`、`description_localized` 是否允许空字符串；
* `packlist.img` 是否对所有目标壳都必须存在；
* 374 × 750 是否为所有目标壳的唯一固定尺寸，还是需将尺寸作为壳配置；
* 自动裁切是否需要后续加入上 / 中 / 下焦点；
* 目标壳对根层与 Timinggroup 内负时间 Timing 的兼容性；
* AudioOffset 与前导补偿的实际换算；
* 多难度缺失项的 `rating = -1` 之外是否还需额外字段。

---

## 16. 开发执行顺序

```text
Gate 0：已关闭
↓
Version 2.1：导出元数据、练习曲包与双层输出工作流
↓
Version 2.2：安全合并至目标目录
↓
Version 2.2.5：Timing 相位与原谱流速保真
↓
Version 2.3：波形双端拖拽选段
↓
Version 2.4：循环试听
↓
Version 2.5：Combo 切片与多难度选择
↓
Version 2.6：本地官方资料与曲包资源库
↓
Version 3.0：谱面预览
↓
Future：总导出包重建与一致性检查
↓
Future：非线性 Arc 高精度分段拟合
```

每个新功能进入开发前，必须回答：

1. 它依赖哪些已有数据模型？
2. 它是否影响游戏可读的输出？
3. 它的异常路径是什么？
4. 它能否在当前版本独立交付？
5. 它如何自动测试、如何真实壳验证？
6. 它是否可能破坏 current_export、library_export 或目标壳现有数据？
