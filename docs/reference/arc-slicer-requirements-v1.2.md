# Arc Slicer 项目需求书

> 文档状态：设计基线（修订 1.2）
> 项目名称：Arc Slicer
> 当前阶段：Gate 0 已完成实机导入与游玩验证；待补“非线性 Arc 近似警告”后正式关闭。后续主线从 Version 2.1 开始。
> 更新原则：任何新增功能必须保持当前版本可独立使用，不以“未来功能完成后才可用”为前提。
>
> 本次修订重点：
> * 记录 Gate 0 已完成“真实壳导入、进入歌曲与基础游玩”的实机验证；
> * 将“非线性 Arc 中途截断”的 UI 风险提示列为 Gate 0 唯一剩余功能与验收项；
> * 不再把 `t1 > t2` 视为需要兼容或验证的常规 Arc；改为验证 x/y 坐标反向时 easing 不被错误翻转；
> * 新增“Timing 相位与原谱流速保真”独立阶段，处理小节线相位、根层 Timing、组内 Timing、负时间 Timing 与 AudioOffset 兜底方案；
> * 保留未来“非线性 Arc 高精度分段拟合”专项计划。

---

## 1. 项目目标

Arc Slicer 是面向 Arcaea 自制壳/本地资源环境的谱面练习切分工具。

用户应能够从一首完整歌曲中选取一个或多个练习片段。工具将为每个片段生成：

* 已切分并可选倍速处理的 `base.ogg`；
* 与音频时间一致的 `.aff` 谱面；
* 必要的歌曲资源；
* 可导入的 `songlist` 条目；
* 统一归属的新练习曲包及其 `packlist`、曲包封面。

最终输出应能够作为一个完整练习曲包导入目标壳，而不要求用户手工补写 songlist、packlist 或整理资源。

---

## 2. 核心设计原则

### 2.1 每个版本必须可用

每一版本都必须完成一个完整闭环，而非只完成 UI、数据结构或半套逻辑。

例如：

* 有 songlist 模板功能时，必须能够导出可用 songlist；
* 有新曲包功能时，必须能生成 packlist 与封面；
* 有“写入目标目录”功能时，必须能安全合并，不允许静默破坏原文件；
* 有 Combo 选段功能时，必须能可靠映射到 AFF 时间并生成正确切片。

### 2.2 输出优先于展示

谱面预览、波形、拖拽选段等体验功能不能阻塞“稳定导出可导入练习包”的主线。

优先级：

1. 输出正确；
2. 元数据完整；
3. 资源目录正确；
4. 安全合并；
5. 选段体验；
6. 谱面预览。

### 2.3 游戏数据与工具数据分离

游戏可读取的文件必须保持原生格式：

* `songlist`
* `packlist`
* `.aff`
* 歌曲资源目录
* 曲包封面目录

工具自身的配置、缓存、扫描索引、用户偏好、导出计划等信息，必须使用独立文件保存，不得向游戏 `songlist` 或 `packlist` 注入自定义字段。

### 2.4 官方数据只作本地参考

工具可扫描用户自行提供的本地官方资源、songlist、packlist 与可读取谱面，用于模板和元数据匹配。

工具不得：

* 下载、分发或打包官方资源；
* 处理加密内容；
* 绕过资源保护；
* 默认复制官方曲包结构到输出。

输出练习曲包必须使用工具新建的 packlist 与曲包封面。

---

## 3. 当前项目基线

### 3.1 当前已实现能力

当前程序已经具备：

* PyQt6 桌面界面；
* 选择或拖入歌曲目录；
* 添加多个按毫秒定义的时间段；
* 使用 ffmpeg 切分 `base.ogg`；
* 对切片音频应用全局倍速；
* 输出每个片段的歌曲文件夹；
* 可手工填写一部分 songlist 信息；
* 输出合并后的 `out/songlist`；
* PyInstaller 打包 EXE；
* 仅将同时含有 `base.ogg` 与 `2.aff` 的目录列为可切歌曲，排除 `songs/pack/`；
* 校验 speed 必须为有限正数；
* 按 `new_time = (old_time - start_ms) / speed` 换算 AFF 事件时间；
* 按 `new_bpm = old_bpm × speed` 换算 Timing BPM 与 `bpm_base`；
* 对跨越切点的 Hold 与 Arc 进行基础裁切；
* 根据原 Arc easing 计算被截断 Arc 的新端点坐标；
* 区分根层 Timing 与 Timinggroup 内 Timing，并补齐切片后的基础 Timing；
* 对非零 `AudioOffset`、Camera / Scenecontrol 持续时间未完整缩放等限制输出警告；
* 建立基础 Gate 0 自动回归测试；
* 已完成一次真实测试壳实机验证：切出的歌曲资源、songlist 与 AFF 可被壳正常识别，可进入并开始游玩；
* 已验证被截断 Arc 的当前端点插值输出可被壳读取；非线性 Arc 仍属于“可用但近似”的已知行为。

### 3.2 当前明确限制与待完成 Gate 0 项

当前实现或当前阶段仍存在以下限制，后续不能忽略：

