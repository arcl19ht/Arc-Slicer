# Arcaea AFF 谱面格式参考

> 本文根据 AFF 格式介绍整理，用于理解和审查谱面读取、切片、重写与导出逻辑。
> 本文描述的是格式与行为参考，不应将“能生成 `.aff` 文件”直接视为“输出谱面语义正确或一定可被游戏正常读取”。

---

## 1. 总论

Arcaea 谱面的后缀名为 `.aff`。

所有安装包中的官方未加密谱面，包括常规曲包中无需世界模式解锁的 PST / PRS / FTR / ETR 难度，以及愚人节版本中的愚人节谱面，通常可以直接阅读。

### 1.1 谱面所在位置

* Android APK：`assets/songs/<曲目id>/`
* iOS IPA：`Payload/Arc-mobile.app/songs/<曲目id>/`

常见难度文件编号：

| 文件编号 | 难度 |
| -------- | ---- |
| `0.aff`  | PST  |
| `1.aff`  | PRS  |
| `2.aff`  | FTR  |
| `3.aff`  | BYD  |
| `4.aff`  | ETR  |

其他文件的用途需要结合实际包体内容确认。

理论上，修改 `.aff` 文件及对应音源后，重新正确封包即可游玩。

### 1.2 谱面不包含的信息

`.aff` 文件本身通常**不包含**以下歌曲元数据：

* 曲名
* 难度等级
* 谱师
* 曲包归属
* 解锁条件

这些信息分别需要参考：

* `songlist`：歌曲信息
* `unlocks`：解锁条件
* `packlist`：曲包信息

---

## 2. 文件总体结构

AFF 文件通常由三部分构成：

```text
标识信息
-
正常 AFF 语句
```

其中，第一个**单独成行的 `-`** 是分隔符。

* 分隔符之前为标识信息区。
* 分隔符之后为正常 AFF 语句区。
* 标识信息与普通 AFF 语句的排序通常不受限制。
* 同类型标识信息或同一时间点的 AFF 语句可能受排序影响。

---

## 3. 标识信息

### 3.1 `AudioOffset`

官方谱面通常会包含：

```aff
AudioOffset:x
```

| 字段 | 类型 | 含义                                           |
| ---- | ---: | ---------------------------------------------- |
| `x`  |  int | 谱面整体向前（负值）或向后（正值）偏移的毫秒数 |

通常 `x = 0`。此时谱面中物件的时间值直接对应歌曲播放进度的毫秒数。

当 `x ≠ 0` 时，物件在音乐中实际对应的时间会受到该偏移影响。由于有些音源的第一个采音点未必在整拍上，官方谱面有时会使用非零偏移。

删除这一行通常不会使游戏崩溃，但会影响谱面与音频的对齐逻辑。

### 3.2 `TimingPointDensityFactor`

有些谱面会包含：

```aff
TimingPointDensityFactor:y
```

| 字段 |        类型 | 含义                                    |
| ---- | ----------: | --------------------------------------- |
| `y`  | int / float | 全局实体 Arc 和 Hold 的物量密度调整倍率 |

规则：

* 缺失时默认值为 `1`。
* 最小值为 `0`。
* 该值会影响 Hold 和实体 Arc 的判定块密度与物量计算。

### 3.3 自定义标识信息

在第一个 `-` 之前可以写入自定义标识信息，例如：

```aff
ChartVersion:2
```

游戏通常可以读取和记录这类信息，但未必产生实际效果。

---

## 4. 时间与基本约束

### 4.1 时间单位

AFF 中绝大多数时间字段使用：

* 单位：毫秒（ms）
* 类型：整数（int）

通常要求：

* 点事件时间 `t >= 0`
* 区间事件时间 `t1 <= t2`

部分特殊 Arc 类型可能允许 `t1 > t2`，详见 Arc 章节。

### 4.2 切片工具应重点关注的时间语义

对谱面切片、变速、时间偏移而言，应区分：

