import json
import math
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path


class _Fake:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _Fake()

    def __getattr__(self, name):
        return _Fake()

    def __or__(self, other):
        return self


class _FakeSignal:
    def connect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


def _install_fake_pyqt():
    if "PyQt6" in sys.modules:
        return
    pyqt = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtgui = types.ModuleType("PyQt6.QtGui")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    qtcore.Qt = _Fake()
    qtcore.QThread = _Fake
    qtcore.pyqtSignal = lambda *args, **kwargs: _FakeSignal()
    for name in ("QTimer", "QSize", "QMimeData", "QPoint", "QRect"):
        setattr(qtcore, name, _Fake)

    for name in (
        "QColor", "QFont", "QPalette", "QPainter", "QLinearGradient",
        "QDragEnterEvent", "QDropEvent", "QDragLeaveEvent", "QMouseEvent",
        "QTextCursor",
    ):
        setattr(qtgui, name, _Fake)

    for name in (
        "QApplication", "QMainWindow", "QWidget", "QVBoxLayout", "QHBoxLayout",
        "QLabel", "QPushButton", "QComboBox", "QLineEdit", "QTextEdit",
        "QScrollArea", "QFrame", "QFileDialog", "QSizePolicy", "QSpacerItem",
        "QCheckBox", "QGridLayout", "QGraphicsDropShadowEffect",
    ):
        setattr(qtwidgets, name, _Fake)

    sys.modules["PyQt6"] = pyqt
    sys.modules["PyQt6.QtCore"] = qtcore
    sys.modules["PyQt6.QtGui"] = qtgui
    sys.modules["PyQt6.QtWidgets"] = qtwidgets


_install_fake_pyqt()

import app


def _arc_lines(aff_text):
    return [line.strip() for line in aff_text.splitlines() if line.strip().startswith("arc(")]


def _parse_arc_line(line):
    m = re.match(r"arc\(([+-]?\d+),([+-]?\d+),(.*)\)(\[(.*)\])?;", line.strip())
    if not m:
        raise AssertionError(f"Could not parse Arc line: {line}")
    return int(m.group(1)), int(m.group(2)), [part.strip() for part in m.group(3).split(",")], m.group(5)


def _assert_arc_coords_are_float_literals(testcase, fields):
    for field in (fields[0], fields[1], fields[3], fields[4]):
        testcase.assertIn(".", field)
        float(field)


