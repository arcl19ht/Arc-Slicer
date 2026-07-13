# Arc Slicer 当前开发状态

## 文档范围

- 当前稳定版本：V2.4
- V2.3 截止提交：`8316bba feat(v2.3): add timeline quick draft gesture`
- main 稳定基线：`d7bbaed`（V2.4 PR #4 合并）
- V2.4 收口文档提交：`9ff4f05 docs: close v2.4 and plan multi-difficulty slicing`
- 测试基线：378 passed，12 skipped，75 subtests passed。

历史需求书和 V2.3 实施计划保留其当时的设计上下文，不作为当前状态判断依据。

## V2.2 已完成

- AFF 与 `base.ogg` 切片、任意正数倍速和片段级倍速覆盖。
- `current_export` 与 `library_export`、songlist/packlist、曲包封面和固定 section 选项。
- 外部目标壳 `songs` 根目录的安全合并：验证目标、检查计划、显式确认、备份、manifest、失败恢复和目标目录记忆。

## V2.3 已完成

- `WaveformData`、波形缓存、波形/时间标尺/timeline lanes。
- 空白区拖拽创建、端点编辑、草稿预览和 Ctrl+单击快速草稿。
- 卡片与时间线 selected/hovered 联动，自动/手动排序。
- `uid` 与 `link_group_id`，断链、重连和级联区间编辑。
- 撤销/重做，以及 Delete、Backspace、Ctrl+S、Ctrl+D 快捷键。

## V2.4 已完成

### V2.4-A 手动试听

- 使用源 `base.ogg` 对完整选中片段播放、暂停和恢复。
- 支持循环、有效倍速、空格快捷键和波形播放头。
- 不生成临时试听音频，不影响 AFF、导出、dirty 或历史。

### V2.4-B 防抖自动试听

- 自动试听默认关闭且不持久化。
- 正式编辑提交后按 200ms 防抖安排试听。
- 显式选择完整卡片或时间线片段同样安排试听；快速连续选择只播放最后一个片段。
- 手动播放、输入编辑、拖动、删除、切歌和关闭窗口均取消 pending。

### V2.4-C EXE/OGG 稳定性与时间线交互

- 修复显式选择片段未安排自动试听的问题。
- 修复时间线选择推动主页面跳到对应卡片的问题。
- 未选中时间线片段首次点击只选择和高亮；自动试听开启时从片段起点试听，主页面不滚动。
- 短点击已选中片段会定位播放头并立即播放，不修改区间、dirty 或历史。
- 拖动已选中片段主体会整体平移，保持长度、限制音频边界、同步级联组，并只提交一次历史；最终状态只自动试听一次。
- endpoint handle 继续优先于主体点击和平移；循环到终点仍回到完整片段的原始起点。

### UI Clarity

- 自动排序、循环和自动试听使用真实 switch；表单与导出选择使用方形勾选框。
- 主按钮、禁用态、下拉箭头和播放工具栏的视觉语义已完成 Windows 源码环境人工验收。

## 人工验收

- Windows 源码环境听感验收通过。
- Windows 源码环境 UI 视觉验收通过。
- Windows EXE 最终人工验收通过，包括真实 OGG 播放、手动/自动试听、循环、倍速、选择防抖、定位播放、整体及级联平移、撤销/重做与 viewport 稳定性。
- 最终 EXE 构建成功，SHA-256：`6F314CDB5DE1F479E1F06A506A63B7BC29C5D8D93BB7278307E5FEACF56B37F9`。

## 当前开发：V2.5-B 多难度选择与正式导出

V2.5-B 已接入主界面、slides、试听音源选择和正式写盘流程，尚待 Windows 源码 UI、真实多 AFF/OGG 切片与目标壳兼容的人工作业验收。曲目卡片之后、timeline 之前显示发现的标准难度；选择与每难度 metadata 按歌曲保存。每段输出始终只有一个目录与一个 song ID，包含一次 `base.ogg`、选中的 AFF 和可用的选中 `N.ogg`；songlist 聚合为一个 `difficulties` 数组。0/1/2 保留兼容占位，3/4 仅在实际选中时写入。试听音源可在 `base.ogg` 与有效专属音源间切换，不会改写 canonical base duration 或 slides。合法但无事件的 AFF 头部（如 `AudioOffset:-30` 加 `-`）仍作为真实难度处理。Waveform worker 的结果信号不再提前释放运行线程；关闭会等待所有 active waveform worker 完成。手动 Space/播放按钮在试听 spec 未变化时暂停和原位恢复。`audioOverride` 继续由目录派生，`jacketOverride` 尚未实现；V2.5-C 尚未开始。