| 类别     | 示例                              | 处理原则                                                           |
| -------- | --------------------------------- | ------------------------------------------------------------------ |
| 点事件   | Tap、Arctap、Camera、Scenecontrol | 判断事件时间是否在切片区间内，再进行时间偏移                       |
| 区间事件 | Hold、Arc、Camera 持续效果        | 判断与切片区间是否相交，必要时裁剪区间端点                         |
| 状态事件 | Timing、Scenecontrol、Header 信息 | 不能只按“事件是否落在区间内”处理，可能需要继承切片开始时的有效状态 |
| 嵌套块   | Timinggroup                       | 需要分别处理块属性、内部 Timing 和内部物件                         |

---

## 5. Timing

### 5.1 语法

```aff
timing(t,bpm,beats);
```

| 字段    |  类型 | 含义                       |
| ------- | ----: | -------------------------- |
| `t`     |   int | Timing 起始时间            |
| `bpm`   | float | 流速，单位为拍 / 分钟      |
| `beats` | float | 每多少个四分音符构成一小节 |

每个 Timing 会在 `t` 处生成一条小节线。

### 5.2 `beats` 的约束

当 `bpm ≠ 0` 时：

* `beats` 不可为 `0`。
* 例如 `4.00` 表示 4/4 拍，即四拍一小节。

若 `beats = 0`，可能导致除零错误并使游戏崩溃。

### 5.3 基础合法性要求

每张谱面必须至少存在一个：

```aff
timing(0,bpm,beats);
```

该 Timing 必须满足：

* 位于 Timinggroup 外；
* `t = 0`；
* `bpm >= 0`；
* `beats >= 0`。

否则谱面可能无法被正常读取。

### 5.4 切片时的注意事项

切片输出通常需要确保：

1. 切片起点 `0ms` 有一个有效的外层 Timing；
2. 该 Timing 应继承原谱面在切片起点实际生效的 BPM 与 beats；
3. Timinggroup 内的 Timing 不应被误当作外层小节线 Timing；
4. 切片后的 Timing 时间需要与音频变速结果一致。

---

## 6. 地面音符：Tap 与 Hold

### 6.1 Tap

语法：

```aff
(t,lane);
```

| 字段   |         类型 | 含义                 |
| ------ | -----------: | -------------------- |
| `t`    |          int | Tap 所在时间         |
| `lane` | 0～5 / float | Tap 所在轨道或横坐标 |

### 6.2 Hold

语法：

```aff
hold(t1,t2,lane);
```

| 字段   |         类型 | 含义                  |
| ------ | -----------: | --------------------- |
| `t1`   |          int | Hold 开始时间         |
| `t2`   |          int | Hold 结束时间         |
| `lane` | 0～5 / float | Hold 所在轨道或横坐标 |

当 `t1 = t2` 时，Hold 物量为 `0`。

### 6.3 轨道编号与浮点轨道

整数轨道从左到右为：

```text
0, 1, 2, 3, 4, 5
```

通常仅使用 `1～4` 轨。

启用 `enwidenlanes` 后：

* 1 轨左侧新增 0 轨；
* 4 轨右侧新增 5 轨；
* 可形成六轨布局。

`lane` 也可以是 float，表示基于坐标的位置。

整数轨道向 Arc 横坐标的映射：

```text
x = (lane - 0.5) / 4
```

Arc 横坐标向轨道坐标的映射：

```text
lane = (x + 0.5) / 2
```

浮点轨道的判定与普通轨道不同，通常更适合演出用途而非普通 Tap / Hold。

### 6.4 切片时的注意事项

对 Hold 切片时：

* 若 Hold 与切片区间无交集，应删除；
* 若 Hold 跨越切片左边界，应将开始时间裁剪为切片起点；
* 若 Hold 跨越切片右边界，应将结束时间裁剪为切片终点；
* 裁剪后应保证 `t1 <= t2`；
* 若切片后时间重映射，应对两个端点同时应用相同速度变换。

---

## 7. 音弧：Arc 与天空音符：Arctap

### 7.1 Arc 基本语法

```aff
arc(t1,t2,x1,x2,easing,y1,y2,color,hitsound,arctype,*smoothness);
```

带 `*` 的参数为可选参数。

