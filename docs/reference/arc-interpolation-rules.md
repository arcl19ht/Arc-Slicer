# Arcaea AFF Arc 坐标计算与截断规则

> 用途：为 Arc Slicer 的 Arc 截断、Arctap 坐标计算、反向 Arc 处理和后续谱面预览提供统一规则。
> 适用对象：`arc(t1,t2,x1,x2,easing,y1,y2,color,hitsound,arctype,*smoothness);`
> 本文只规定 Arc 的时间—坐标插值；不规定物量、Arc 组、音频切片或 Timing 计算。

---

## 1. 基本定义

一条 Arc 的关键参数：

```text
t1, t2       声明的起止时间
x1, x2       声明的横坐标起止值
y1, y2       声明的纵坐标起止值
easing       缓动类型
```

对于持续时间不为零的 Arc，即：

```text
t1 != t2
```

在 Arc 上任意时刻 `t` 的归一化进度定义为：

```text
p = (t - t1) / (t2 - t1)
```

当 `t = t1` 时，`p = 0`；当 `t = t2` 时，`p = 1`。

坐标计算统一写作：

```text
x(t) = x1 + (x2 - x1) × Ex(p)
y(t) = y1 + (y2 - y1) × Ey(p)
```

其中：

* `Ex(p)`：easing 对 x 轴使用的进度函数；
* `Ey(p)`：easing 对 y 轴使用的进度函数；
* `p` 在正常切片边界计算中应落在 `[0, 1]`；
* 若调用方允许查询范围外时间，可先将 `p` 截断到 `[0, 1]`，但切片逻辑本身不应将范围外时间当作 Arc 内部点。

---

## 2. 基础缓动函数

设 `p ∈ [0, 1]`。

### 2.1 Straight：`s`

```text
S(p) = p
```

即线性插值，速度恒定。

```text
Lerp(a, b, S(p)) = a + (b - a) × p
```

---

### 2.2 Sine Out：`si`

```text
SI(p) = sin(πp / 2)
```

性质：

* 开始时快；
* 接近终点时逐渐减速；
* `SI(0) = 0`；
* `SI(1) = 1`。

注意：AFF 中的 `si` 是 **Sine Out**。

---

### 2.3 Sine In：`so`

```text
SO(p) = 1 - cos(πp / 2)
```

性质：

* 开始时慢；
* 接近终点时逐渐加速；
* `SO(0) = 0`；
* `SO(1) = 1`。

注意：AFF 中的 `so` 是 **Sine In**。

---

### 2.4 Bézier：`b`

`b` 使用固定的三次 Bézier 缓动。

对于单个坐标轴，控制点为：

```text
P0 = start
P1 = start
P2 = end
P3 = end
```

因此：

```text
B(start, end, p)
= (1-p)^3 × start
+ 3(1-p)^2p × start
+ 3(1-p)p^2 × end
+ p^3 × end
```

化简为：

```text
B(start, end, p)
= start + (end - start) × (3p² - 2p³)
```

因此对应进度函数为：

```text
B(p) = 3p² - 2p³
```

性质：

* 开始时慢；
* 中间加速；
* 接近终点再次减速；
* 起点与终点的速度均为零；
* 在 `p = 0.5` 时刚好位于 50% 位置。

---

## 3. easing 字符串的完整映射

AFF 中可用的 Arc easing 为：

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

除上述值外，读取时按 `s` 处理；写出时不得主动生成未知 easing。

| easing | x 轴函数 | y 轴函数 | 说明                        |
| ------ | -------- | -------- | --------------------------- |
| `b`    | `B`      | `B`      | 两轴均为 Bézier             |
| `s`    | `S`      | `S`      | 两轴均为线性                |
| `si`   | `SI`     | `S`      | `si s` 的简写               |
| `so`   | `SO`     | `S`      | `so s` 的简写               |
| `sisi` | `SI`     | `SI`     | x、y 都为 Sine Out          |
| `siso` | `SI`     | `SO`     | x 为 Sine Out，y 为 Sine In |
| `sosi` | `SO`     | `SI`     | x 为 Sine In，y 为 Sine Out |
| `soso` | `SO`     | `SO`     | x、y 都为 Sine In           |