* 当前硬编码读取和输出 `2.aff`，即仅处理 FTR；
* 当前常规资源复制逻辑仍以 `base.jpg` 为主，尚未完成标准曲绘优先级输出；
* 当前倍速为全局参数，不能逐片段设置；
* `AudioOffset` 尚未完成音频切点与 AFF 时间的统一换算；
* Camera / Scenecontrol 仅缩放起始时间，部分持续时间参数尚未按 speed 处理；
* 非线性 Arc（`b`、`si`、`so`、`sisi`、`siso`、`sosi`、`soso`）被中途截断时，当前方法只保证切片边界坐标正确，不保证内部轨迹与原 Arc 局部严格一致；
* 非线性 Arc 截断的 UI 风险提示与用户确认流程是 Gate 0 剩余必须项；完成并实测后 Gate 0 才正式关闭；
* 当前补入 `timing(0,...)` 的策略尚未保留“切片开始时位于原节拍/小节中的相位”；根层小节线与各 Timinggroup 的 Note 流速保真改由后续独立阶段实现；
* 当前未读取或写入 packlist；
* 当前直接写入输出目录，没有“输出计划/冲突预览/安全合并”机制。

---

## 4. 资源与目录规范

## 4.1 songs 根目录

```text
songs/
├── songlist
├── packlist
├── unlock
├── pack/
│   ├── select_<pack_id>.png
│   └── ...
├── <song_id_1>/
├── <song_id_2>/
└── ...
```

规则：

* `songlist`：歌曲元数据；
* `packlist`：曲包元数据；
* `unlock`：本项目当前不读取、不生成、不修改；
* `pack/`：曲包封面资源，不是歌曲目录；
* 其余普通目录可作为歌曲候选目录；
* 歌曲目录识别必须基于实际资源文件，而不应只根据“它是目录”。

建议的歌曲目录识别条件：

* 存在 `base.ogg`；
* 存在至少一个有效 `.aff`；
* 目录名符合歌曲 ID 规则。

## 4.2 歌曲目录资源

标准歌曲目录：

```text
songs/<song_id>/
├── base.ogg
├── 1080_base.jpg
├── 1080_base_256.jpg
├── 0.aff
├── 1.aff
├── 2.aff
├── 3.aff
└── 4.aff
```

难度编号：

| AFF 文件 | 难度 |
| -------- | ---- |
| `0.aff`  | PST  |
| `1.aff`  | PRS  |
| `2.aff`  | FTR  |
| `3.aff`  | BYD  |
| `4.aff`  | ETR  |

曲绘兼容优先级：

1. `1080_base.jpg`
2. `1080_base_256.jpg`
3. 旧资源兼容：`base.jpg`

输出时应优先复制真实标准资源名，而不是继续以 `base.jpg` 作为唯一规则。

---

## 5. 数据模型

后续实现不得继续把所有状态散落在 UI 控件和若干临时字典中。应建立统一领域模型。

建议至少包含以下概念：

```text
SourceSong
SongTemplate
SegmentSpec
ChartSelection
OutputSongPlan
PackPlan
ExportPlan
MergeTarget
```

### 5.1 SourceSong

表示一个已识别的源歌曲。

建议字段：

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

表示一个可作为输出基础的 songlist 单项模板。

来源可以是：

* 用户上传 songlist；
* 用户手动填写；
* 本地官谱资料索引；
* 当前源歌曲目录中发现的 songlist。

模板必须经过规范化，不应直接原样复制。

### 5.3 SegmentSpec

表示一个待切分片段。

建议字段：

```text
mode: "time" | "combo"
start_ms
end_ms
start_combo
end_combo
speed
label_override
```

规则：

* 时间模式以毫秒为主；
* Combo 模式必须在导出前解析为明确的毫秒区间；
* 每个片段未来必须支持独立倍速；
* UI 中的数字输入、波形拖拽、Combo 输入最终都写入同一 SegmentSpec。

### 5.4 OutputSongPlan

表示一个即将导出的练习歌曲。

建议字段：

```text
song_id
display_title
segment_index
segment_spec
audio_output_path
chart_output_path
songlist_entry
resource_copy_plan
```

### 5.5 PackPlan

表示一个练习曲包。

建议字段：

```text
pack_id
display_name
description
cover_source
cover_output_path
packlist_entry
song_ids
```

### 5.6 ExportPlan

表示一次完整导出，不应直接由 UI 立即写入文件。

建议字段：

```text
source_song
selected_chart
template
segments
output_songs
pack
target_mode
target_path
conflicts
warnings
```

导出流程必须先生成 ExportPlan，再执行文件写入。

---

## 6. songlist 读写规范

## 6.1 原生格式

所有输出 songlist 必须是：

```json
{
  "songs": [
    {
      "id": "ascii_song_id"
    }
  ]
}
```

不允许把工具配置、自定义 schema、缓存字段写入该文件。

## 6.2 模板导入

用户可上传一个 JSON 格式 songlist 文件。

处理规则：

1. 文件必须是 UTF-8 JSON；
2. 顶层必须包含 `songs` 数组；
3. `songs` 为空时报错；
4. 只有一个 songs 项时，自动选中；
5. 多个 songs 项时，显示下拉列表供用户选择；
6. 下拉项至少显示：

   * `id`
   * 英文标题或可用标题
   * artist
   * set
7. 选中后将该项转换为 SongTemplate；
8. 不可识别字段保留为“待审查信息”，但不能默认写回输出。

## 6.3 模板规范化

工具应定义字段白名单和类型检查。

