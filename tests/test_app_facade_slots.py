import inspect
import unittest

import app
from arc_slicer.ui.main_window import MainWindow as CoreMainWindow


class FacadeSlotSignatureTests(unittest.TestCase):
    def test_forwarding_facades_match_core_signatures(self):
        for name, facade in app.MainWindow.__dict__.items():
            if not callable(facade) or not hasattr(CoreMainWindow, name):
                continue
            source = inspect.getsource(facade)
            if "_MainWindow." not in source:
                continue
            facade_params = list(inspect.signature(facade).parameters.values())[1:]
            core_params = list(inspect.signature(getattr(CoreMainWindow, name)).parameters.values())[1:]
            self.assertEqual([(p.kind, p.default is inspect.Parameter.empty) for p in facade_params], [(p.kind, p.default is inspect.Parameter.empty) for p in core_params], name)
            self.assertFalse(any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in facade_params), name)


if __name__ == "__main__":
    unittest.main()