---

## 4. 短写法与不存在的曲线

这部分必须严格遵守，不能按字符串长度随意推断。

```text
si = si s
so = so s
```

也就是说：

```text
si：x 使用 SI，y 使用 S
so：x 使用 SO，y 使用 S
```

`si` 和 `so` 的第二个 `s` 是省略的 y 轴线性缓动。

因此：

```text
不存在 s si
不存在 s so
不存在 ssi
不存在 sso
```

不能把 `si` 错读为：

```text
x = S
y = SI
```

也不能把 `so` 错读为：

```text
x = S
y = SO
```

AFF 已定义的双轴非线性组合只有：

```text
sisi
siso
sosi
soso
```

其中字符串前半部分控制 x，后半部分控制 y。

---

## 5. 容易混淆的反向关系

## 5.1 `siso` 与 `sosi` 是互相反过来的组合

```text
siso:
x = SI = Sine Out
y = SO = Sine In

sosi:
x = SO = Sine In
y = SI = Sine Out
```

不要把两者混写。

---

## 5.2 坐标从大到小，不等于要交换 `si` 与 `so`

例如：

```text
arc(0,1000,1.0,0.0,si,0.0,0.0,...)
```

x 从 `1.0` 移动到 `0.0`，但 easing 仍是 `si`。

计算仍为：

```text
x(t) = 1.0 + (0.0 - 1.0) × SI(p)
```

坐标方向由 `x1 → x2` 决定；缓动类型描述的是从声明起点走向声明终点时的进度分布。

因此：

> 仅因为 x 或 y 的数值方向反过来，不能把 `si` 改成 `so`，也不能把 `so` 改成 `si`。

---

## 5.3 真正“反过来”是参数方向被反转

若程序将一条 Arc 的声明起终点完全交换：

```text
(t1, x1, y1) ↔ (t2, x2, y2)
```

则进度方向也被反转。

原缓动函数为：

```text
F(p)
```

反向后的等价缓动函数必须是：

```text
F_reverse(p) = 1 - F(1 - p)
```

对应关系如下：

| 原 easing | 反向后的 easing |
| --------- | --------------- |
| `s`       | `s`             |
| `b`       | `b`             |
| `si`      | `so`            |
| `so`      | `si`            |
| `sisi`    | `soso`          |
| `siso`    | `sosi`          |
| `sosi`    | `siso`          |
| `soso`    | `sisi`          |

原因：

```text
S_reverse(p)  = S(p)
B_reverse(p)  = B(p)
SI_reverse(p) = SO(p)
SO_reverse(p) = SI(p)
```

因此：

> 若真正交换了 Arc 的时间与端点，必须同时按上表反转 easing。
> 若只是在坐标上从大到小移动，不得反转 easing。

---

## 6. `t1 > t2` 的反向 Arc

AFF 中，满足特定条件的 Arc 可以出现：

```text
t1 > t2
```

处理这类 Arc 时：

1. 判断时间覆盖范围时，可以使用：

```text
low  = min(t1, t2)
high = max(t1, t2)
```

2. 计算 Arc 坐标时，不能把 `t1/t2` 排序后再计算。

必须保留声明方向：

```text
p = (t - t1) / (t2 - t1)
```

因为这里分母为负数。

例如：

```text
t1 = 5000
t2 = 1000
```

则：

```text
t = 5000 → p = 0
t = 1000 → p = 1
```

这仍然正确表达了“从声明起点到声明终点”的参数方向。

### 6.1 禁止的做法

不要这样处理：

```text
先交换 t1 和 t2
再交换 x1/x2、y1/y2
但保持原 easing 不变
```

这会改变 `si`、`so`、`siso`、`sosi` 等非对称缓动的实际轨迹。

### 6.2 两种正确策略

#### 策略 A：保留原方向

切片器应优先采用此策略。

* 保留 `t1 > t2`；
* 分别裁剪原始 `t1` 和 `t2`；
* 用原始 Arc 的 `position_at(t)` 计算新端点；
* easing 原样保留。

此时不需要变换 easing。