| 字段         |        类型 | 含义                 |
| ------------ | ----------: | -------------------- |
| `t1`, `t2`   |         int | Arc 开始、结束时间   |
| `x1`, `x2`   |       float | Arc 起点、终点横坐标 |
| `easing`     |      string | Arc 滑动方式         |
| `y1`, `y2`   |       float | Arc 起点、终点纵坐标 |
| `color`      |         int | Arc 颜色             |
| `hitsound`   |      string | Arctap 特殊打击音效  |
| `arctype`    |      string | Arc 类型             |
| `smoothness` | float，可选 | Arc 分段平滑度       |

### 7.2 时间字段

通常：

```text
t1 <= t2
```

当 `t1 = t2` 时：

* Arc 与判定线平行；
* 物量为 `0`；
* 可用于连接 Arc 组；
* 宏观上可视作连续 Arc 的连接段，不能换手。

仅当以下情况时可出现 `t1 > t2`：

* `skylineBoolean = true`
* `arctype = designant`

### 7.3 横纵坐标

| 字段       | 含义                     |
| ---------- | ------------------------ |
| `x1`, `x2` | Arc 开始、结束时的横坐标 |
| `y1`, `y2` | Arc 开始、结束时的纵坐标 |

### 7.4 缓动类型 `easing`

常见有效值：

```text
b
s
si
so
sisi
siso
soso
sosi
```

说明：

| 值   | 含义     |
| ---- | -------- |
| `b`  | Bezier   |
| `s`  | Straight |
| `si` | Sine Out |
| `so` | Sine In  |

若不是上述值，通常会被视作 Straight。

当 `t1 = t2` 时，缓动参数通常无意义。

组合形式如：

```text
siso
```

可表示 x 方向与 y 方向采用不同的缓动类型。

### 7.5 颜色 `color`

|   值 | 颜色 |
| ---: | ---- |
|  `0` | 蓝   |
|  `1` | 红   |
|  `2` | 绿   |
|  `3` | 灰   |

其他数值通常显示为黑色。

注意：

* `arctype = true` 时，颜色字段通常无意义；
* 绿色 Arc 的兼容性受游戏版本与谱面类型影响；
* `color = 3` 在较新版本中可出现横缩放 Arctap 形态。

### 7.6 特殊打击音效 `hitsound`

`hitsound` 于 v4.0.0 实装，用于为该 Arc 上的所有 Arctap 指定特殊音效。

示例：

```aff
arc(...,glass_wav,true)[arctap(...)];
```

这会尝试使用：

```text
songs/<songid>/glass.wav
```

作为打击音效。

常用值：

```text
none
```

表示不应用特殊音效。

即使当前 Arc 没有 Arctap 或不是音轨类型，`hitsound` 也不应随意填写，以避免兼容性问题。

### 7.7 Arc 类型 `arctype`

常见值：

| 值          | 含义                |
| ----------- | ------------------- |
| `false`     | 普通音弧            |
| `true`      | 音轨                |
| `designant` | 特殊 Designant 音轨 |

无效值通常按 `false` 处理。

若 Arc 带有 Arctap，除 `designant` 外通常视为 `true`。

`designant` 类型：

* 表现为偏粉红的音轨；
* Arc 上的 Arctap 也会染色；
* 其 Arctap 不计入总 Combo；
* 击打时不增加 HP；
* 通常只在特定演出场景中生效；
* 某些旧版本会将其视为 `false`。

### 7.8 平滑度 `smoothness`

于 v6.8.0 新增。

```text
smoothness >= 1
```

作用：

* 控制 Arc segment 的细分数量；
* 默认值与最小值均为 `1`。

### 7.9 带 Arctap 的 Arc

当 `arctype = true`，或 Arc 上有 Arctap 时，常见语法为：

```aff
arc(t1,t2,x1,x2,easing,y1,y2,color,hitsound,true,*smoothness)[arctap(tn1),arctap(tn2),...];
```

其中：

| 字段          | 含义                 |
| ------------- | -------------------- |
| `tn1 ... tnm` | 各个 Arctap 的时间点 |

要求：

```text
t1 <= tn <= t2
```

若 Arctap 时间超出 Arc 的时间区间，坐标可能出现异常。

`arctap` 有时可简写为 `at`，但官方谱面通常不使用该别名。