class Gate0SongAndSpeedTests(unittest.TestCase):
    def test_song_dir_filter_requires_audio_and_ftr_aff(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            valid = root / "valid"
            valid.mkdir()
            (valid / "base.ogg").write_bytes(b"")
            (valid / "2.aff").write_text("-\n", encoding="utf-8")

            pack = root / "pack"
            pack.mkdir()
            incomplete = root / "incomplete"
            incomplete.mkdir()
            (incomplete / "base.ogg").write_bytes(b"")

            self.assertTrue(app.is_sliceable_song_dir(valid))
            self.assertFalse(app.is_sliceable_song_dir(pack))
            self.assertFalse(app.is_sliceable_song_dir(incomplete))

    def test_speed_rejects_invalid_values(self):
        for raw in ("", "abc", "0", "-1", "NaN", "inf", "-inf"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    app.parse_speed_text(raw)

    def test_atempo_rejects_non_positive_values(self):
        for speed in (0, -1):
            with self.subTest(speed=speed):
                with self.assertRaises(ValueError):
                    app._atempo(speed)

    def test_atempo_keeps_chain_support(self):
        self.assertEqual(app._atempo(4.0), "atempo=2.000000,atempo=2.000000")
        self.assertEqual(app._atempo(0.25), "atempo=0.500000,atempo=0.500000")

    def test_manual_songlist_scales_numeric_bpm_and_preview(self):
        meta = {
            "title_base": "Song",
            "artist": "Artist",
            "bpm": "180",
            "bpm_base": 180.0,
            "set": "single",
            "purchase": "",
            "side": 0,
            "bg": "base_light",
            "version": "1.0",
            "chart_designer": "Chart",
            "jacket_designer": "Jacket",
            "rating": 9,
            "rating_plus": False,
        }
        entry = app.make_songlist_entry("song_0_10000", 0, 0, 10000, 2.0, meta)["songs"][0]
        self.assertEqual(entry["bpm_base"], 360.0)
        self.assertEqual(entry["bpm"], "360")
        self.assertEqual(entry["audioPreviewEnd"], 5000)

    def test_manual_songlist_preserves_complex_bpm_string(self):
        meta = {
            "title_base": "Song",
            "artist": "Artist",
            "bpm": "120-180",
            "bpm_base": 150.0,
            "set": "single",
            "purchase": "",
            "side": 0,
            "bg": "base_light",
            "version": "1.0",
            "chart_designer": "Chart",
            "jacket_designer": "Jacket",
            "rating": 9,
            "rating_plus": False,
        }
        entry = app.make_songlist_entry("song_0_10000", 0, 0, 10000, 2.0, meta)["songs"][0]
        self.assertEqual(entry["bpm_base"], 300.0)
        self.assertEqual(entry["bpm"], "120-180")

    def test_fragment_songlist_scales_bpm_like_manual_path(self):
        old_path = app.SONGLIST_EXAMPLE_PATH
        with tempfile.TemporaryDirectory() as td:
            template_path = Path(td) / "songlist_example.json"
            app.SONGLIST_EXAMPLE_PATH = template_path
            try:
                template_path.write_text(
                    json.dumps({
                        "songs": [{
                            "id": "source",
                            "title_localized": {"en": "Source"},
                            "bpm": "180",
                            "bpm_base": 180.0,
                            "search_title": "remove me",
                        }]
                    }),
                    encoding="utf-8",
                )
                frag = app.make_songlist_fragment("clip_numeric", 0, 10000, 2.0)
                self.assertIsInstance(frag, dict)
                self.assertEqual(list(frag.keys()), ["songs"])
                song = frag["songs"][0]
                self.assertEqual(song["bpm_base"], 360.0)
                self.assertEqual(song["bpm"], "360")
                self.assertEqual(song["audioPreviewEnd"], 5000)

                template_path.write_text(
                    json.dumps({
                        "songs": [{
                            "id": "source",
                            "title_localized": {"en": "Source"},
                            "bpm": "120-180",
                            "bpm_base": 150.0,
                        }]
                    }),
                    encoding="utf-8",
                )
                frag = app.make_songlist_fragment("clip_complex", 0, 10000, 2.0)
                song = frag["songs"][0]
                self.assertEqual(song["bpm_base"], 300.0)
                self.assertEqual(song["bpm"], "120-180")
            finally:
                app.SONGLIST_EXAMPLE_PATH = old_path


class Gate0ArcMathTests(unittest.TestCase):
    def assertPointAlmostEqual(self, actual, expected, places=6):
        self.assertAlmostEqual(actual[0], expected[0], places=places)
        self.assertAlmostEqual(actual[1], expected[1], places=places)

    def test_easing_key_positions(self):
        p = 0.5
        cases = {
            "s": (0.5, 0.5),
            "si": (math.sin(math.pi * p / 2), 0.5),
            "so": (1 - math.cos(math.pi * p / 2), 0.5),
            "b": (0.5, 0.5),
            "sisi": (math.sin(math.pi * p / 2), math.sin(math.pi * p / 2)),
            "siso": (math.sin(math.pi * p / 2), 1 - math.cos(math.pi * p / 2)),
            "sosi": (1 - math.cos(math.pi * p / 2), math.sin(math.pi * p / 2)),
            "soso": (1 - math.cos(math.pi * p / 2), 1 - math.cos(math.pi * p / 2)),
        }
        for easing, expected in cases.items():
            with self.subTest(easing=easing):
                self.assertPointAlmostEqual(
                    app.arc_position_at(500, 0, 1000, 0, 1, 0, 1, easing),
                    expected,
                )

    def test_bezier_non_midpoint_differs_from_linear(self):
        p = 0.25
        expected = 3 * p * p - 2 * p * p * p
        point = app.arc_position_at(250, 0, 1000, 0, 1, 0, 1, "b")
        self.assertPointAlmostEqual(point, (0.15625, 0.15625))
        self.assertPointAlmostEqual(point, (expected, expected))
        self.assertNotAlmostEqual(point[0], p)

    def test_si_so_axis_mapping(self):
        si = app.arc_position_at(500, 0, 1000, 0, 1, 0, 1, "si")
        so = app.arc_position_at(500, 0, 1000, 0, 1, 0, 1, "so")
        self.assertGreater(si[0], si[1])
        self.assertLess(so[0], so[1])

    def test_siso_and_sosi_are_not_swapped(self):
        siso = app.arc_position_at(500, 0, 1000, 0, 1, 0, 1, "siso")
        sosi = app.arc_position_at(500, 0, 1000, 0, 1, 0, 1, "sosi")
        self.assertGreater(siso[0], siso[1])
        self.assertLess(sosi[0], sosi[1])

    def test_descending_coordinates_do_not_change_easing(self):
        point = app.arc_position_at(500, 0, 1000, 1, 0, 1, 0, "si")
        self.assertPointAlmostEqual(point, (1 - math.sin(math.pi / 4), 0.5))

    def test_unknown_easing_uses_linear_coordinates(self):
        point = app.arc_position_at(250, 0, 1000, 0, 1, 0, 1, "unknown")
        self.assertPointAlmostEqual(point, (0.25, 0.25))


class Gate0AffSlicingTests(unittest.TestCase):
    def test_crossing_arc_recomputes_endpoints(self):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\narc(0,1000,0,1,s,0,1,0,none,false)[arctap(500)];\n"
        out = app.slice_aff(aff, 250, 750, 1.0)
        t1, t2, fields, taps = _parse_arc_line(_arc_lines(out)[0])
        self.assertEqual((t1, t2), (0, 500))
        _assert_arc_coords_are_float_literals(self, fields)
        self.assertEqual([float(fields[i]) for i in (0, 1, 3, 4)], [0.25, 0.75, 0.25, 0.75])
        self.assertEqual(taps, "arctap(250)")

    def test_descending_coordinate_arc_keeps_forward_time(self):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\narc(0,1000,1.00,0.00,s,1.00,0.00,0,none,false);\n"
        out = app.slice_aff(aff, 250, 750, 1.0)
        t1, t2, fields, _ = _parse_arc_line(_arc_lines(out)[0])
        self.assertEqual((t1, t2), (0, 500))
        _assert_arc_coords_are_float_literals(self, fields)
        self.assertEqual([float(fields[i]) for i in (0, 1, 3, 4)], [0.75, 0.25, 0.75, 0.25])

    def test_descending_nonlinear_arc_keeps_easing_and_interpolates(self):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\narc(0,1000,1.00,0.00,si,1.00,0.00,0,none,false);\n"
        out = app.slice_aff(aff, 250, 750, 1.0)
        out_t1, out_t2, fields, _ = _parse_arc_line(_arc_lines(out)[0])

        self.assertEqual((out_t1, out_t2), (0, 500))
        self.assertEqual(fields[2], "si")
        _assert_arc_coords_are_float_literals(self, fields)

        p_start = 0.25
        p_end = 0.75
        self.assertAlmostEqual(float(fields[0]), 1 - math.sin(math.pi * p_start / 2), places=6)
        self.assertAlmostEqual(float(fields[1]), 1 - math.sin(math.pi * p_end / 2), places=6)
        self.assertAlmostEqual(float(fields[3]), 1 - p_start, places=6)
        self.assertAlmostEqual(float(fields[4]), 1 - p_end, places=6)

    def test_zero_duration_arc_does_not_interpolate(self):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\narc(500,500,0,1,si,0,1,3,none,false);\n"
        out = app.slice_aff(aff, 0, 1000, 1.0)
        t1, t2, fields, _ = _parse_arc_line(_arc_lines(out)[0])
        self.assertEqual((t1, t2), (500, 500))
        _assert_arc_coords_are_float_literals(self, fields)
        self.assertEqual([float(fields[i]) for i in (0, 1, 3, 4)], [0.0, 1.0, 0.0, 1.0])
        self.assertEqual(fields[2], "si")

    def test_closed_interval_keeps_boundary_taps_and_arctaps(self):
        aff = (
            "AudioOffset:0\n-\n"
            "timing(0,100.00,4.00);\n"
            "(250,1);\n"
            "(750,2);\n"
            "arc(250,750,0,1,s,0,1,0,none,true)[arctap(250),arctap(750)];\n"
        )
        out = app.slice_aff(aff, 250, 750, 1.0)
        self.assertIn("(0,1);", out)
        self.assertIn("(500,2);", out)
        self.assertIn("[arctap(0),arctap(500)]", out)

    def test_repro_arc_coordinates_are_float_literals(self):
        aff = (
            "AudioOffset:0\n-\n"
            "timing(0,100.00,4.00);\n"
            "arc(6000,6625,0.50,-0.25,si,0.00,0.00,0,none,false);\n"
            "arc(6000,6001,0.50,0.50,s,0.00,0.00,0,none,true)[arctap(6000)];\n"
            "arc(6000,6625,0.50,1.25,si,0.00,0.00,1,none,false);\n"
        )
        out = app.slice_aff(aff, 5938, 6625, 1.0)
        lines = _arc_lines(out)
        self.assertEqual(len(lines), 3)

        expected = [
            ((62, 687), (0.5, -0.25, 0.0, 0.0), None),
            ((62, 63), (0.5, 0.5, 0.0, 0.0), "arctap(62)"),
            ((62, 687), (0.5, 1.25, 0.0, 0.0), None),
        ]
        for line, (times, coords, taps_expected) in zip(lines, expected):
            t1, t2, fields, taps = _parse_arc_line(line)
            self.assertEqual((t1, t2), times)
            _assert_arc_coords_are_float_literals(self, fields)
            self.assertEqual([float(fields[i]) for i in (0, 1, 3, 4)], list(coords))
            if taps_expected is None:
                self.assertIsNone(taps)
            else:
                self.assertEqual(taps, taps_expected)
                self.assertNotIn(".", taps)

    def test_arc_coords_never_emit_bare_integers(self):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\narc(0,1000,0,1,s,0,1,0,none,false);\n"
        out = app.slice_aff(aff, 0, 1000, 1.0)
        _, _, fields, _ = _parse_arc_line(_arc_lines(out)[0])
        _assert_arc_coords_are_float_literals(self, fields)
        self.assertEqual([float(fields[i]) for i in (0, 1, 3, 4)], [0.0, 1.0, 0.0, 1.0])

    def test_hold_crossing_slice_is_clamped(self):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\nhold(0,1000,2);\n"
        out = app.slice_aff(aff, 250, 750, 1.0)
        self.assertIn("hold(0,500,2);", out)

    def test_hold_boundary_zero_length_is_kept_by_closed_interval(self):
        aff = (
            "AudioOffset:0\n-\n"
            "timing(0,100.00,4.00);\n"
            "hold(0,250,2);\n"
            "hold(750,1000,3);\n"
        )
        out = app.slice_aff(aff, 250, 750, 1.0)
        self.assertIn("hold(0,0,2);", out)
        self.assertIn("hold(500,500,3);", out)

    def test_timing_bpm_scales_with_speed(self):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\ntiming(1000,120.00,4.00);\n(1000,1);\n"
        out = app.slice_aff(aff, 1000, 1200, 2.0)
        self.assertIn("timing(0,240.00,4.00);", out)
        self.assertIn("(0,1);", out)

    def test_outer_timing_does_not_use_timinggroup_timing(self):
        aff = (
            "AudioOffset:0\n-\n"
            "timing(0,100.00,4.00);\n"
            "timinggroup(){\n"
            "timing(900,999.00,4.00);\n"
            "};\n"
            "(1000,1);\n"
        )
        out = app.slice_aff(aff, 1000, 1100, 2.0)
        self.assertIn("timing(0,200.00,4.00);", out)
        self.assertNotIn("1998.00", out)

    def test_timinggroup_inserts_effective_internal_timing(self):
        aff = (
            "AudioOffset:0\n-\n"
            "timing(0,100.00,4.00);\n"
            "timinggroup(noinput){\n"
            "timing(0,50.00,4.00);\n"
            "(1200,1);\n"
            "};\n"
        )
        out = app.slice_aff(aff, 1000, 1300, 2.0)
        self.assertIn("timinggroup(noinput){\n", out)
        self.assertIn("timing(0,100.00,4.00);\n(100,1);", out)

    def test_outer_timing_is_not_satisfied_by_timinggroup_timing_zero(self):
        aff = (
            "AudioOffset:0\n-\n"
            "timing(0,100.00,4.00);\n"
            "timinggroup(noinput){\n"
            "timing(0,50.00,4.00);\n"
            "(1200,1);\n"
            "};\n"
        )
        out = app.slice_aff(aff, 1000, 1300, 2.0)
        _, body = app._extract_header_and_body(out)
        outer_timings = app._parse_outer_timings(body)

        self.assertIn((0, 200.0, 4.0), outer_timings)
        self.assertIn("timinggroup(noinput){\n", out)
        self.assertIn("timing(0,100.00,4.00);\n(100,1);", out)

    def test_timinggroup_uses_last_internal_timing_before_slice(self):
        aff = (
            "AudioOffset:0\n-\n"
            "timing(0,100.00,4.00);\n"
            "timinggroup(noinput){\n"
            "timing(0,50.00,4.00);\n"
            "timing(800,75.00,4.00);\n"
            "(1200,1);\n"
            "};\n"
        )
        out = app.slice_aff(aff, 1000, 1300, 2.0)
        self.assertIn("timinggroup(noinput){\n", out)
        self.assertIn("timing(0,150.00,4.00);\n(100,1);", out)
        self.assertNotIn("timing(0,100.00,4.00);\n(100,1);", out)

    def test_empty_timinggroup_is_removed(self):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\ntiminggroup(){\n(100,1);\n};\n"
        out = app.slice_aff(aff, 1000, 1300, 1.0)
        self.assertNotIn("timinggroup", out)

    def test_nonzero_audio_offset_warns_and_preserves_header(self):
        warnings = []
        aff = "AudioOffset:-20\nTimingPointDensityFactor:1\n-\ntiming(0,100.00,4.00);\n(0,1);\n"
        out = app.slice_aff(aff, 0, 100, 1.0, warnings)
        self.assertIn("AudioOffset:-20", out)
        self.assertIn(app.AUDIO_OFFSET_WARNING, warnings)

    def test_camera_scenecontrol_warning_once(self):
        warnings = []
        aff = (
            "AudioOffset:0\n-\n"
            "timing(0,100.00,4.00);\n"
            "camera(100,0,0,0,0,0,0,qi,1000);\n"
            "scenecontrol(200,trackdisplay,1.00,0);\n"
        )
        app.slice_aff(aff, 0, 500, 1.0, warnings)
        self.assertEqual(warnings.count(app.CAMERA_SCENE_WARNING), 1)

    def test_audio_offset_and_camera_warnings_each_once(self):
        warnings = []
        aff = (
            "AudioOffset:12\n-\n"
            "timing(0,100.00,4.00);\n"
            "camera(100,0,0,0,0,0,0,qi,1000);\n"
            "scenecontrol(200,trackdisplay,1.00,0);\n"
        )
        app.slice_aff(aff, 0, 500, 1.0, warnings)
        self.assertEqual(warnings.count(app.AUDIO_OFFSET_WARNING), 1)
        self.assertEqual(warnings.count(app.CAMERA_SCENE_WARNING), 1)


class Gate0NonlinearArcWarningTests(unittest.TestCase):
    def _warnings(self, aff_body, segments):
        aff = "AudioOffset:0\n-\ntiming(0,100.00,4.00);\n" + aff_body
        return app.find_nonlinear_arc_cut_warnings(aff, segments)

    def test_start_boundary_cutting_nonlinear_arc_warns(self):
        warnings = self._warnings(
            "arc(0,1000,0,1,si,0,1,0,none,false);\n",
            [{"s": 250, "e": 1000}],
        )
        self.assertEqual(len(warnings[0]["start"]), 1)
        self.assertEqual(warnings[0]["start"][0]["easing"], "si")
        self.assertEqual(warnings[0]["end"], [])

    def test_end_boundary_cutting_nonlinear_arc_warns(self):
        warnings = self._warnings(
            "arc(0,1000,0,1,so,0,1,0,none,false);\n",
            [{"s": 0, "e": 750}],
        )
        self.assertEqual(warnings[0]["start"], [])
        self.assertEqual(len(warnings[0]["end"]), 1)
        self.assertEqual(warnings[0]["end"][0]["easing"], "so")

    def test_both_boundaries_cutting_same_nonlinear_arc_warn(self):
        warnings = self._warnings(
            "arc(0,1000,0,1,b,0,1,0,none,false);\n",
            [{"s": 250, "e": 750}],
        )
        self.assertEqual(len(warnings[0]["start"]), 1)
        self.assertEqual(len(warnings[0]["end"]), 1)
        self.assertEqual(warnings[0]["start"][0]["easing"], "b")
        self.assertEqual(warnings[0]["end"][0]["easing"], "b")

    def test_linear_arc_has_no_cut_warning(self):
        warnings = self._warnings(
            "arc(0,1000,0,1,s,0,1,0,none,false);\n",
            [{"s": 250, "e": 750}],
        )
        self.assertEqual(warnings[0], {"start": [], "end": []})

    def test_boundary_aligned_with_arc_endpoint_has_no_warning(self):
        warnings = self._warnings(
            "arc(0,1000,0,1,si,0,1,0,none,false);\n",
            [{"s": 0, "e": 1000}],
        )
        self.assertEqual(warnings[0], {"start": [], "end": []})

    def test_fully_contained_arc_has_no_cut_warning(self):
        warnings = self._warnings(
            "arc(200,800,0,1,sisi,0,1,0,none,false);\n",
            [{"s": 0, "e": 1000}],
        )
        self.assertEqual(warnings[0], {"start": [], "end": []})

    def test_timinggroup_arc_with_arctap_is_detected(self):
        warnings = self._warnings(
            "timinggroup(noinput){\n"
            "arc(0,1000,0,1,siso,0,1,0,none,false)[arctap(500)];\n"
            "};\n",
            [{"s": 250, "e": 750}],
        )
        self.assertEqual(len(warnings[0]["start"]), 1)
        self.assertEqual(len(warnings[0]["end"]), 1)
        self.assertEqual(warnings[0]["start"][0]["easing"], "siso")
        self.assertEqual(warnings[0]["end"][0]["easing"], "siso")

    def test_zero_duration_and_unknown_easing_have_no_warning(self):
        warnings = self._warnings(
            "arc(500,500,0,1,si,0,1,0,none,false);\n"
            "arc(0,1000,0,1,unknown,0,1,0,none,false);\n",
            [{"s": 250, "e": 750}],
        )
        self.assertEqual(warnings[0], {"start": [], "end": []})

    def test_multiple_segments_are_reported_independently(self):
        warnings = self._warnings(
            "arc(0,1000,0,1,soso,0,1,0,none,false);\n",
            [
                {"s": 100, "e": 200},
                {"s": 1000, "e": 1200},
                {"s": 900, "e": 1100},
            ],
        )
        self.assertEqual(len(warnings[0]["start"]), 1)
        self.assertEqual(len(warnings[0]["end"]), 1)
        self.assertEqual(warnings[1], {"start": [], "end": []})
        self.assertEqual(len(warnings[2]["start"]), 1)
        self.assertEqual(warnings[2]["end"], [])

    def test_web_api_get_arc_cut_warnings_reads_current_songs_dir(self):
        old_config = app.CONFIG_PATH
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            songs_dir = root / "songs"
            song_dir = songs_dir / "song"
            song_dir.mkdir(parents=True)
            (song_dir / "base.ogg").write_bytes(b"")
            (song_dir / "2.aff").write_text(
                "AudioOffset:0\n-\ntiming(0,100.00,4.00);\n"
                "arc(0,1000,0,1,si,0,1,0,none,false);\n",
                encoding="utf-8",
            )
            app.CONFIG_PATH = root / "config.json"
            app.CONFIG_PATH.write_text(json.dumps({"songs_dir": str(songs_dir)}), encoding="utf-8")
            try:
                result = app.ArcWebApi().get_arc_cut_warnings("song", [{"s": 250, "e": 750}])
            finally:
                app.CONFIG_PATH = old_config

        self.assertEqual(len(result[0]["start"]), 1)
        self.assertEqual(len(result[0]["end"]), 1)
        self.assertEqual(result[0]["start"][0]["easing"], "si")

    def test_web_api_allows_song_dir_junction_inside_songs_dir(self):
        old_config = app.CONFIG_PATH
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_song = root / "source_song"
            songs_dir = root / "songs"
            linked_song = songs_dir / "song"
            source_song.mkdir()
            songs_dir.mkdir()
            (source_song / "base.ogg").write_bytes(b"")
            (source_song / "2.aff").write_text(
                "AudioOffset:0\n-\ntiming(0,100.00,4.00);\n"
                "arc(0,1000,0,1,so,0,1,0,none,false);\n",
                encoding="utf-8",
            )
            if app.sys.platform == "win32":
                app.subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(linked_song), str(source_song)],
                    check=True,
                    capture_output=True,
                    creationflags=app.subprocess.CREATE_NO_WINDOW,
                )
            else:
                linked_song.symlink_to(source_song, target_is_directory=True)
            app.CONFIG_PATH = root / "config.json"
            app.CONFIG_PATH.write_text(json.dumps({"songs_dir": str(songs_dir)}), encoding="utf-8")
            try:
                result = app.ArcWebApi().get_arc_cut_warnings("song", [{"s": 250, "e": 750}])
            finally:
                app.CONFIG_PATH = old_config

        self.assertNotIn("__error", result)
        self.assertEqual(len(result[0]["start"]), 1)
        self.assertEqual(len(result[0]["end"]), 1)
        self.assertEqual(result[0]["start"][0]["easing"], "so")


