"""Exercise WaveformWorker's real QThread lifetime outside the test runner process."""
import os
import subprocess
import sys
import unittest


_SCRIPT = r'''
import threading
from pathlib import Path
from PyQt6.QtCore import QEventLoop
from PyQt6.QtWidgets import QApplication, QMainWindow
from arc_slicer.ui.main_window import MainWindow
from arc_slicer.workers import WaveformWorker

app = QApplication([])
emitted = threading.Event()
release = threading.Event()

class Panel:
    def set_error(self): pass

class Window(QMainWindow):
    _on_waveform_done = MainWindow._on_waveform_done
    _on_waveform_worker_finished = MainWindow._on_waveform_worker_finished
    _release_waveform_worker = MainWindow._release_waveform_worker

class HoldingWorker(WaveformWorker):
    def run(self):
        self.done_signal.emit(self.generation, str(self.audio_path), {"generation": self.generation}, "")
        emitted.set()
        release.wait(2)

worker = HoldingWorker(7, Path("source.ogg"))
window = Window()
window._waveform_workers = [worker]
window._waveform_worker = worker
window._waveform_generation = 7
window._waveform_audio_path = "source.ogg"
window._waveform_panel = Panel()
worker.done_signal.connect(window._on_waveform_done)
worker.finished.connect(window._on_waveform_worker_finished)
worker.start()
assert emitted.wait(1)
app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
assert worker.isRunning() and window._waveform_workers == [worker]
release.set()
assert worker.wait(2000)
app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
assert window._waveform_workers == [] and window._waveform_worker is None
'''


class WaveformWorkerLifecycleTests(unittest.TestCase):
    def test_worker_is_retained_until_finished_without_qthread_destruction_warning(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertNotIn("QThread: Destroyed while thread", result.stderr)


if __name__ == "__main__":
    unittest.main()