### 7.10 切片 Arc 时的关键语义风险

仅裁剪 Arc 的时间端点并不一定语义正确。

若 Arc 从原始区间：

```text
[t1, t2]
```

被裁剪到：

```text
[max(t1, s), min(t2, e)]
```

则通常还需要考虑：

* 新起点对应的 `x` 坐标；
* 新终点对应的 `x` 坐标；
* 新起点对应的 `y` 坐标；
* 新终点对应的 `y` 坐标；
* easing 曲线下的插值语义；
* Arc 与相邻 Arc 的连接关系；
* Arc 上 Arctap 的保留与时间合法性；
* 裁剪后是否生成空 Arctap 列表；
* 被裁掉的 Arc 是否仍保留有效视觉与判定语义。

因此：

> 对 Arc 进行切片时，仅 clamp `t1`、`t2` 而不重算 `x1`、`x2`、`y1`、`y2`，可能导致输出 Arc 与原谱面切片区间的实际轨迹不一致。

---

## 8. 横缩放 Arctap

`color = 3` 的 Arc 可形成横缩放 Arctap 形态。

语法：

```aff
arc(t,t,x1,x2,easing,y,y,3,hitsound,false,*smoothness);
```

| 字段         | 含义                   |
| ------------ | ---------------------- |
| `t`          | Arctap 时间            |
| `x1`, `x2`   | 缩放起始与终止横坐标   |
| `easing`     | 此形态下通常无实际意义 |
| `y`          | Arctap 纵坐标          |
| `hitsound`   | 特殊打击音效           |
| `smoothness` | 此形态下通常无意义     |

从轨道俯视图理解：

* 以 `x1` 为端点；
* 向 `x2` 延伸；
* 线段长度即为缩放后的 Arctap 长度。

若填写 `hitsound`，Arctap 可使用特殊样式和音效，但其实际判定仍遵循原 Arctap 判定。

---

## 9. Camera

### 9.1 语法

```aff
camera(t,x,y,z,xozAng,yozAng,xoyAng,ease,duration);
```

| 字段          |   类型 | 含义              |
| ------------- | -----: | ----------------- |
| `t`           |    int | Camera 开始时间   |
| `x`, `y`, `z` |  float | 世界坐标位移      |
| `xozAng`      |  float | xoz 平面旋转角    |
| `yozAng`      |  float | yoz 平面旋转角    |
| `xoyAng`      |  float | xoy 平面旋转角    |
| `ease`        | string | 缓动类型          |
| `duration`    |  float | 持续时间，单位 ms |

### 9.2 坐标系

以垂直判定面为基准：

| 方向 | 含义                     |
| ---- | ------------------------ |
| x 轴 | 横向移动，左负右正       |
| y 轴 | 纵向移动，下负上正       |
| z 轴 | 沿轨道方向移动，前负后正 |

角度方向：

| 字段     | 正方向                 |
| -------- | ---------------------- |
| `xozAng` | 逆时针为正，顺时针为负 |
| `yozAng` | 抬头为正，低头为负     |
| `xoyAng` | 逆时针为正，顺时针为负 |

### 9.3 缓动

常见有效值：

| 值      | 含义             |
| ------- | ---------------- |
| `qi`    | Cubic In         |
| `qo`    | Cubic Out        |
| `reset` | 重置 Camera 状态 |

无效值通常按 Linear 处理。

当 `ease != reset` 时，会关闭 Arc 对 Camera 的倾斜控制。

### 9.4 坐标注意事项

Camera 的世界坐标与 Arc 坐标不是同一套坐标系统。

参考关系：

|   Arc 坐标 | Camera 移动距离 |
| ---------: | --------------: |
| `x = 1.00` |          约 850 |
| `y = 1.00` |          约 450 |

### 9.5 切片时的注意事项

Camera 是具有持续时间的状态事件。

切片时不能只判断：

```text
t 是否位于 [s, e]
```

还应考虑：

* Camera 效果是否在切片起点之前已开始；
* 切片起点时 Camera 的实际状态；
* 切片是否需要补偿或重置 Camera；
* `duration` 是否需要裁剪；
* 时间缩放后 duration 是否应同步缩放。

---

