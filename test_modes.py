import json
import os
import unittest
from unittest.mock import Mock, patch

import commands
import modes

CONFIG = {
    "settings": {"chrome_path": "C:/Chrome/chrome.exe"},
    "work mode": {"aliases": ["work", "college mode", "student mode"], "actions": [
        {"type": "url", "value": "https://claude.ai"},
        {"type": "app", "value": "antigravity", "path": "C:/Antigravity", "args": ["C:/ST Project"]},
        {"type": "app", "value": "chatgpt"},
        {"type": "folder", "value": "C:/ST Project"},
        {"type": "app", "value": "whatsapp"},
    ]},
}


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(json.dumps(CONFIG))
        self.config_patch = patch("modes._load_config", side_effect=lambda: (self.config, None))
        self.config_patch.start()
        modes._active_modes.clear()
        modes._mode_windows.clear()
        modes._mode_already_open.clear()
        modes._chatgpt_appid, modes._chatgpt_looked_up = None, False
        self.save_patch = patch("modes._save_state")
        self.save_patch.start()
        self.record_patch = patch("modes._record_new_windows", return_value=[])
        self.record_patch.start()

    def tearDown(self):
        self.config_patch.stop()
        self.record_patch.stop()
        self.save_patch.stop()

    def _isfile(self, path):
        return path in {"C:/Chrome/chrome.exe", "C:/Antigravity/Antigravity.exe"}

    @patch("modes.time.sleep")
    @patch("commands.get_driver")
    @patch("modes.os.startfile", create=True)
    @patch("modes.subprocess.run")
    @patch("modes.subprocess.Popen")
    @patch("modes.os.listdir", return_value=["Antigravity.exe"])
    @patch("modes.os.path.isdir", side_effect=lambda path: path in {"C:/Antigravity", "C:/ST Project"})
    @patch("modes.os.path.isfile")
    @patch("app_launcher._find_target", return_value="whatsapp:")
    def test_work_mode_local_actions_in_order(self, target, isfile, _isdir, _listdir, popen, run, startfile, get_driver, _sleep):
        isfile.side_effect = self._isfile
        run.return_value.stdout = "ChatGPT_123"
        reply = commands.execute_command("open work mode")
        self.assertIn("Work Mode is on", reply)
        self.assertIn("Claude", reply)
        self.assertIn("ChatGPT", reply)
        self.assertEqual(popen.call_args_list, [
            unittest.mock.call(["C:/Chrome/chrome.exe", "--new-window", "https://claude.ai"], shell=False),
            unittest.mock.call([os.path.join("C:/Antigravity", "Antigravity.exe"), "C:/ST Project"], shell=False),
            unittest.mock.call(["explorer.exe", "shell:AppsFolder\\ChatGPT_123"], shell=False),
            unittest.mock.call(["whatsapp:"], shell=False),
        ])
        startfile.assert_called_once_with("C:/ST Project")
        get_driver.assert_not_called()

    @patch("modes.time.sleep")
    @patch("modes.os.startfile", create=True)
    @patch("modes.subprocess.Popen")
    @patch("modes.os.path.isfile", return_value=True)
    @patch("modes.os.path.isdir", return_value=True)
    @patch("modes.os.listdir", return_value=["Antigravity.exe"])
    @patch("app_launcher._find_target", return_value="whatsapp:")
    @patch("modes._chatgpt_id", return_value=None)
    def test_missing_chatgpt_continues_and_mode_can_restart(self, _chatgpt, _target, _listdir, _isdir, _isfile, popen, _startfile, _sleep):
        reply = commands.execute_command("work")
        self.assertIn("couldn't find the ChatGPT app", reply)
        first_count = popen.call_count
        self.assertIn("already on", commands.execute_command("open work mode"))
        self.assertEqual(popen.call_count, first_count)
        self.assertIn("is off", commands.execute_command("turn off work mode"))
        commands.execute_command("open work mode")
        self.assertGreater(popen.call_count, first_count)

    def test_invalid_config_unknown_modes_and_settings_are_safe(self):
        self.config_patch.stop()
        with patch("modes._load_config", return_value=({}, "The modes configuration is invalid.")):
            self.assertIn("configuration", commands.execute_command("open work mode"))
        self.config_patch.start()
        self.config = {"settings": {"chrome_path": "x"}}
        self.assertIn("don't have any", commands.execute_command("list modes"))
        # Settings is not a mode; normal app routing remains available.
        self.assertNotIn("mode called settings", commands.execute_command("open settings"))
        self.config = json.loads(json.dumps(CONFIG))
        self.assertIn("don't have a mode", commands.execute_command("open gaming mode"))

    @patch("modes.time.sleep")
    @patch("modes.subprocess.Popen")
    @patch("modes.os.path.isdir", return_value=False)
    @patch("modes.os.path.isfile", return_value=False)
    def test_invalid_actions_do_not_activate_mode(self, _isfile, _isdir, popen, _sleep):
        self.config["work mode"]["actions"] = [
            {"type": "url", "value": "ftp://unsafe.example"},
            {"type": "folder", "value": "C:/missing"},
            {"type": "url", "value": ""},
        ]
        reply = commands.execute_command("open work mode")
        self.assertIn("couldn't", reply)
        self.assertNotIn("work mode", modes._active_modes)
        popen.assert_not_called()

    @patch("modes.time.sleep")
    @patch("modes.os.startfile", create=True)
    @patch("modes.subprocess.Popen")
    @patch("modes.os.path.isfile", return_value=True)
    @patch("modes.os.path.isdir", return_value=True)
    @patch("modes.os.listdir", return_value=["Antigravity.exe"])
    @patch("app_launcher._find_target", return_value="whatsapp:")
    @patch("modes._chatgpt_id", return_value="ChatGPT_123")
    def test_mode_in_chain_and_existing_routes_remain_safe(self, *_mocks):
        with patch("commands.time.sleep"), patch("youtube_controller.search", return_value="Searching YouTube for bbs"):
            self.assertIn("Searching YouTube", commands.execute_command("open work mode then search bbs on youtube"))
        self.assertIn("Opening", commands.execute_command("open notepad"))
        self.assertFalse(commands.is_shutdown_command("stop the video"))

    @patch("modes.time.sleep")
    @patch("modes.time.monotonic", side_effect=[0, 6])
    @patch("modes._window_pid", side_effect=lambda hwnd: {20: 200, 30: 300}.get(hwnd))
    @patch("modes._window_exists", side_effect=[True, True, False, False])
    @patch("modes._close_window")
    def test_turn_off_closes_only_recorded_windows(self, close, _exists, _pid, _monotonic, _sleep):
        modes._active_modes.add("work mode")
        modes._mode_windows["work mode"] = [
            {"hwnd": 20, "pid": 200, "title": "Claude", "action_label": "Claude"},
            {"hwnd": 30, "pid": 999, "title": "Old window", "action_label": "Antigravity"},
        ]
        modes._mode_already_open["work mode"] = ["WhatsApp"]
        reply = commands.execute_command("turn off work mode")
        close.assert_called_once_with(20)
        self.assertIn("Closed Claude", reply)
        self.assertIn("WhatsApp was already open", reply)
        self.assertNotIn("work mode", modes._active_modes)
        self.assertIn("isn't on", commands.execute_command("turn off work mode"))

    @patch("modes.time.sleep")
    @patch("modes.time.monotonic", side_effect=[0, 6])
    @patch("modes._window_pid", return_value=200)
    @patch("modes._window_exists", return_value=True)
    @patch("modes._close_window")
    def test_still_open_window_is_reported_without_termination(self, close, _exists, _pid, _monotonic, _sleep):
        modes._active_modes.add("work mode")
        modes._mode_windows["work mode"] = [{"hwnd": 20, "pid": 200, "title": "IDE", "action_label": "Antigravity"}]
        reply = commands.execute_command("disable work mode")
        close.assert_called_once_with(20)
        self.assertIn("still open", reply)

    @patch("modes.time.sleep")
    @patch("modes.subprocess.Popen")
    @patch("modes.os.kill", create=True)
    def test_window_tracking_never_terminates_processes(self, kill, popen, _sleep):
        modes._active_modes.add("work mode")
        modes._mode_windows["work mode"] = [{"hwnd": 20, "pid": 200, "title": "Claude", "action_label": "Claude"}]
        with patch("modes._window_exists", return_value=False), patch("modes._window_pid", return_value=200), patch("modes._close_window"):
            commands.execute_command("end work mode")
        kill.assert_not_called()
        popen.assert_not_called()

    def test_active_flag_is_set_before_a_slow_worker_finishes(self):
        class SlowThread:
            def start(self): pass
            def join(self, _timeout): pass
            def is_alive(self): return True

        with patch("modes.threading.Thread", return_value=SlowThread()):
            self.assertIn("is starting", commands.execute_command("open work mode"))
        self.assertIn("work mode", modes._active_modes)

    @patch("modes.time.sleep")
    @patch("modes.os.startfile", create=True)
    @patch("modes.subprocess.Popen")
    @patch("modes.os.path.isfile", return_value=True)
    @patch("modes.os.path.isdir", return_value=True)
    @patch("modes.os.listdir", return_value=["Antigravity.exe"])
    @patch("app_launcher._find_target", return_value="whatsapp:")
    @patch("modes._chatgpt_id", return_value="ChatGPT_123")
    def test_alias_start_and_canonical_stop_share_state(self, *_mocks):
        commands.execute_command("work")
        self.assertIn("work mode", modes._active_modes)
        self.assertIn("is off", commands.execute_command("turn off work mode"))

    @patch("modes.time.sleep")
    @patch("modes.time.monotonic", side_effect=[0, 6])
    @patch("modes._window_pid", side_effect=lambda hwnd: {11: 101, 22: 202}.get(hwnd))
    @patch("modes._window_exists", side_effect=lambda hwnd: hwnd == 11)
    @patch("modes._close_window")
    def test_saved_state_survives_restart_and_drops_stale_windows(self, close, _exists, _pid, _monotonic, _sleep):
        state_file = Mock()
        state_file.read_text.return_value = json.dumps({
            "active_modes": ["Work Mode"],
            "windows": {"work mode": [
                {"hwnd": 11, "pid": 101, "title": "Claude", "action_label": "Claude"},
                {"hwnd": 22, "pid": 202, "title": "Stale", "action_label": "Antigravity"},
            ]},
            "already_open": {"work mode": []},
        })
        with patch("modes.STATE_PATH", state_file):
            modes._active_modes.clear(); modes._mode_windows.clear(); modes._mode_already_open.clear()
            modes._load_state()
            self.assertEqual(modes._mode_windows["work mode"], [{"hwnd": 11, "pid": 101, "title": "Claude", "action_label": "Claude"}])
            commands.execute_command("end work")
        close.assert_called_once_with(11)

    def test_missing_or_invalid_state_is_safe(self):
        with patch("modes.STATE_PATH") as state_file:
            state_file.read_text.side_effect = FileNotFoundError
            modes._load_state()
            state_file.read_text.side_effect = ValueError
            modes._load_state()
        self.assertIn("isn't on", commands.execute_command("turn off work mode"))


if __name__ == "__main__":
    unittest.main()
