# AFF Slicer Engineering Notes

> This file collects slicer-oriented inferences, design choices, compatibility questions, and test ideas separated from the raw AFF format reference.
> Each item is explicitly labeled as one of: Engineering inference, Design choice, Compatibility to verify.

---

## 1. Time Semantics For Slicing

| Label | Note |
| ----- | ---- |
| Engineering inference | For slicing, distinguish point events, interval events, state events, and block/group events. Point events can usually be selected by timestamp; interval events may need overlap checks and endpoint trimming; state events may need active-state reconstruction at the slice start; Timinggroup needs separate handling for flags, internal Timing, and internal objects. |
| Design choice | Boundary policy must be explicit: closed intervals can duplicate boundary events across adjacent slices, while half-open intervals avoid duplication but may omit events exactly at the right edge. |
| Engineering inference | When event timestamps are remapped for speed changes, audio duration and event-time scale should be verified together. |

---

## 2. Header

| Label | Note |
| ----- | ---- |
| Compatibility to verify | Nonzero `AudioOffset` creates ambiguity between "slice by AFF event time" and "slice by audio playback time"; preserving, rewriting, or normalizing it should be tested with real charts. |
| Engineering inference | Header lines such as `TimingPointDensityFactor` affect later judgement density and should be preserved unless the tool intentionally changes note-count behavior. |

---

## 3. Timing

| Label | Note |
| ----- | ---- |
| Engineering inference | A slice output should have an outer `timing(0,bpm,beats);` corresponding to the effective outer Timing at the slice start. |
| Engineering inference | Timinggroup-internal Timing should not be used as the source for outer measure-line Timing. |
| Design choice | For `speed != 1`, whether to multiply Timing BPM by speed is a design decision: changing BPM may preserve measure/scroll relation to the sped-up audio, while leaving BPM unchanged preserves source scroll values after timestamp compression. This must be validated against the intended user experience. |

---

## 4. Tap And Hold

| Label | Note |
| ----- | ---- |
| Engineering inference | Hold slicing should remove non-overlapping Holds, trim crossing endpoints, keep `t1 <= t2`, and apply the same time transform to both endpoints. |
| Compatibility to verify | Zero-length Holds can result from boundary trimming; although zero-length Hold note count is defined as `0`, target-version readability should be tested. |

---

## 5. Arc And Arctap

| Label | Note |
| ----- | ---- |
| Engineering inference | For an Arc trimmed from `[t1,t2]` to `[max(t1,s),min(t2,e)]`, endpoint coordinates normally need to be recomputed from the original easing curve. Merely clamping time can change the visible/judgement trajectory. |
| Engineering inference | Arctaps should be kept only when their remapped timestamp remains inside the remapped Arc interval. |
| Compatibility to verify | Empty Arctap lists such as `arc(... )[];` should be tested against target versions; raw syntax examples do not settle whether this is accepted everywhere. |
| Engineering inference | Arc group relations can change when endpoints, coordinates, or connecting segments are trimmed; note-count or hand-continuity goals require explicit verification. |
| Compatibility to verify | Horizontally scaled Arctap (`color = 3`, `t1 = t2`) is version-dependent and should have dedicated tests rather than being assumed equivalent to ordinary Arc. |

---

## 6. Camera

| Label | Note |
| ----- | ---- |
| Engineering inference | Camera has `duration`, so treating it only as a point event can lose effects that started before the slice and remain active inside it. |
| Engineering inference | Camera slicing may need active-state reconstruction, reset/compensation at slice start, duration trimming, and duration scaling when speed changes. |

---

## 7. Scenecontrol

| Label | Note |
| ----- | ---- |
| Engineering inference | Scenecontrol includes state and presentation effects; `trackhide`, `trackshow`, `trackdisplay`, `enwidencamera`, and `enwidenlanes` may require slice-start state reconstruction. |
| Engineering inference | Scenecontrol parameters that represent durations may need trimming and speed scaling. |
| Compatibility to verify | `hidegroup` should be tested with Timinggroup slicing to confirm display state remains aligned with the intended group behavior. |

---

## 8. Timinggroup

| Label | Note |
| ----- | ---- |
| Engineering inference | Timinggroup slicing should preserve flags such as `noinput`, `fadingholds`, `anglex`, and `angley` when the group is kept. |
| Engineering inference | Internal Timing should be offset independently from outer Timing and should remain semantically internal. |
| Compatibility to verify | Empty Timinggroups produced after deleting all internal events should be tested or removed by policy. |
| Engineering inference | Since Timinggroup cannot be nested, a slicer may warn or reject nested Timinggroup input rather than recursively treating it as a generic block. |

---

## 9. Unknown Or Partially Supported Events

| Label | Note |
| ----- | ---- |
| Engineering inference | Unknown AFF lines that contain timestamps can become desynchronized if copied verbatim. |
| Design choice | A safer policy is to classify known unsupported events, preserve only when safe, and report warnings before export. |
| Compatibility to verify | Flick has a timestamp but is version-dependent; if preserved, its time remapping and target-version readability should be tested. |

---

## 10. Suggested Minimal Test Matrix

| Label | Test category | Minimal coverage |
| ----- | ------------- | ---------------- |
| Compatibility to verify | Header | `AudioOffset`, `TimingPointDensityFactor`, custom header, separator |
| Engineering inference | Timing | Effective outer Timing before slice, Timing inside slice, Timinggroup-internal Timing |
| Design choice | Tap | Left boundary, right boundary, outside interval, floating lane |
| Engineering inference | Hold | Fully contained, crosses left edge, crosses right edge, crosses both edges, zero length |
| Engineering inference | Arc | Fully contained, crosses boundaries, different easing, zero duration, Arc group |
| Compatibility to verify | Arctap | Boundary Arctap, trimmed Arctap, all Arctaps trimmed away |
| Compatibility to verify | Horizontally scaled Arctap | `color=3`, `t1=t2`, hitsound |
| Engineering inference | Camera | Starts inside interval, starts before interval and continues inside, reset |
| Engineering inference | Scenecontrol | `trackhide`, `trackdisplay`, `enwidencamera`, `enwidenlanes`, `hidegroup` |
| Engineering inference | Timinggroup | Empty flags, `noinput`, `fadingholds`, `anglex` / `angley`, empty block |
| Compatibility to verify | Flick | Time remapping and compatibility warning |
| Design choice | Speed | `0.5x`, `1.0x`, `2.0x`; verify audio duration and chart time synchronization |
| Engineering inference | Output legality | Outer `timing(0,...)`, no Arctap outside Arc interval, no nested Timinggroup in output |
