import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from easysync import addon, settings, updates
from easysync.link import WwiseLink
from easysync.ui import MainWindow
from easysync.update_dialog import UpdateDialog

APP = QApplication.instance() or QApplication([])


class AppTests(unittest.TestCase):
    def test_settings_survive_reload_and_future_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            with patch.object(settings, 'APP_DIR', Path(tmp)), patch.object(settings, 'SETTINGS_PATH', path):
                original = settings.Settings(pins=['example'], last_destination='example/path')
                original.save()
                self.assertEqual(settings.Settings.load(), original)
                self.assertEqual(settings.Settings.load().default_container, 'Random Container')
                self.assertFalse(settings.Settings.load().suggest_paths)

    def test_wwise_commands_have_no_reserved_shortcut(self):
        data = addon.build(addon.Launcher('EasySync.exe', '', '.'))
        self.assertEqual(len(data['commands']), 2)
        self.assertTrue(all('defaultShortcut' not in c for c in data['commands']))

    def test_import_cannot_be_interrupted_by_close(self):
        window = MainWindow(WwiseLink(), settings.Settings(), [])
        window._persist = lambda: None
        window.show()
        APP.processEvents()
        window._importing = True
        self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        window._importing = False
        self.assertTrue(window.close())

    def test_update_check_releases_busy_state(self):
        dialog = UpdateDialog(None)
        with patch.object(updates, 'check_latest', return_value=None):
            dialog._act()
            deadline = time.monotonic() + 4
            while dialog.busy and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(.01)
        self.assertFalse(dialog.busy)
        self.assertIn('최신', dialog.label.text())
        dialog.close()


if __name__ == '__main__':
    unittest.main()