输出基础字段建议为：

```json
{
  "id": "",
  "title_localized": {
    "en": ""
  },
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

基础难度字段建议为：

```json
{
  "ratingClass": 2,
  "chartDesigner": "",
  "jacketDesigner": "",
  "rating": 0
}
```

可选字段按实际需要保留，例如：

* `ratingPlus`
* `source_localized`
* `source_copyright`
* `bg_inverse`
* `search_title`
* `search_artist`
* `jacketOverride`

不应默认保留或复制以下不适合练习副本的字段：

* `world_unlock`
* `remote_dl`
* `songlist_hidden`
* `byd_local_unlock`
* `hidden_until`
* `hidden_until_unlocked`
* 与官方解锁、远程下载、隐藏状态相关的字段

`purchase` 是否删除或改为空字符串，必须以目标壳的实际验证结果为准。未验证前不得假设“删除 purchase 字段一定安全”。

## 6.4 手动填写

手动填写与模板导入必须共用 SongTemplate 输出路径。

不得保留两套独立逻辑：

* “导入模板生成 songlist”；
* “手填面板生成 songlist”。

手动填写只应被视为构建 SongTemplate 的另一种来源。

---

## 7. 命名与唯一性规范

## 7.1 歌曲 ID

每个输出歌曲 ID 必须：

* 仅使用 ASCII；
* 在同一次导出中唯一；
* 与目标 songs 目录已有歌曲 ID 不冲突；
* 适合作为目录名；
* 不依赖中文、空格或特殊符号；
* 在导出计划阶段即可检测冲突。

建议格式：

```text
<source_id>_prc_<pack_short>_<segment_index>
```

示例：

```text
fractureray_prc_8f2c_01
fractureray_prc_8f2c_02
```

不得仅使用时间作为唯一 ID，因为重复导出、不同倍速、不同难度、不同曲包可能产生碰撞。

## 7.2 显示标题

输出标题应直观反映练习信息。

至少应包含：

* 原曲标题；
* 片段序号；
* 原曲起止时间；
* 倍速。

示例：

```text
Fracture Ray · 01 · 00:42.000–01:08.500 · 0.75x
```

Combo 模式可使用：

```text
Fracture Ray · Combo 350–620 · 0.75x
```

显示标题允许用户覆盖，但工具生成的默认名称必须始终清晰。

## 7.3 曲包 ID 与曲包名称

每次导出默认生成一个新练习曲包。

建议：

```text
pack_id: practice_<source_id>_<short_hash>
display_name: <原曲名> Practice
```

曲包 ID 必须是 ASCII。

曲包显示名称可使用原曲名与中文等 Unicode 文本。

---

## 8. packlist 与曲包封面规范

## 8.1 packlist 最小输出

普通练习曲包默认仅生成必要字段：

```json
{
  "id": "practice_xxx",
  "plus_character": -1,
  "name_localized": {
    "en": "Original Song Practice"
  },
  "description_localized": {
    "en": "Practice clips generated by Arc Slicer."
  }
}
```

默认不得生成：

* `pack_parent`
* `is_extend_pack`
* `is_active_extend_pack`
* `small_pack_image`
* `cutout_pack_image`

除非用户明确启用相应特殊功能。

## 8.2 封面文件规则

普通曲包封面默认路径：

```text
songs/pack/select_<pack_id>.png
```

注意：

* 文件名基于 `pack_id`，不是曲包显示名称；
* packlist 本身通常不保存封面路径字段；
* 输出目录必须包含 `pack/`，而不是 `packs/`。

## 8.3 封面生成

默认封面来源优先级：

1. `1080_base.jpg`
2. `1080_base_256.jpg`
3. `base.jpg`

封面生成流程：

1. 确定目标壳需要的 `select_*.png` 尺寸或比例；
2. 使用中心裁切；
3. 缩放到目标尺寸；
4. 输出 PNG；
5. 在 ExportPlan 中记录裁切来源、尺寸和最终路径。

后续可增加手动裁切区域调整，但首版不应依赖该功能才能生成可用封面。

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

位于 `start_ms` 或 `end_ms` 的 Tap、Hold 端点、Arc 端点和 Arctap 都允许保留；相邻片段共享边界事件可以接受。

输入片段必须满足：

```text
end_ms > start_ms
```

输出事件时间统一为：

```text
new_time = round((old_time - start_ms) / speed)
```

倍速规则已确定：

```text
输出 Timing BPM = 原 Timing BPM × speed
输出 songlist bpm_base = 原 bpm_base × speed
Timing beats 保持不变
```

单一数值形式的 songlist `bpm` 可同步缩放；复杂 BPM 字符串必须保留原样，不能误解析或破坏。

`AudioOffset` 的音频时间与 AFF 时间换算仍需后续独立实现。当前阶段应保留原 Header；检测到非零 `AudioOffset` 时只给出警告，不得伪称已经完全对齐。

### 9.3 Hold 与 Arc

切到 Hold 或 Arc 中间时：

* 不能只裁切起止时间；
* Hold 必须按闭区间裁切并换算起止时间；
* Arc 必须根据 easing 计算切点时的真实坐标，再生成新端点；
* 附着 Arctap 只保留在有效闭区间内的项；
* Arc 组关系必须重新检查；
* 不能因为切片产生非法 Arc。

对于持续 Arc：

```aff
arc(t1,t2,x1,x2,easing,y1,y2,...)
```

在任意时刻 `t` 的归一化进度为：

```text
p = (t - t1) / (t2 - t1)
```

坐标为：

```text
x(t) = x1 + (x2 - x1) × Ex(p)
y(t) = y1 + (y2 - y1) × Ey(p)
```

正常可读 AFF 的持续 Arc 应满足 `t1 < t2`。`t1 > t2` 不作为本项目的常规输入、测试目标或兼容承诺；解析器可进行防御性容错以避免崩溃，但不得据此推断其语义。

需要正式验证的是**坐标反向**：当 `x1 > x2` 和/或 `y1 > y2` 时，时间仍正向推进，easing 名称仍表示同一时间缓动；不得因为坐标差为负而交换 `si` / `so` 或反转 x/y easing。

零时长 Arc 不进入连续插值；作为点事件处理，避免除零。

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

特别规则：

```text
si = si s
so = so s
```

不存在 `ssi`、`sso`、`s si` 或 `s so`。坐标从大到小移动时，不得因此交换 `si` 与 `so`。

Arc 的 `x1/x2/y1/y2` 必须写成带小数点的浮点字面量。对当前 Arcaea 读取环境而言，Arc 坐标中的裸整数 `0`、`1` 不等价于 `0.00`、`1.00`，可能触发参数类型错误、导致事件被忽略或使游戏闪退。

因此输出建议统一使用六位小数：

```aff
arc(62,687,0.500000,-0.250000,si,0.000000,0.000000,0,none,false);
```

以下字段不得误写为浮点：

* Arc 时间 `t1/t2`；
* Arctap 时间；
* Timing 时间；
* `color`；
* `smoothness`。

### 9.5 非线性 Arc 的截断近似与 UI 警告

线性 `s` Arc 在中途截断后，只要重新计算首尾坐标并继续使用 `s`，内部轨迹可与原 Arc 完全一致。

但以下非线性 easing：

```text
b
si
so
sisi
siso
sosi
soso
```

在中途截断后，即使新 Arc 的起点和终点坐标均按原曲线计算，再沿用原 easing，也一般只能保证：

```text
切片两端不突跳
```

不能保证：

```text
切片内部每一个时间点的位置与原 Arc 局部严格一致
```

`siso`、`sosi` 等 x/y 使用不同 easing 的 Arc，空间轨迹本身也可能产生偏差。

Gate 0 必须在用户点击“运行切片”前扫描所有待输出时间段和 `2.aff`。若发现非线性 Arc 被**真正中途截断**，必须显示一次聚合 UI 确认对话框，而不是只写日志。

真正中途截断的判断：

```text
Arc 与切片窗口 [start_ms, end_ms] 相交
且 Arc 的至少一个时间端点位于窗口外
```

对持续 Arc，令：

```text
low  = min(t1, t2)
high = max(t1, t2)
```

则只要：

```text
low < start_ms
或
high > end_ms
```

即视为被截断。

以下情形不警告：

* `s` Arc；
* Arc 完整包含于窗口；
* Arc 仅贴合边界、没有裁去任何部分；
* 零时长 Arc。

扫描必须覆盖根层 Arc、Timinggroup 内 Arc、坐标反向 Arc 与带 Arctap 的 Arc。

不要求把 `t1 > t2` 作为正常谱面进行功能测试。若解析器遇到这类非标准输入，应以“不崩溃、不误删其他事件”为最低容错目标，而不是声称已正确还原其语义。

对话框至少包含：

* 受影响的片段编号；
* 被截断的非线性 Arc 总数；
* easing 类型统计；
* 说明“当前将按边界正确、内部近似的方式切片”。

用户必须能选择：

```text
继续近似切片
取消并返回修改时间段
```

默认不得静默继续。若用户确认继续，则按当前端点插值与原 easing 保留规则导出。

### 9.6 当前 Timing 兼容策略与后续相位保真边界

当前 Gate 0 的 Timing 策略目标是：让切片谱面可读、事件时间与倍速规则一致，并在切点处提供有效的根层与组内基础 Timing。

当前根层基础 Timing 策略：

* 切片输出补入有效的根层 `timing(0,bpm,beats);`；
* 当切片起点之后没有保留下来的根层 `timing(0,...)` 时，使用切点前最后一个根层 Timing 的 BPM 与 beats 生成该基础 Timing；
* 根层 Timing 搜索不得误用 Timinggroup 内 Timing。

当前 Timinggroup 策略：

* 对仍保留事件的 Timinggroup，保留原 flags；
* 若切片后不存在组内 `timing(0,...)`，使用切点前最后一个组内有效 Timing 补入；
* 若组内完全没有有效语句，可删除整个 Timinggroup；
* 根层 Timing 与组内 Timing 必须分别判断，不能相互替代。

该策略保证的是“BPM 与事件时间的局部可读性”，**不保证切片开始时的小节线相位与原谱完全连续**。原因是：把切点前生效 Timing 重置为输出 `0ms`，会保留 BPM 与拍间距，却可能丢失“切点位于原小节第几拍”的相位信息。

### 9.7 未来：Timing 相位、小节线与组内流速保真

本功能为独立正确性阶段，不并入 Gate 0，也不应被波形或试听功能替代。

需要同时保持的三个目标：

1. **音频对齐**：输出音频从用户选择的原曲切点开始；
2. **根层小节线相位**：根层（基础 Timing 作用域）的小节线/拍线在输出时间轴上与原谱切点后的拍位连续；拍线间隔由 BPM 与 beats 定义；
3. **Timinggroup Note 流速**：每个保留 Timinggroup 内 Note 的流速状态、后续 BPM 变化与原谱对应区间一致。

设：

```text
T = 某作用域中切点前最后一个生效 Timing 的原始锚点时间
S = 切片起点
B = 该 Timing 的原 BPM
v = speed
```

基础换算保持：

```text
输出 BPM B' = B × v
输出锚点 u_anchor = (T - S) / v
```

`u_anchor` 通常为负数。若目标壳实测接受根层与 Timinggroup 内的负时间 Timing，优先方案是：

1. 为根层与每个保留 Timinggroup 分别找到切点前生效的最后一个 Timing；
2. 保留其 BPM、beats 与作用域；
3. 将该 Timing 锚点变换到 `u_anchor`，即使其为负数；
4. 将切点后的 Timing 事件按同一时间换算平移，并将 BPM 乘以 `speed`；
5. 由负时间锚点自然继承根层小节线相位与组内 Note 流速。

若实测证明负时间 Timing 不可读、会闪退或无法保留预期相位，则采用“前导时间补偿”备选方案：

1. 根据切点距离原拍线/小节线的相位计算所需前导时长；
2. 在输出开头加入等长的无事件前导；
3. 将所有 AFF 事件与 Timing 整体后移；
4. 将音频播放起点以同样时长延后；
5. 仅在通过实际验证后，使用 AudioOffset 或等价方式完成音频延后；不得猜测 AudioOffset 的符号、单位或生效顺序。

本阶段的第一步不是直接改生产逻辑，而是建立最小实测谱：固定 BPM、可见拍线、根层与 Timinggroup 各一组，在原拍的 `1/4`、`1/2`、`3/4` 相位切片，并分别测试：

* 负时间根层 Timing 是否可读；
* 负时间 Timinggroup 内 Timing 是否可读；
* 1.0x、0.5x、2.0x 下拍线相位是否与音频拍点一致；
* 根层小节线与 Timinggroup 内 Note 流速是否同时保持；
* 若负 Timing 不可用，AudioOffset/前导补偿的实际方向与行为。

只有以上实测结论明确后，才能把该策略推广到普通谱面。
### 9.8 需要覆盖的语句

AFF 解析器最终至少必须识别：

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

后续 Combo 计算还必须理解：

* `noinput`
* `fadingholds`
* `anglex`
* `angley`
* Arc 组
* `true` Arc
* `designant` Arc

---

## 10. 功能版本规划

# Gate 0：切片核心校正与非线性 Arc 风险提示（收尾）

目标：完成已通过实机导入验证的 FTR 基础切片链路收尾，并让用户在非线性 Arc 近似切片前明确知情。

范围：

已完成并实机验证：

* 歌曲目录识别已排除 `songs/pack/`；
* speed 已限制为有限正数；
* 事件时间、Timing BPM 与 `bpm_base` 的倍速规则已固化；
* Arc 跨切点端点插值已实现；
* Arc 坐标已强制输出浮点字面量，禁止 `0` / `1` 等裸整数坐标；
* Timinggroup 与根层基础 Timing 已具备可读性补齐；
* AFF 回归测试集已建立；
* 非零 `AudioOffset`、Camera / Scenecontrol 已知限制已记录日志；
* 实机验证已确认切片歌曲可导入、可进入并开始游玩。

Gate 0 剩余必须项：

* 新增非线性 Arc 中途截断检测；
* 在运行前以 UI 聚合警告展示风险，并由用户选择继续近似切片或取消；
* 补充并执行对应自动测试与一次实机确认；
* 不实现非线性 Arc 高精度拟合，只保留其未来接口与测试边界。

验收标准：

* 对测试谱进行切片后，游戏可读取；
* 音频与谱面不明显错位；
* 切在 Arc/Hold 中间不会产生非法 AFF；
* Arc 坐标不会因输出为裸整数而被制谱器或游戏拒绝；
* 当前基础 Timing 与倍速下谱面可读、节拍间隔合理；“切点小节线相位与原谱连续”的严格保真不属于 Gate 0，转入独立 Timing 相位阶段；
* `pack/` 不会出现在歌曲选择列表中；
* `s` Arc 被截断时不触发非线性警告；
* 非线性 Arc 完整包含于窗口时不触发警告；
* 非线性 Arc 真正被截断时必须先弹出 UI 确认；
* 用户取消后不得创建该次导出文件；
* 用户确认后按当前近似规则完成导出。

---

# Version 2.1：完整练习曲包导出

功能范围：

* 导入 songlist 模板；
* 单项自动选择、多项下拉选择；
* 手动填写 SongTemplate；
* songlist 标准化读写；
* 自动生成唯一歌曲 ID；
* 自动生成直观显示标题；
* 自动生成新 packlist；
* 自动生成曲包封面；
* 输出完整的 `out/` 练习曲包目录。

输出结构：

```text
out/
├── songlist
├── packlist
├── pack/
│   └── select_<pack_id>.png
└── songs/
    ├── <segment_id_01>/
    │   ├── base.ogg
    │   ├── 1080_base.jpg
    │   ├── 1080_base_256.jpg
    │   └── <selected_difficulty>.aff
    └── <segment_id_02>/