#### 策略 B：强制规范化为 `t1 <= t2`

仅当程序架构必须这样做时使用。

* 交换时间；
* 交换 x/y 端点；
* 同时按“反向 easing 表”替换 easing；
* 再输出新 Arc。

此策略必须有单元测试，不得只交换坐标和时间。

---

## 7. Arc 在任意时刻的位置

建议统一使用以下接口：

```python
def arc_position_at(
    t: float,
    t1: float,
    t2: float,
    x1: float,
    x2: float,
    y1: float,
    y2: float,
    easing: str,
) -> tuple[float, float]:
    ...
```

逻辑如下：

```python
def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def progress_at(t: float, t1: float, t2: float) -> float:
    if t1 == t2:
        raise ValueError("zero-duration Arc has no continuous progress")
    return clamp01((t - t1) / (t2 - t1))


def linear(p: float) -> float:
    return p


def sine_out(p: float) -> float:  # si
    return math.sin(math.pi * p / 2.0)


def sine_in(p: float) -> float:  # so
    return 1.0 - math.cos(math.pi * p / 2.0)


def bezier(p: float) -> float:   # b
    return 3.0 * p * p - 2.0 * p * p * p


def axis_easing(easing: str) -> tuple[Callable, Callable]:
    table = {
        "b":    (bezier, bezier),
        "s":    (linear, linear),
        "si":   (sine_out, linear),
        "so":   (sine_in, linear),
        "sisi": (sine_out, sine_out),
        "siso": (sine_out, sine_in),
        "sosi": (sine_in, sine_out),
        "soso": (sine_in, sine_in),
    }
    return table.get(easing.lower(), (linear, linear))


def arc_position_at(...):
    p = progress_at(t, t1, t2)
    fx, fy = axis_easing(easing)
    x = x1 + (x2 - x1) * fx(p)
    y = y1 + (y2 - y1) * fy(p)
    return x, y
```

---

## 8. Arc 切片时的新端点计算

设原 Arc 为：

```text
arc(t1,t2,x1,x2,easing,y1,y2,...)
```

切片时间窗口为：

```text
[L, R]
```

只要原 Arc 与窗口相交，就先保留其声明端点方向：

```text
new_t1 = clamp(t1, L, R)
new_t2 = clamp(t2, L, R)
```

然后分别按原 Arc 求位置：

```text
new_x1, new_y1 = position_at(new_t1)
new_x2, new_y2 = position_at(new_t2)
```

输出 Arc 使用：

```text
arc(
  transformed(new_t1),
  transformed(new_t2),
  new_x1,
  new_x2,
  original_easing,
  new_y1,
  new_y2,
  ...
)
```

其中：

```text
transformed(t) = (t - slice_start) / speed
```

### 8.1 最低要求：端点正确

切片后至少必须保证：

* 新 Arc 在切片开头出现的位置，等于原 Arc 在该时刻的位置；
* 新 Arc 在切片结尾消失的位置，等于原 Arc 在该时刻的位置；
* 不出现从原 Arc 起点突然跳入切片的视觉错误；
* `t1 > t2` 时仍保持正确参数方向。

---

## 9. 非线性 Arc 的“完全轨迹保持”限制

对于 `si`、`so`、`b`、`sisi`、`siso`、`sosi`、`soso`：

> 只重算新端点、但保留原 easing 字符串，能够保证切片边界位置正确；
> 但通常不能保证切片内部轨迹与原谱完全一致。

原因是：

```text
原曲线在 p=a 到 p=b 的局部片段
重新映射到 0 到 1 后
通常不再恰好属于同一种固定 easing 曲线。
```

例如，原 `si` Arc 从 `p=0.40` 截到 `p=0.75`：

* 重算两端位置可以避免边界跳变；
* 但新 Arc 再使用完整 `si`，中间进度并不完全等于原曲线的局部参数变化。

因此分为两个标准：

### 9.1 Gate 0 最低标准

* 必须重算截断端点；
* 必须保持时间、端点、方向和 Arctap 坐标关系合理；
* 允许非线性 Arc 的切片内部存在轻微轨迹再参数化差异；
* 必须以实机验证其可读性与演出可接受性。

