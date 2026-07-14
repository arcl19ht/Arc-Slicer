"""Keep real PyQt facade imports out of Gate0's fake-Qt pytest process."""
import os
import subprocess
import sys
import unittest


_SCRIPT = r'''
import inspect, json, os, tempfile
from pathlib import Path
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
import app
from arc_slicer.ui.main_window import MainWindow as Core

for name, facade in app.MainWindow.__dict__.items():
    if not callable(facade) or not hasattr(Core, name): continue
    if "_MainWindow." not in inspect.getsource(facade): continue
    fp=list(inspect.signature(facade).parameters.values())[1:]
    cp=list(inspect.signature(getattr(Core,name)).parameters.values())[1:]
    assert [(p.name,p.kind,p.default) for p in fp] == [(p.name,p.kind,p.default) for p in cp], name
    assert not any(p.kind in (p.VAR_POSITIONAL,p.VAR_KEYWORD) for p in fp), name

q=QApplication([])
with tempfile.TemporaryDirectory() as td:
    root=Path(td); songs=root/'songs'; songs.mkdir()
    deps=app.MainWindowDependencies(config_path=root/'config.json', slides_path=root/'slides.json', out_dir=root/'out', default_songs_dir=songs)
    w=app.MainWindow(dependencies=deps)
    button=w._btn_external_choose
    before=w._external_merge_target
    app.QFileDialog.getExistingDirectory=lambda *_args: ''
    button.click()
    assert w._external_merge_target == before
    w.close()
print(json.dumps({'ok': True}))
'''


class FacadeSlotIsolationTests(unittest.TestCase):
    def test_facade_contract_and_external_target_button_in_subprocess(self):
        env = os.environ.copy(); env['QT_QPA_PLATFORM'] = 'offscreen'
        result = subprocess.run([sys.executable, '-c', _SCRIPT], text=True, encoding='utf-8', errors='replace', capture_output=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn('"ok": true', result.stdout)


if __name__ == '__main__':
    unittest.main()