## 10. Scenecontrol

### 10.1 语法

```aff
scenecontrol(t,type,*param1,*param2);
```

带 `*` 的参数为可选参数，但两个参数必须同时出现或同时省略。

| 字段               |        类型 | 含义                  |
| ------------------ | ----------: | --------------------- |
| `t`                |         int | Scenecontrol 开始时间 |
| `type`             |      string | 场景控制类型          |
| `param1`, `param2` | float / int | 事件参数              |

### 10.2 已知类型

#### `trackhide`

隐藏轨道。

```aff
scenecontrol(t,trackhide);
```

当前版本中通常近似等价于：

```aff
scenecontrol(t,trackdisplay,1.00,0);
```

#### `trackshow`

显示轨道。

```aff
scenecontrol(t,trackshow);
```

当前版本中通常近似等价于：

```aff
scenecontrol(t,trackdisplay,1.00,255);
```

#### `trackdisplay`

轨道透明度控制。

```aff
scenecontrol(t,trackdisplay,param1,param2);
```

| 参数     | 含义                                             |
| -------- | ------------------------------------------------ |
| `param1` | 从当前 alpha 变换到目标 alpha 的持续时间，单位秒 |
| `param2` | 目标 alpha 值                                    |

规则：

* `param1 = 0.00` 通常等价于 `1.00`；
* `param2 = 0`：轨道完全透明；
* `param2 = 255`：轨道不透明；
* `param2 < 255`：可能出现黑色背景特效；
* `param2 >= 256`：透明度可能按 256 取模。

示例：

```aff
scenecontrol(20480,trackdisplay,6.00,0);
```

#### `redline`

背景红线效果。

```aff
scenecontrol(t,redline,param1,param2);
```

| 参数     | 含义                 |
| -------- | -------------------- |
| `param1` | 红线存在时长，单位秒 |
| `param2` | 未使用               |

示例：

```aff
scenecontrol(40960,redline,1.88,0);
```

#### `arcahvdistort`

Arcahv 解锁演出的背景变形效果。

```aff
scenecontrol(t,arcahvdistort,param1,param2);
```

#### `arcahvdebris`

Arcahv 解锁演出的背景碎片效果。

```aff
scenecontrol(t,arcahvdebris,param1,param2);
```

对于上述两个效果：

| 参数     | 含义                                           |
| -------- | ---------------------------------------------- |
| `param1` | 当前 alpha 变换到指定 alpha 的持续时间，单位秒 |
| `param2` | 目标 alpha 值                                  |

示例：

```aff
scenecontrol(1000,arcahvdebris,1.00,128);
```

#### `hidegroup`

控制 Timinggroup 内音符显示或隐藏。

```aff
scenecontrol(t,hidegroup,param1,param2);
```

| 参数     | 含义                       |
| -------- | -------------------------- |
| `param1` | 未使用                     |
| `param2` | `1` 表示隐藏，`0` 表示显示 |

示例：

```aff
scenecontrol(81920,hidegroup,0.00,1);
```

#### `enwidencamera`

使 Camera 按一定比例远离轨道，并提高 Sky Input 高度。

```aff
scenecontrol(t,enwidencamera,param1,param2);
```

| 参数     | 含义                |
| -------- | ------------------- |
| `param1` | 持续时长，单位 ms   |
| `param2` | 淡入或淡出：`1 / 0` |

示例：

```aff
scenecontrol(1000,enwidencamera,1000.00,1);
```

启用后：

* Sky Input 线移动到 Arc 坐标约 `y = 1.61`；
* 不会禁用接 Arc 时的相机倾斜。

#### `enwidenlanes`

显示两侧 Extra Lane，扩展为六轨布局。

```aff
scenecontrol(t,enwidenlanes,param1,param2);
```

| 参数     | 含义                |
| -------- | ------------------- |
| `param1` | 持续时长，单位 ms   |
| `param2` | 淡入或淡出：`1 / 0` |

注意：

* `enwidenlanes` 与 `trackdisplay` / `trackhide` / `trackshow` 不兼容。

### 10.3 切片时的注意事项

Scenecontrol 是状态与演出事件，切片时应注意：