class Gate0UiSaveTests(unittest.TestCase):
    class _TextBox:
        def __init__(self, text):
            self._text = text

        def text(self):
            return self._text

    class _SongBox:
        def currentText(self):
            return "song"

    class _SonglistPanel:
        def get_meta(self):
            return None

    def test_save_slides_catches_invalid_speed_before_writing(self):
        old_path = app.SLIDES_PATH
        with tempfile.TemporaryDirectory() as td:
            slides_path = Path(td) / "slides.json"
            slides_path.write_text("original", encoding="utf-8")
            app.SLIDES_PATH = slides_path

            win = object.__new__(app.MainWindow)
            win._speed_input = self._TextBox("abc")
            win._song_box = self._SongBox()
            win._rows = []
            win._songlist_panel = self._SonglistPanel()
            logs = []
            win._push_log = lambda text, kind="normal": logs.append((text, kind))

            try:
                app.MainWindow._save_slides(win)
            finally:
                app.SLIDES_PATH = old_path

            self.assertEqual(slides_path.read_text(encoding="utf-8"), "original")
            self.assertTrue(any("速度无效" in text for text, _ in logs))
            self.assertTrue(all(kind == "err" for _, kind in logs))


class Gate0WebApiImportTests(unittest.TestCase):
    def test_add_song_folder_path_imports_valid_song_dir_without_dialog(self):
        old_config = app.CONFIG_PATH
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "source_song"
            songs_dir = root / "songs"
            src.mkdir()
            (src / "base.ogg").write_bytes(b"")
            (src / "2.aff").write_text("-\n", encoding="utf-8")
            app.CONFIG_PATH = root / "config.json"
            app.CONFIG_PATH.write_text(json.dumps({"songs_dir": str(songs_dir)}), encoding="utf-8")
            try:
                api = app.ArcWebApi()
                api._window = object()
                result = api.add_song_folder_path(str(src))
            finally:
                app.CONFIG_PATH = old_config

            self.assertTrue(result["ok"])
            self.assertEqual(result["song_id"], "source_song")
            self.assertTrue((songs_dir / "source_song" / "2.aff").exists())

    def test_add_song_folder_path_rejects_empty_missing_and_file_paths(self):
        old_config = app.CONFIG_PATH
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            songs_dir = root / "songs"
            file_path = root / "not_a_dir.aff"
            file_path.write_text("-", encoding="utf-8")
            app.CONFIG_PATH = root / "config.json"
            app.CONFIG_PATH.write_text(json.dumps({"songs_dir": str(songs_dir)}), encoding="utf-8")
            try:
                api = app.ArcWebApi()
                cases = ["", str(root / "missing"), str(file_path)]
                results = [api.add_song_folder_path(path) for path in cases]
            finally:
                app.CONFIG_PATH = old_config

            self.assertTrue(all(not result["ok"] for result in results))
            self.assertIn("路径为空", results[0]["msg"])
            self.assertIn("目录不存在", results[1]["msg"])
            self.assertIn("请拖入歌曲文件夹", results[2]["msg"])
            self.assertFalse(songs_dir.exists())


if __name__ == "__main__":
    unittest.main()