当前分支：`feature/v2.5-multi-difficulty-export`。V2.5-A 已提供单一难度定义、目录发现、选择规范化、旧 slides 兼容解析、每难度元数据迁移、缺失/未知难度报告和多难度导出/单条 songlist 聚合计划；V2.5-B 已接入 UI 与正式写盘。

已确认标准映射：`0.aff` = Past/PST/ratingClass 0，`1.aff` = Present/PRS/ratingClass 1，`2.aff` = Future/FTR/ratingClass 2，`3.aff` = Beyond/BYD/ratingClass 3，`4.aff` = Eternal/ETR/ratingClass 4。以目录实际存在的普通可读文件为准：任意 0–4 子集都合法，不要求 0/1/2 同时存在，3/4 同时存在也合法；未知名称 `.aff` 单独报告且不参与计划。

新导入歌曲默认选择全部已发现难度。旧 slides 缺少选择字段时，若有 `2.aff` 则恢复为 `[2]`，否则恢复全部可用难度；显式空选择或已选文件缺失保持错误状态，不会静默全选或删除。选择是歌曲级状态，不复制到片段。

`N.aff` 与可用 `N.ogg` 同时存在时，N 具有派生的 `audioOverride: true`；它不是用户输入，不保存到 slides。孤立或不可用的 `N.ogg` 产生明确 warning，不成为 available difficulty，也不进入计划。音频不变量已修正为“每个片段、每个不同源音频一条操作”：每片段始终有 `base.ogg`，并为每个实际选中且可用的专属 `N.ogg` 另建一条操作。

V2.5-A 保持当前正式 FTR 导出和 songlist `ratingClass 0/1/2` 兼容占位不变。这些 compatibility entries 不等于物理 AFF 可用性或 V2.5-B 的已选 chart outputs。单条 songlist 计划会将一个片段的所有真实选中难度聚合到一个 song ID 和一个 difficulties 数组；0/1/2 未选中或不存在时为 `rating = -1` 占位，3/4 仅在实际选中时出现。可选难度标题覆盖独立于 `audioOverride`，空白或与普通标题相同则省略；不从音源推导 `jacketOverride`。

V2.5-B 将负责难度选择 UI、持久化、多 AFF 切片、多难度导出和 songlist difficulties；V2.5-C 将负责缺失难度、真实歌曲、外部测试壳与 Windows EXE 验收。每个片段/倍速的 `base.ogg` 必须只切一次，既有 segment export ID 和 external merge 安全边界保持不变。

## 已取消 / 不计划

Combo snapping 已取消，原因是当前用户需求和实际收益不足。近期不实现 combo 时间解析、端点吸附、snapping UI 或 snapping 配置；除非未来出现新的明确用户需求，不得自行恢复。

## 远期候选

- 谱面预览：等待独立需求评估，不承诺版本号。

## 尚未实现

- 多难度切片。
- 官方曲包封面 / topbar 资源库。

## V2.5-B 验证状态

自动化边界校验已补齐：导入会在链接或复制前验证可读 `base.ogg` 和至少一个标准 AFF；试听 `N.ogg` 使用独立时长且不会覆盖 canonical base duration；任何实际导出音源在 staging 前逐一探测并校验全部片段终点。已保存但缺失的难度会显示明确状态并可单独清除，元数据保留。另已覆盖 waveform QThread 生命周期、暂停/恢复和无事件合法 AFF。Windows 源码、真实歌曲和 EXE 人工验收仍待执行。

## 文档更新规则

每次版本收口后，同步更新 `README.md`、`AGENT.md` 和本文档，并明确区分“已经实现”“正在开发”“尚待人工验收”“已取消”和“远期候选”。