* 切片开始前已经生效的状态是否需要继承；
* `trackhide`、`trackshow`、`trackdisplay` 是否需要补出切片起点状态；
* 持续效果的 duration 是否需要裁剪与变速；
* `enwidencamera` 与 `enwidenlanes` 是否影响后续物件坐标合法范围；
* `hidegroup` 是否需要与 Timinggroup 对应处理。

---

## 11. Timinggroup

### 11.1 基本语法

```aff
timinggroup(){
  // 正常 AFF 语句
};
```

Timinggroup 中的物件使用其内部独立的 Timing。

用途包括：

* 在同一时间实现不同物件的不同流速；
* 设置 noinput、fadingholds、Arctap 旋转等特殊效果。

### 11.2 Timing 规则

Timinggroup 内：

* 至少应包含一个 Timing；
* 内部 Timing 不产生小节线；
* 外层 Timinggroup 之外的 Timing 决定小节线；
* 理论上可存在无限多个 Timinggroup；
* 一张谱面可以仅由一个外层 `timing(0,...)` 与多个 Timinggroup 构成。

### 11.3 不可嵌套

Timinggroup **不能嵌套**。

因此，解析器不应把 Timinggroup 当作可无限递归嵌套的通用块结构。

### 11.4 Timinggroup 标识

可在括号中添加特殊标识：

```aff
timinggroup(noinput_anglex200){
  ...
};
```

多个标识通常用下划线连接。

无标识或无效标识通常不产生特殊效果。

### 11.5 `noinput`

```aff
timinggroup(noinput){
  ...
};
```

效果：

* 内部物件仅显示，不可击打；
* 不产生物量；
* 不判定命中；
* 内部实体 Arc 与 Hold 在经过判定线后仍会消失；
* 部分 Arc 判定特性仍可能保留，例如异色 Arc 的接手逻辑。

### 11.6 `fadingholds`

```aff
timinggroup(fadingholds){
  ...
};
```

效果：

* 未击中 Hold 会进行 alpha 渐变；
* 仅对该 Timinggroup 中的 Hold 生效；
* 可与 `noinput` 叠加。

### 11.7 `anglex` 与 `angley`

示例：

```aff
timinggroup(angley3400_anglex200){
  ...
};
```

含义：

* `anglex200`：Arctap 轨迹绕对应 x 轴平行线旋转 20°；
* `angley3400`：Arctap 轨迹绕对应 y 轴平行线旋转 340°；
* 两者可叠加；
* 实际落点和判定位置不受影响；
* 仅影响 Arctap，不影响 Tap、Hold、Arc；
* 叠加时先按 x 轴旋转，再按 y 轴旋转；
* 不受参数书写顺序影响。

### 11.8 切片时的注意事项

切片 Timinggroup 时，应同时考虑：

1. Timinggroup 头部标识是否完整保留；
2. 内部 Timing 是否正确偏移与补齐；
3. 内部点事件、区间事件是否按同样规则切片；
4. 空 Timinggroup 是否允许保留；
5. 不应错误支持嵌套 Timinggroup；
6. `hidegroup` 等 Scenecontrol 是否与对应 Timinggroup 的语义一致。

---

## 12. Flick

### 12.1 语法

```aff
flick(t,x,y,vx,vy);
```

| 字段       |  类型 | 含义           |
| ---------- | ----: | -------------- |
| `t`        |   int | Flick 时间     |
| `x`, `y`   | float | Flick 初始位置 |
| `vx`, `vy` | float | Flick 方向向量 |

实际滑动方位可理解为相对正右方的：

```text
arctan(vy / vx)
```

### 12.2 兼容性注意事项

官方谱面通常没有实际使用 Flick。

部分版本中 Flick 相关代码被删除或不完整，因此不应默认认为 Flick 在所有版本都可正常读取。

切片工具若遇到 Flick：

* 不应无条件原样保留；
* 至少应识别其时间字段并进行时间偏移；
* 应标记为兼容性存疑事件。

---

## 13. 坐标范围与显示约束

### 13.1 常规情况下的实体 Arc 与 Arctap 范围

无 Camera 时，实体 Arc 起止点与 Arctap 坐标通常不应超出由以下四点构成的梯形：

