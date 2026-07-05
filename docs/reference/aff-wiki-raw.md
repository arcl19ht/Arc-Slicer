# Arcaea AFF Wiki Raw Reference

> This file keeps format facts, syntax, field meanings, constraints, and version notes extracted from `affintro.md`.
> It intentionally omits slicer-specific engineering advice, risk analysis, review checklists, and test matrices.

---

## 1. Overview

Arcaea chart files use the `.aff` extension.

Unencrypted official charts in install packages can usually be read directly. Common difficulty file names are:

| File | Difficulty |
| ---- | ---------- |
| `0.aff` | PST |
| `1.aff` | PRS |
| `2.aff` | FTR |
| `3.aff` | BYD |
| `4.aff` | ETR |

Android APK charts are commonly under `assets/songs/<songid>/`; iOS IPA charts are commonly under `Payload/Arc-mobile.app/songs/<songid>/`.

`.aff` files usually do not contain song metadata such as title, difficulty rating, chart designer, pack, or unlock conditions. These are stored in files such as `songlist`, `unlocks`, and `packlist`.

---

## 2. File Structure

An AFF file is usually composed of:

```text
header information
-
normal AFF statements
```

The first standalone line containing `-` is the separator.

* Lines before the separator are header information.
* Lines after the separator are normal AFF statements.
* Header information and normal AFF statements usually have flexible ordering.
* Same-type header information or AFF statements at the same timestamp may be order-sensitive.

---

## 3. Header Information

### 3.1 `AudioOffset`

Official charts usually contain:

```aff
AudioOffset:x
```

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `x` | int | Overall chart offset in milliseconds; negative shifts earlier, positive shifts later |

Usually `x = 0`; in that case object timestamps directly correspond to song playback progress in milliseconds.

When `x != 0`, object timing relative to the music is affected by this offset. Some official charts use nonzero offset when the first audible beat is not on a clean beat boundary.

Deleting this line usually does not crash the game, but affects chart/audio alignment logic.

### 3.2 `TimingPointDensityFactor`

Some charts contain:

```aff
TimingPointDensityFactor:y
```

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `y` | int / float | Global density multiplier for physical Arc and Hold timing points |

Rules:

* Missing value defaults to `1`.
* Minimum value is `0`.
* This value affects Hold and physical Arc judgement-block density and note count.

### 3.3 Custom Header Information

Custom header information can appear before the first `-`, for example:

```aff
ChartVersion:2
```

The game can usually read and record this information, but it may not have any practical effect.

---

## 4. Time And Basic Constraints

Most AFF time fields use:

* Unit: milliseconds (ms)
* Type: integer (`int`)

Common requirements:

* Point-event time `t >= 0`
* Interval-event times `t1 <= t2`

Some special Arc types may allow `t1 > t2`; see the Arc section.

---

## 5. Timing

### 5.1 Syntax

```aff
timing(t,bpm,beats);
```

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `t` | int | Timing start time |
| `bpm` | float | Scroll speed, in beats per minute |
| `beats` | float | Number of quarter notes per measure |

Each Timing creates a measure line at `t`.

### 5.2 `beats` Constraints

When `bpm != 0`:

* `beats` must not be `0`.
* For example, `4.00` means 4/4 time.

If `beats = 0`, division by zero may occur and the game may crash.

### 5.3 Basic Legality

Every chart must have at least one:

```aff
timing(0,bpm,beats);
```

This Timing must:

* Be outside any Timinggroup.
* Have `t = 0`.
* Have `bpm >= 0`.
* Have `beats >= 0`.

Otherwise the chart may fail to load normally.

---

## 6. Ground Notes: Tap And Hold

### 6.1 Tap

```aff
(t,lane);
```

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `t` | int | Tap time |
| `lane` | 0-5 / float | Ground lane or horizontal coordinate |

### 6.2 Hold

```aff
hold(t1,t2,lane);
```

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `t1` | int | Hold start time |
| `t2` | int | Hold end time |
| `lane` | 0-5 / float | Ground lane or horizontal coordinate |

When `t1 = t2`, Hold note count is `0`.

