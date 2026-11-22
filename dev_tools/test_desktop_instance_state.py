"""验证桌面客户端启动时如何认领档案中的进程。"""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from module.device.method import desktop_impl as desktop
from module.exception import EmulatorNotRunningError


class DesktopInstanceStateTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        profile = directory.name
        self.state_path = Path(profile) / 'oas_instance.json'
        self.pid = os.getpid()
        self.window = desktop.DesktopWindow()
        self.window.config = SimpleNamespace(script=SimpleNamespace(desktop=SimpleNamespace(
            enable=True, game_path=profile, profile_dir=profile)))

    def test_legacy_pid_of_unrelated_process_does_not_block_start(self):
        self.state_path.write_text(json.dumps({'pid': self.pid}), encoding='utf-8')
        with (
            patch.object(desktop, 'desktop_install_root', return_value=str(self.state_path.parent)),
            patch.object(desktop, 'desktop_game_exe', return_value='onmyoji.exe'),
            patch.object(desktop, 'desktop_prepare_profile_if_needed'),
            patch.object(desktop, 'desktop_spawn_client', return_value=None) as spawn,
        ):
            self.assertFalse(desktop.desktop_launch_instance(self.window.config))
            spawn.assert_called_once()
            self.assertEqual(self.window._desktop_locate_window(), (None, 0))

    def test_legacy_pid_of_live_client_waits_for_its_window(self):
        self.state_path.write_text(json.dumps({'pid': self.pid}), encoding='utf-8')
        with (
            patch.object(desktop, 'desktop_install_root', return_value=str(self.state_path.parent)),
            patch.object(desktop, '_desktop_pid_under_root', return_value=True),
            patch.object(desktop, 'find_desktop_window_by_pid', side_effect=EmulatorNotRunningError),
        ):
            self.assertEqual(self.window._desktop_locate_window(), (self.pid, 0))
            os.utime(self.state_path, (0, 0))
            self.assertEqual(self.window._desktop_locate_window(), (None, 0))

    def test_same_pid_with_different_creation_time_is_ignored(self):
        desktop.desktop_write_instance_state(self.state_path.parent, self.pid)
        with patch.object(desktop, 'find_desktop_window_by_pid', return_value=123):
            self.assertEqual(self.window._desktop_locate_window(), (self.pid, 123))
        state = json.loads(self.state_path.read_text(encoding='utf-8'))
        state['started_at'] -= 1
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        self.assertEqual(self.window._desktop_locate_window(), (None, 0))


if __name__ == '__main__':
    unittest.main()