```text
(-0.50, 0.00)
( 1.50, 0.00)
( 0.00, 1.00)
( 1.00, 1.00)
```

Beyond 难度中，上方两个点通常变为：

```text
(-0.25, 1.00)
( 1.25, 1.00)
```

### 13.2 启用 `enwidencamera` 时

实体 Arc 起止点与 Arctap 坐标通常不应超出：

```text
(-1.00, 0.00)
( 2.00, 0.00)
(-0.25, 1.61)
( 1.25, 1.61)
```

Beyond 难度中，上方两个点通常变为：

```text
(-0.63, 1.61)
( 1.63, 1.61)
```

超出 Beyond 难度对应梯形范围时，部分 Arc 或 Arctap 可能位于屏幕外。

### 13.3 音轨类型的坐标例外

当 `arctype = true` 时，Arc 本体通常没有严格坐标界限。

但：

* 其搭载的 Arctap 仍应遵循可见与可判定的坐标范围；
* 实际制作中通常仍会把 Arc 放在合理视觉区域内。

---

## 14. 物量计算

### 14.1 基础计数

| 物件                                       | 物量计算                                  |
| ------------------------------------------ | ----------------------------------------- |
| Tap                                        | 每个 `+1`                                 |
| Arctap                                     | 每个 `+1`                                 |
| Hold                                       | 按判定块计算                              |
| 实体 Arc                                   | 大体按 Hold 方式计算，但受 Arc 组规则影响 |
| 持续时间为 0 的 Arc                        | `0`                                       |
| `skylineBoolean = true` 或 `designant` Arc | `0`                                       |

### 14.2 Hold 判定块

通常情况下，Hold 按其起始位置 BPM 的半拍划分：

```text
30000 / bpm 毫秒
```

即八分音符间隔。

规则：

* 每个判定块开始处物量 `+1`；
* 最后一个判定块不计物量；
* Hold 跨越 Timing 时，仍按 Hold 起始点的 BPM 计算；
* `bpm < 0` 时，按 `|bpm|` 计算；
* `bpm = 0` 时，物件不存在，不计算物量；
* `bpm >= 255` 时，判定块间隔改为一拍：

```text
60000 / bpm 毫秒
```

若 Hold 长度短于原判定块长度：

* 整个物件对半分为两个判定块；
* 最后一个判定块同样不计物量。

### 14.3 `TimingPointDensityFactor` 对物量的影响

若存在：

```aff
TimingPointDensityFactor:y
```

则每个判定块的时间间隔需要再除以：

```text
y
```

### 14.4 Arc 与 Arc 组

Arc 基本按 Hold 类似方式计算，但每个 Arc 语句默认单独计算。

Arc 可连接成 Arc 组。

连接条件：

1. 前一个 Arc 结尾与后一个 Arc 开头的 x 坐标差小于 `0.1`；
2. y 坐标相等；
3. 时间差小于 `10ms`；
4. 不要求颜色相同；
5. 不要求处于同一个 Timinggroup；
6. 即使带有 `noinput` 也可能形成连接关系。

Arc 组的物量规则：

* 头 Arc 按 Hold 方式计算；
* 后续 Arc 每条物量 `+1`。

### 14.5 切片与物量的关系

切片可能破坏原有 Arc 组关系，例如：

* 切掉连接段；
* 改变 Arc 起止时间；
* 改变 Arc 起止坐标；
* 造成原本相连的 Arc 断开；
* 让原本不相连的 Arc 意外满足连接条件。

因此，若切片工具目标包含“保持原物量逻辑”或“保持体验等价”，应将 Arc 连接关系纳入验证范围。

---

## 15. 对 AFF 切片实现的审查清单

实现谱面切片时，至少应确认以下问题。

### 15.1 Header 与分隔符

* 是否保留 `AudioOffset`？
* 切片后 AudioOffset 是否仍正确？
* 是否保留 `TimingPointDensityFactor`？
* 是否只以第一个单独成行的 `-` 作为分隔符？
* 是否避免修改 Header 中非事件文本？

### 15.2 Timing