```

验收标准：

* 用户不手工编辑 JSON，也能生成完整练习曲包；
* 所有输出歌曲归属同一新曲包；
* 输出 songlist、packlist 为合法 JSON；
* 每个输出歌曲 ID 唯一；
* 每个曲包封面路径和文件命名正确；
* 结果可整体复制到目标壳的 songs 根目录进行验证。

---

# Version 2.2：安全合并至目标目录

功能范围：

* 用户可指定目标 songs 根目录；
* 自动读取目标 `songlist`、`packlist`、`pack/`；
* 生成导入预览；
* 检测歌曲 ID、曲包 ID、封面文件冲突；
* 使用 staging 临时目录完成导出；
* 用户确认后才写入目标；
* 支持生成备份或至少保留写前副本。

默认策略：

* 不覆盖已有同名歌曲；
* 不覆盖已有曲包；
* 不修改 `unlock`；
* 冲突必须显式提示；
* 不允许静默直接修改源文件。

验收标准：

* 用户可在写入前清楚看到新增和冲突内容；
* 失败时目标目录保持可用；
* 成功后新曲包可在目标壳中被识别。

---

# Version 2.2.5：Timing 相位与原谱流速保真

定位：这是输出正确性功能，不是 UI 体验增强；应在安全合并之后、波形与循环试听之前完成。

功能范围：

* 保留根层小节线/拍线在切片起点处的原始相位；
* 保留各保留 Timinggroup 内 Note 的初始流速与后续 Timing 变化；
* 支持 1.0x、0.5x、2.0x 等 speed 下的统一 BPM、时间和相位换算；
* 为根层与每个 Timinggroup 分别维护“切点前最后一个生效 Timing”的状态；
* 先通过最小测试谱验证负时间 Timing；
* 若负时间 Timing 不可行，再实现经过实测的前导时间 + AudioOffset/等价补偿方案；
* 不在未经实机验证时改变现有 Gate 0 兼容输出策略。

实施顺序：

1. 固定 BPM 的根层拍线相位实验；
2. 多段 Timing 与变拍号实验；
3. Timinggroup 内独立 Timing 与 Note 流速实验；
4. 0.5x / 1.0x / 2.0x 的相位一致性实验；
5. 仅在负时间 Timing 不可用时，实现前导时间与 AudioOffset 兜底。

验收标准：

* 从非正拍切点开始切片时，输出拍线在相同音乐拍位出现，而不是在输出 `0ms` 被错误重置；
* 根层小节线间隔与原谱对应区间一致；
* 各 Timinggroup 中的 Note 流速与原谱对应区间一致；
* 倍速下音频拍点、根层拍线、组内 Note 流速三者一致；
* 负时间 Timing 或前导补偿路径均经过目标壳实际验证；
* 失败时保留 Gate 0 的可读兼容输出，不输出半成品相位逻辑。

---

# Version 2.3：波形与双端拖拽选段

功能范围：

* 从 `base.ogg` 提取或缓存波形；
* 每个片段显示双端拖拽选区；
* 开始、结束数值输入与拖拽双向同步；
* 显示当前片段时长；
* 支持缩放、平移或至少支持较长歌曲的有效定位。

限制：

* 拖动波形时不得反复触发真实 ffmpeg 导出；
* 波形缓存应在源曲切换时失效；
* 数字输入仍必须保留，不能只依赖鼠标操作。

验收标准：

* 用户无需反复手算毫秒即可完成常规选段；
* 拖动后数值输入正确更新；
* 手工输入后波形选区正确更新；
* 不影响已有导出结果。

---

# Version 2.4：循环试听

功能范围：

* 播放源 `base.ogg` 的当前选区；
* 调整区间后自动循环试听；
* 提供自动试听开关；
* 防止拖动过程中频繁重启播放；
* 切换片段时停止旧片段。

建议行为：

* 停止拖动约 150–300ms 后再启动试听；
* 到达结束点自动跳回开始点；
* 试听使用源音频，不重新生成临时切片音频。

验收标准：

* 能通过听觉确认切点；
* 循环边界与当前区间一致；
* 不影响导出速度和文件内容；
* 打包 EXE 环境下 OGG 播放稳定。

---

# Version 2.5：Combo 切片与多难度选择

功能范围：

* 用户选择源难度，而非固定 FTR；
* 支持时间模式与 Combo 模式；
* 根据 AFF 计算 Combo 与对应时间点；
* Combo 区间自动转换为时间区间；
* 显示 Combo 起止值；
* 输出标题可体现 Combo 信息；
* 可选择 PST / PRS / FTR / BYD / ETR 中实际存在的谱面。

Combo 计算必须覆盖：

* Tap；
* Arctap；
* Hold；
* Arc；
* Arc 组；
* TimingPointDensityFactor；
* BPM 特殊规则；
* noinput Timinggroup；
* true / designant Arc；
* 跨 Timing 的 Hold 与 Arc。

验收标准：

* 输入 Combo 区间后可得到正确时间区间；
* 生成切片的实际 Combo 与预期范围一致；
* 不同难度选择输出正确的 AFF 文件和 `ratingClass`；
* 不因 noinput、Arc 组等特殊结构明显错误计数。

---

# Version 2.6：本地官谱资料库

功能范围：

* 用户选择本地官方 songs 根目录；
* 扫描可用 songlist、packlist、歌曲目录；
* 建立本地索引；
* 允许直接搜索和选择可读取官方歌曲；
* 自动匹配歌曲 metadata 模板；
* 自动使用当前工具规则生成练习曲包；
* 不复制官方 packlist 到输出。

匹配优先级：

1. 歌曲目录 ID；
2. songlist 中的 ID；
3. 精确标题；
4. 本地化标题或别名；
5. 多结果时用户手动选择。

验收标准：

* 用户无需自行导出官方 songlist 才能生成练习曲包；
* 匹配不到时不猜测错误数据；
* 有歧义时必须提示选择；
* 输出仍使用新建练习 packlist 与封面。

---

# Version 3.0：谱面预览

功能范围：

* 独立 AFF 渲染或接入可靠外部渲染模块；
* 显示 Tap、Hold、Arc、Arctap；
* 与当前时间选区同步；
* 辅助确认切点与谱面内容；
* 不作为导出核心依赖。

架构要求：

```text
AFF Parser
→ Normalized Chart Model
→ Slicer / Combo Calculator
→ Preview Renderer
```

预览模块不得反向决定切片正确性。

验收标准：

* 即使预览模块关闭或异常，导出功能仍可用；
* 预览与实际 AFF 时间一致；
* 不以简单“静态 Note 图”冒充完整谱面预览。

---

# Future 专项：非线性 Arc 高精度分段拟合

目标：减少 `b / si / so / sisi / siso / sosi / soso` Arc 被中途截断后，因重新套用同一 easing 而产生的局部轨迹误差。

原缓动函数 `F` 截取 `[a,b]` 区间后，其严格等价的局部函数为：

```text
G(q) = [F(a + (b-a)q) - F(a)] / [F(b) - F(a)]
```

但 AFF 只能写固定 easing 名称，不能直接表达任意 `G(q)`。因此一条非线性 Arc 的局部片段通常无法用一条标准 Arc 严格等价地重建。

未来方案应采用：

```text
自适应采样
+
多段短 Arc 逼近
```

建议流程：

1. 对被截断的非线性 Arc 建立原始位置函数；
2. 在切片保留区间内采样；
3. 以误差阈值递归细分；
4. 将相邻采样点输出为多段短 Arc；
5. 在每一段上选择可接受的 AFF easing，首版可优先使用 `s`；
6. 保留 color、hitsound、arctype、smoothness、Timinggroup flags；
7. 将 Arctap 归属到正确的分段 Arc；
8. 对坐标反向 Arc 保持原 easing 语义，不因 x/y 方向相反而交换 `si` / `so`；
9. 对每段 Arc 坐标保持浮点字面量；
10. 以位置误差、Arctap 位置、游戏实机观感和 AFF 可读性验证结果。

该专项完成前，当前 UI 警告仍必须保留；不得因为存在未来拟合计划而把当前近似输出宣传为严格等价。

---

## 11. UI 要求

### 11.1 必须保留的基本操作

* 选择 songs 根目录；
* 选择源歌曲；
* 选择源难度；
* 新增、删除片段；
* 数字输入开始与结束时间；
* 设置每片段倍速；
* 选择元数据来源；
* 查看输出计划；
* 导出到独立目录；
* 合并至目标目录；
* 查看日志和错误。

### 11.2 元数据来源 UI

建议在界面中明确展示：

```text
元数据来源：
○ 导入 songlist 模板
○ 手动填写
○ 本地官方资料库
```

三个来源最终必须生成同一个 SongTemplate，不允许各自生成不同格式的 songlist。

### 11.3 导出前预览

导出前至少展示：

* 曲包 ID 与显示名；
* 输出歌曲数量；
* 每个输出歌曲 ID；
* 每个显示标题；
* 片段时间 / Combo；
* 倍速；
* 将复制的资源；
* 冲突与警告。


### 11.4 非线性 Arc 截断警告

运行前必须完成一次 AFF 风险扫描。

若扫描到非线性 Arc 被真正中途截断，UI 必须：

* 在启动 worker 与任何 ffmpeg 写入前弹出确认对话框；
* 聚合展示受影响片段数、Arc 数和 easing 类型统计；
* 明确说明：当前输出保证切片边界位置正确，但内部轨迹属于近似；
* 提供“继续近似切片”和“取消并返回修改时间段”；
* 取消时不创建输出文件、不启动 worker；
* 继续时将本次确认结果传递给导出流程，避免 worker 内再次弹窗。

禁止只在日志中提示或为每条 Arc 连续弹出单独对话框。


---

## 12. 错误处理与安全要求

必须明确处理：

* 找不到 `base.ogg`；
* 找不到选择的 AFF；
* AFF 无法解析；
* 时间段结束小于等于开始；
* 倍速小于等于 0；
* songlist JSON 不合法；
* songlist 缺少 songs；
* 曲包 ID 非 ASCII；
* 输出歌曲 ID 冲突；
* 目标目录 songlist 或 packlist 不合法；
* ffmpeg 不存在或调用失败；
* 封面生成失败；
* 当前歌曲目录没有有效曲绘；
* 官谱元数据匹配存在歧义。

所有会修改目标目录的操作必须：

1. 先生成 ExportPlan；
2. 先验证；
3. 再写入 staging；
4. 最后确认写入；
5. 出错时尽可能保持目标目录不变。

---

## 13. 测试要求

## 13.1 AFF 回归测试集

至少准备以下测试谱：

* 只有 Tap；
* Hold 跨越切点；
* Arc 跨越切点；
* 带 Arctap 的 Arc；
* 多段 Timing；
* Timinggroup；
* noinput Timinggroup；
* 非零 AudioOffset；
* TimingPointDensityFactor；
* 不同倍速；
* PST / PRS / FTR / BYD / ETR；
* 含 Camera 与 Scenecontrol；
* 极短片段；
* 切点恰好落在物件时间上；
* 坐标反向 Arc：`x1 > x2`、`y1 > y2` 与双轴同时反向，确认 easing 不被翻转；
* 不将 `t1 > t2` 作为正常谱面兼容测试；如遇非标准输入，仅测试解析器不崩溃和不误删无关事件；
* 非线性 Arc 警告的聚合统计、取消与确认路径；
* Timing 相位专项最小谱：非正拍切点、根层 Timing、Timinggroup 内 Timing、1.0x / 0.5x / 2.0x、负时间 Timing 兼容性与前导补偿兜底。

## 13.2 元数据测试

至少验证：

* 单项 songlist 模板；
* 多项 songlist 模板；
* 缺少可选字段；
* 含官方特殊字段；
* 非法字段类型；
* 重复歌曲 ID；
* 重复曲包 ID；
* 中文标题；
* ASCII ID 生成；
* packlist 封面文件名。

## 13.3 导入测试

至少验证：

* 独立输出目录可正常导入；
* 合并至已有 songs 目录；
* 发生冲突时不破坏已有文件；
* 失败中断时不留下半写入 JSON；
* Windows 打包 EXE 环境；
* ffmpeg 内置与系统 PATH 两种环境。

---

## 14. 非目标

在以下版本完成前，本项目不追求：

* 编辑、创作或重写完整 AFF；
* 修改 unlock；
* 自动生成 World 解锁；
* 支持加密或不可读取官方谱面；
* 自动发布/分发完整游戏资源；
* 用谱面预览替代真实游戏内验证；
* 在 Future 专项完成前，把非线性 Arc 截断宣称为严格数学等价；
* 默认覆盖已有歌曲或曲包；
* 以“看起来能运行”为标准代替可导入验证。

---

## 15. 待决事项

以下问题必须在对应功能实施前确认，不能由开发者自行猜测。

### 15.1 切片、AudioOffset 与 Timing 相位

* 时间输入最终应以音频播放时间还是 AFF 时间定义？
* AudioOffset 正负方向如何与 ffmpeg 音频裁切对应？
* 输出 AFF 是否保留、重写或删除 AudioOffset？
* 目标壳是否允许根层负时间 Timing？是否允许 Timinggroup 内负时间 Timing？
* 根层小节线相位的实际来源、beats 参数与目标壳显示行为是否与最小实验一致？
* 若负时间 Timing 不可用，前导时间应锚定到上一拍、下一拍还是小节线；其与 AudioOffset 的组合规则是什么？

在上述规则通过专门实验确定前，当前版本保留原 `AudioOffset` 并提示风险，不得擅自缩放、删除或用其伪造相位对齐。

### 15.2 倍速规则

已确定：

* AFF 事件时间按 `1 / speed` 缩放；
* Timing BPM 与 `bpm_base` 必须乘以 `speed`；
* 单数值 `bpm` 可乘以 `speed`；
* 区间或复杂 BPM 字符串保留原样。

仍待后续版本确认：

* 每片段是否允许独立倍速；
* 显示标题中 BPM 与 speed 的呈现方式。

### 15.3 标题规则

* 标题默认显示时间、Combo、倍速的精确格式；
* 时间保留毫秒、百分秒还是秒；
* Combo 模式下是否同时显示时间；
* 用户手动覆盖标题后，是否仍保留内部练习标记。

### 15.4 曲包封面规格

* 目标壳实际 `select_<pack_id>.png` 的尺寸；
* 是否存在固定比例；
* 是否需要额外小图或 cutout 模式；
* 默认中心裁切是否足够。

### 15.5 purchase 与兼容字段

* 当前目标壳中 `purchase` 缺失是否可用；
* 空字符串、默认值或其他写法何者最安全；
* 输出是否保留 `version`；
* 是否需要保留 `source_localized` 等来源信息。

---

## 16. 开发执行顺序

```text
Gate 0：补齐并验证非线性 Arc 风险提示后关闭
↓
Version 2.1：完整练习曲包导出
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
Version 2.6：本地官谱资料库
↓
Version 3.0：谱面预览
↓
Future 专项：非线性 Arc 高精度分段拟合
```

开发中不得跳过 Gate 0 直接堆叠 UI 功能。

任何新功能进入开发前，应先回答：

1. 它依赖哪些已有数据模型？
2. 它是否影响输出正确性？
3. 它的异常路径是什么？
4. 它如何在当前版本独立交付？
5. 它的验收方式是什么？
6. 它是否会破坏已有游戏数据？