### 9.2 未来精确标准

若要求完全保持原曲线：

* 需要对非线性 Arc 做细分；
* 以多段短 Arc 近似原轨迹；
* 或建立能表达局部曲线的新表示；
* 不应假设“裁掉两端再保留相同 easing”必然数学等价。

---

## 10. Arctap 坐标规则

Arctap 自身只保存时间：

```text
arctap(tn)
```

它的坐标继承自所属 Arc：

```text
arctap_x = arc_x(tn)
arctap_y = arc_y(tn)
```

因此：

* Arctap 是否保留，应按其时间是否属于输出 Arc 的有效时间范围判断；
* 保留后的 Arctap 时间应按切片与倍速规则转换；
* Arctap 的视觉坐标会自动由切片后 Arc 决定；
* 若输出 Arc 只做到“端点正确但非完全轨迹保持”，内部 Arctap 的位置也可能与原谱存在细微差异。

---

## 11. 零时长 Arc

当：

```text
t1 == t2
```

Arc 不构成普通连续轨迹。

此类 Arc：

* 不应调用普通 `position_at()`；
* 不应用于连续缓动插值；
* 切片时应作为时间点事件处理；
* 是否保留取决于切片边界规则；
* 原始 `x1/x2/y1/y2/easing` 应尽量原样保留；
* 不得因插值错误制造除零问题。

---

## 12. 与 Arc 坐标无关的字段

以下字段不改变 Arc 的 x/y 插值规则：

```text
color
hitsound
arctype
smoothness
timinggroup flags
```

其中：

* `arctype=true`、`designant` 仍使用同一坐标计算；
* `smoothness` 影响渲染 segment 细分，不改变理论坐标函数；
* Timinggroup 的 `noinput` 等标识影响判定或显示，不改变 Arc 的参数曲线；
* 这些字段必须在切片时保留，但不应混入坐标插值函数。

---

## 13. 实施检查表

实现 Arc 截断前，必须确认：

* [ ] `si = Sine Out`，使用 `sin(πp/2)`；
* [ ] `so = Sine In`，使用 `1-cos(πp/2)`；
* [ ] `si` 被解析为 `(si, s)`，不是 `(s, si)`；
* [ ] 不生成 `ssi`、`sso` 等不存在的 easing；
* [ ] `siso` 与 `sosi` 的 x/y 方向没有写反；
* [ ] 坐标下降时不交换 `si/so`；
* [ ] 反转 Arc 参数方向时按表变换 easing；
* [ ] `t1 > t2` 不被无条件排序；
* [ ] `t1 == t2` 不进入普通连续插值；
* [ ] 切片 Arc 端点使用原 Arc 的 `position_at()` 计算；
* [ ] Arctap 位置按所属 Arc 曲线计算；
* [ ] `b`、`si`、`so`、复合 easing 都有测试样例；
* [ ] 非线性 Arc 的“端点正确”与“轨迹严格等价”被明确区分。

---

## 14. 最小测试样例

至少应验证：

1. `s`：x/y 线性；
2. `si`：x Sine Out、y 线性；
3. `so`：x Sine In、y 线性；
4. `siso`：x Sine Out、y Sine In；
5. `sosi`：x Sine In、y Sine Out；
6. `b`：x/y 对称 Bézier；
7. x 从大到小但 easing 不变；
8. y 从大到小但 easing 不变；
9. 正常 `t1 < t2` Arc 的左右截断；
10. `t1 > t2` Arc 的截断；
11. 交换端点后 easing 反向映射；
12. 含 Arctap 的非线性 Arc；
13. 零时长 Arc；
14. 切点恰好位于 Arc 起点或终点。

---

## 15. 最终原则

> Arc 的 easing 描述的是“从声明起点到声明终点”的参数进度，不是单纯的屏幕坐标方向。
>
> 坐标变大或变小，不改变 easing。
>
> 真正反转 Arc 的参数方向时，才需要按反向映射交换 `si/so` 与复合 easing。
>
> 切片时必须先依据原 Arc 计算边界实际坐标，再构造输出 Arc。