* 输出是否保证外层 `timing(0,bpm,beats);`？
* 切片起点处的 BPM / beats 是否继承正确？
* 是否避免把 Timinggroup 内 Timing 错当作外层 Timing？
* 速度变换后 Timing 时间是否同步变换？

### 15.3 Tap / Hold

* 点事件边界采用闭区间还是半开区间？
* Hold 跨边界时是否裁剪两端？
* 裁剪后是否保持 `t1 <= t2`？
* 浮点 lane 是否原样保留？

### 15.4 Arc / Arctap

* Arc 跨边界时是否重算裁剪后端点坐标？
* 是否根据 easing 插值，而不是仅保留原 `x1/x2/y1/y2`？
* Arctap 是否过滤到裁剪后的 Arc 时间范围内？
* 裁剪后空 Arctap 列表是否符合目标兼容性要求？
* Arc 组连接关系是否被破坏？
* 横缩放 Arctap 是否被误当作普通 Arc？
* `designant`、特殊 hitsound、smoothness 是否保留？

### 15.5 Camera / Scenecontrol

* 切片开始前已生效的 Camera 是否需要状态继承？
* 切片开始前已生效的轨道显示状态是否需要补偿？
* duration 是否应裁剪并随速度缩放？
* `enwidencamera` / `enwidenlanes` 是否影响后续坐标范围与视觉状态？

### 15.6 Timinggroup

* 是否正确保留 Timinggroup 标识？
* 是否禁止错误地递归嵌套 Timinggroup？
* 是否保留内部 Timing？
* 空 Timinggroup 是否应删除？
* `noinput`、`fadingholds`、`anglex`、`angley` 是否原样保留？

### 15.7 未识别事件

对于未知 AFF 行：

* 原样保留可能导致其中时间字段未偏移；
* 删除可能丢失新版本事件；
* 更稳妥的策略是识别事件类型、标记未支持语法，并在输出前提示风险。

---

## 16. 已知兼容性与版本备注

* 绿色 Arc 的正常读取范围受谱面类型与游戏版本影响。
* `designant` 在部分旧版本可能按 `false` 处理。
* Flick 在较新版本中可能无法正常读取。
* `enwidencamera`、`enwidenlanes`、横缩放 Arctap、smoothness 等均具有版本依赖。
* 不同游戏版本对未知字段、无效参数、特殊事件的容忍程度可能不同。
* 用于自制或测试的输出谱面，应通过目标游戏版本的实际导入与游玩验证。

---

## 17. 建议的最小测试矩阵

| 测试类别      | 最小覆盖点                                                       |
| ------------- | ---------------------------------------------------------------- |
| Header        | `AudioOffset`、`TimingPointDensityFactor`、自定义 Header、分隔符 |
| Timing        | 切片前最后有效 Timing、切片内 Timing、Timinggroup 内 Timing      |
| Tap           | 左边界、右边界、区间外、浮点 lane                                |
| Hold          | 完全包含、跨左边界、跨右边界、跨两边界、零长度                   |
| Arc           | 完全包含、跨左右边界、不同 easing、零长度、Arc 组                |
| Arctap        | 边界 Arctap、被裁掉的 Arctap、全部被裁掉后的 Arc                 |
| 横缩放 Arctap | `color=3`、`t1=t2`、hitsound                                     |
| Camera        | 区间内开始、切片前开始且持续到区间内、reset                      |
| Scenecontrol  | trackhide、trackdisplay、enwidencamera、enwidenlanes、hidegroup  |
| Timinggroup   | 无标识、noinput、fadingholds、anglex/angley、空块                |
| Flick         | 时间偏移与兼容性提示                                             |
| 变速          | 0.5x、1.0x、2.0x，验证音频时长与谱面时间同步                     |
| 输出合法性    | 外层 `timing(0,...)`、无非法 Arctap 时间、无错误嵌套 Timinggroup |

---

## 18. 免责声明与使用边界

本文仅用于 AFF 格式理解、兼容性研究、谱面工具开发与本地测试。

不同 Arcaea 版本、不同谱面类型、不同特殊演出内容可能存在行为差异。对于任何自动切片、重写或导出的谱面，应以实际目标环境中的导入与游玩结果作为最终验证依据。