### 6.3 Lane Numbers And Floating Lanes

Integer lanes from left to right:

```text
0, 1, 2, 3, 4, 5
```

Usually only lanes `1` through `4` are used.

When `enwidenlanes` is enabled:

* Lane `0` appears to the left of lane `1`.
* Lane `5` appears to the right of lane `4`.
* A six-lane layout can be formed.

`lane` can also be a float, representing a coordinate-based position.

Integer lane to Arc horizontal coordinate:

```text
x = (lane - 0.5) / 4
```

Arc horizontal coordinate to lane coordinate:

```text
lane = (x + 0.5) / 2
```

Floating lanes have different judgement behavior from normal lanes and are usually more suitable for presentation than ordinary Tap / Hold usage.

---

## 7. Arc And Arctap

### 7.1 Arc Syntax

```aff
arc(t1,t2,x1,x2,easing,y1,y2,color,hitsound,arctype,*smoothness);
```

The `*` parameter is optional.

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `t1`, `t2` | int | Arc start and end time |
| `x1`, `x2` | float | Start and end horizontal coordinate |
| `easing` | string | Arc movement type |
| `y1`, `y2` | float | Start and end vertical coordinate |
| `color` | int | Arc color |
| `hitsound` | string | Special Arctap hitsound |
| `arctype` | string | Arc type |
| `smoothness` | optional float | Arc segment smoothness |

### 7.2 Time Fields

Usually:

```text
t1 <= t2
```

When `t1 = t2`:

* The Arc is parallel to the judgement line.
* The Arc note count is `0`.
* It can connect Arc groups.
* It can be regarded as a connection segment between continuous Arcs and cannot be switched between hands.

`t1 > t2` is allowed only when:

* `skylineBoolean = true`
* `arctype = designant`

### 7.3 Coordinates

| Field | Meaning |
| ----- | ------- |
| `x1`, `x2` | Horizontal coordinates at Arc start and end |
| `y1`, `y2` | Vertical coordinates at Arc start and end |

### 7.4 Easing

Common valid values:

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

| Value | Meaning |
| ----- | ------- |
| `b` | Bezier |
| `s` | Straight |
| `si` | Sine Out |
| `so` | Sine In |

Invalid values are usually treated as Straight. When `t1 = t2`, easing is usually meaningless.

Combined values such as `siso` can represent different easing types on the x and y axes.

### 7.5 Color

| Value | Color |
| ----: | ----- |
| `0` | Blue |
| `1` | Red |
| `2` | Green |
| `3` | Gray |

Other values are usually shown as black.

Notes:

* When `arctype = true`, color is usually meaningless.
* Green Arc compatibility depends on game version and chart type.
* In newer versions, `color = 3` can appear as horizontally scaled Arctap.

### 7.6 Hitsound

`hitsound` was implemented in v4.0.0. It specifies the special sound effect for all Arctaps on the Arc.

Example:

```aff
arc(...,glass_wav,true)[arctap(...)];
```

This tries to use:

```text
songs/<songid>/glass.wav
```

as the hitsound.

Common value:

```text
none
```

meaning no special hitsound.

Even when the current Arc has no Arctap or is not a trace type, arbitrary hitsound values can cause compatibility concerns.

### 7.7 Arc Type

Common values:

| Value | Meaning |
| ----- | ------- |
| `false` | Physical Arc |
| `true` | Trace |
| `designant` | Special Designant trace |

Invalid values are usually treated as `false`.

If an Arc has Arctap, it is usually treated as `true` except for `designant`.

`designant`:

* Appears as a pinkish trace.
* Also colors Arctaps on the Arc.
* Its Arctaps do not count toward total combo.
* Hits do not increase HP.
* Usually takes effect only in specific presentation scenes.
* Some old versions treat it as `false`.

### 7.8 Smoothness

Added in v6.8.0.

```text
smoothness >= 1
```

It controls Arc segment subdivision count. Default and minimum are both `1`.

### 7.9 Arc With Arctap

When `arctype = true`, or when the Arc has Arctaps, common syntax is:

```aff
arc(t1,t2,x1,x2,easing,y1,y2,color,hitsound,true,*smoothness)[arctap(tn1),arctap(tn2),...];
```

| Field | Meaning |
| ----- | ------- |
| `tn1 ... tnm` | Each Arctap timestamp |

Requirement:

```text
t1 <= tn <= t2
```

If Arctap time falls outside the Arc interval, coordinates may become abnormal.

`arctap` can sometimes be abbreviated as `at`, but official charts usually do not use this alias.

---

## 8. Horizontally Scaled Arctap

An Arc with `color = 3` can form a horizontally scaled Arctap.

```aff
arc(t,t,x1,x2,easing,y,y,3,hitsound,false,*smoothness);
```

| Field | Meaning |
| ----- | ------- |
| `t` | Arctap time |
| `x1`, `x2` | Scaling start and end horizontal coordinate |
| `easing` | Usually has no practical meaning in this form |
| `y` | Arctap vertical coordinate |
| `hitsound` | Special hitsound |
| `smoothness` | Usually has no meaning in this form |

From top-down track view:

* `x1` is one endpoint.
* The line extends toward `x2`.
* Line length is the scaled Arctap length.

If `hitsound` is filled, the Arctap can use special style and sound, but its actual judgement still follows normal Arctap judgement.

---

## 9. Camera

### 9.1 Syntax

```aff
camera(t,x,y,z,xozAng,yozAng,xoyAng,ease,duration);
```

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `t` | int | Camera start time |
| `x`, `y`, `z` | float | World-coordinate displacement |
| `xozAng` | float | Rotation angle on xoz plane |
| `yozAng` | float | Rotation angle on yoz plane |
| `xoyAng` | float | Rotation angle on xoy plane |
| `ease` | string | Easing type |
| `duration` | float | Duration in ms |

### 9.2 Coordinate System

Based on the vertical judgement plane:

| Direction | Meaning |
| --------- | ------- |
| x axis | Horizontal displacement; left negative, right positive |
| y axis | Vertical displacement; down negative, up positive |
| z axis | Along track direction; forward negative, backward positive |

Angle direction:

| Field | Positive direction |
| ----- | ------------------ |
| `xozAng` | Counterclockwise positive, clockwise negative |
| `yozAng` | Looking up positive, looking down negative |
| `xoyAng` | Counterclockwise positive, clockwise negative |

### 9.3 Easing

Common valid values:

| Value | Meaning |
| ----- | ------- |
| `qi` | Cubic In |
| `qo` | Cubic Out |
| `reset` | Reset Camera state |

Invalid values are usually treated as Linear.

When `ease != reset`, Arc-based camera tilt control is disabled.

### 9.4 Coordinate Notes

Camera world coordinates and Arc coordinates are not the same coordinate system.

Reference relation:

| Arc coordinate | Camera movement distance |
| -------------: | -----------------------: |
| `x = 1.00` | about `850` |
| `y = 1.00` | about `450` |

---

## 10. Scenecontrol

### 10.1 Syntax

```aff
scenecontrol(t,type,*param1,*param2);
```

Optional parameters must appear together or be omitted together.

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `t` | int | Scenecontrol start time |
| `type` | string | Scenecontrol type |
| `param1`, `param2` | float / int | Event parameters |

### 10.2 Known Types

#### `trackhide`

Hides the track.

```aff
scenecontrol(t,trackhide);
```

In current versions, this is usually approximately equivalent to:

```aff
scenecontrol(t,trackdisplay,1.00,0);
```

#### `trackshow`

Shows the track.

```aff
scenecontrol(t,trackshow);
```

In current versions, this is usually approximately equivalent to:

```aff
scenecontrol(t,trackdisplay,1.00,255);
```

#### `trackdisplay`

Controls track transparency.

```aff
scenecontrol(t,trackdisplay,param1,param2);
```

| Parameter | Meaning |
| --------- | ------- |
| `param1` | Duration in seconds for transition from current alpha to target alpha |
| `param2` | Target alpha value |

Rules:

* `param1 = 0.00` is usually equivalent to `1.00`.
* `param2 = 0`: fully transparent track.
* `param2 = 255`: opaque track.
* `param2 < 255`: may create black-background effects.
* `param2 >= 256`: transparency may be taken modulo 256.

#### `redline`

Background red-line effect.

```aff
scenecontrol(t,redline,param1,param2);
```

| Parameter | Meaning |
| --------- | ------- |
| `param1` | Red-line duration in seconds |
| `param2` | Unused |

#### `arcahvdistort`

Arcahv unlock background distortion effect.

```aff
scenecontrol(t,arcahvdistort,param1,param2);
```

#### `arcahvdebris`

Arcahv unlock background debris effect.

```aff
scenecontrol(t,arcahvdebris,param1,param2);
```

For `arcahvdistort` and `arcahvdebris`:

| Parameter | Meaning |
| --------- | ------- |
| `param1` | Duration in seconds for transition from current alpha to target alpha |
| `param2` | Target alpha value |

#### `hidegroup`

Controls display/hide state of notes inside Timinggroup.

```aff
scenecontrol(t,hidegroup,param1,param2);
```

| Parameter | Meaning |
| --------- | ------- |
| `param1` | Unused |
| `param2` | `1` means hidden, `0` means shown |

#### `enwidencamera`

Moves Camera away from the track by a ratio and raises Sky Input height.

```aff
scenecontrol(t,enwidencamera,param1,param2);
```

| Parameter | Meaning |
| --------- | ------- |
| `param1` | Duration in ms |
| `param2` | Fade in/out: `1 / 0` |

After enabled:

* Sky Input line moves to about Arc coordinate `y = 1.61`.
* It does not disable camera tilt when catching Arc.

#### `enwidenlanes`

Shows the two side Extra Lanes, expanding to a six-lane layout.

```aff
scenecontrol(t,enwidenlanes,param1,param2);
```

| Parameter | Meaning |
| --------- | ------- |
| `param1` | Duration in ms |
| `param2` | Fade in/out: `1 / 0` |

`enwidenlanes` is incompatible with `trackdisplay`, `trackhide`, and `trackshow`.

---

## 11. Timinggroup

### 11.1 Basic Syntax

```aff
timinggroup(){
  // normal AFF statements
};
```

Objects in a Timinggroup use the group's internal Timing.

Uses include:

* Different scroll speeds for different objects at the same time.
* Special effects such as `noinput`, `fadingholds`, and Arctap rotation.

### 11.2 Timing Rules

Inside a Timinggroup:

* At least one Timing should be included.
* Internal Timing does not create measure lines.
* Timing outside Timinggroups determines measure lines.
* Theoretically, unlimited Timinggroups can exist.
* A chart can consist only of one outer `timing(0,...)` and multiple Timinggroups.

### 11.3 No Nesting

Timinggroup cannot be nested.

### 11.4 Timinggroup Flags

Special flags can be added inside parentheses:

```aff
timinggroup(noinput_anglex200){
  ...
};
```

Multiple flags are usually joined by underscores. Empty or invalid flags usually produce no special effect.

### 11.5 `noinput`

```aff
timinggroup(noinput){
  ...
};
```

Effects:

* Internal objects are visible but cannot be hit.
* They do not contribute note count.
* They do not judge hits.
* Internal physical Arc and Hold still disappear after passing the judgement line.
* Some Arc judgement behavior may remain, such as cross-color Arc hand-change behavior.

### 11.6 `fadingholds`

```aff
timinggroup(fadingholds){
  ...
};
```

Effects:

* Missed Holds fade in alpha.
* Applies only to Holds in the Timinggroup.
* Can stack with `noinput`.

### 11.7 `anglex` And `angley`

Example:

```aff
timinggroup(angley3400_anglex200){
  ...
};
```

Meaning:

* `anglex200`: Arctap trajectory rotates 20 degrees around the corresponding x-axis parallel line.
* `angley3400`: Arctap trajectory rotates 340 degrees around the corresponding y-axis parallel line.
* Both can stack.
* Actual landing and judgement positions are unaffected.
* Only affects Arctap, not Tap, Hold, or Arc.
* When stacked, x-axis rotation is applied before y-axis rotation.
* Parameter order does not affect behavior.

---

## 12. Flick

### 12.1 Syntax

```aff
flick(t,x,y,vx,vy);
```

| Field | Type | Meaning |
| ----- | ---: | ------- |
| `t` | int | Flick time |
| `x`, `y` | float | Flick initial position |
| `vx`, `vy` | float | Flick direction vector |

Actual flick direction can be understood as relative to the positive-right direction:

```text
arctan(vy / vx)
```

### 12.2 Compatibility Notes

Official charts usually do not actually use Flick.

In some versions, Flick-related code was removed or incomplete, so Flick should not be assumed to work normally in all versions.

---

## 13. Coordinate Range And Display Constraints

### 13.1 Physical Arc And Arctap Range Under Normal Conditions

Without Camera, physical Arc endpoints and Arctap coordinates usually should not exceed the trapezoid formed by:

```text
(-0.50, 0.00)
( 1.50, 0.00)
( 0.00, 1.00)
( 1.00, 1.00)
```

In Beyond difficulty, the upper two points usually become:

```text
(-0.25, 1.00)
( 1.25, 1.00)
```

### 13.2 With `enwidencamera`

Physical Arc endpoints and Arctap coordinates usually should not exceed:

```text
(-1.00, 0.00)
( 2.00, 0.00)
(-0.25, 1.61)
( 1.25, 1.61)
```

In Beyond difficulty, the upper two points usually become:

```text
(-0.63, 1.61)
( 1.63, 1.61)
```

When exceeding the Beyond trapezoid range, some Arcs or Arctaps may be off-screen.

### 13.3 Coordinate Exception For Trace Type

When `arctype = true`, the Arc body usually has no strict coordinate boundary.

However:

* Its Arctaps should still follow visible and judgeable coordinate ranges.
* In practice, Arcs are usually still placed in reasonable visual areas.

---

## 14. Note Count

### 14.1 Basic Counting

| Object | Note-count behavior |
| ------ | ------------------- |
| Tap | `+1` each |
| Arctap | `+1` each |
| Hold | Counted by judgement blocks |
| Physical Arc | Mostly counted like Hold, but affected by Arc group rules |
| Zero-duration Arc | `0` |
| `skylineBoolean = true` or `designant` Arc | `0` |

### 14.2 Hold Judgement Blocks

Normally, Hold is divided by half-beat intervals according to BPM at the Hold start:

```text
30000 / bpm ms
```

Rules:

* Each judgement-block start contributes `+1`.
* The final judgement block does not contribute note count.
* When Hold crosses Timing changes, it still uses the Hold start BPM.
* When `bpm < 0`, `|bpm|` is used.
* When `bpm = 0`, the object does not exist and is not counted.
* When `bpm >= 255`, judgement-block interval changes to one beat:

```text
60000 / bpm ms
```

If Hold duration is shorter than the original judgement-block duration:

* The whole object is divided into two judgement blocks.
* The final judgement block still does not contribute note count.

### 14.3 `TimingPointDensityFactor`

If:

```aff
TimingPointDensityFactor:y
```

exists, each judgement-block interval is further divided by:

```text
y
```

### 14.4 Arc And Arc Groups

Arc note count is basically like Hold, but each Arc statement is counted separately by default.

Arcs can connect into Arc groups.

Connection conditions:

1. The x-coordinate difference between previous Arc end and next Arc start is less than `0.1`.
2. y coordinates are equal.
3. Time difference is less than `10ms`.
4. Same color is not required.
5. Same Timinggroup is not required.
6. Connection may still happen even with `noinput`.

Arc group note-count rules:

* The head Arc is counted like Hold.
* Each later Arc contributes `+1`.

---

## 15. Compatibility And Version Notes

* Green Arc readability depends on chart type and game version.
* `designant` may be treated as `false` in some old versions.
* Flick may not work normally in newer versions.
* `enwidencamera`, `enwidenlanes`, horizontally scaled Arctap, and `smoothness` are version-dependent.
* Different game versions may tolerate unknown fields, invalid parameters, and special events differently.
