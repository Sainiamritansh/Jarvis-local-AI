import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Keep imports and test execution independent of optional desktop packages.
browser = types.ModuleType("browser_driver")
browser.get_driver = Mock()
browser.quit_driver = Mock()
browser.set_browser = Mock()
desktop = types.ModuleType("desktop_commands")
desktop.launch_whatsapp = Mock(return_value="Opening WhatsApp")
desktop.open_app = Mock(return_value="Opening executable")
desktop.send_whatsapp_message_to = Mock(return_value="Message sent")
sys.modules.setdefault("browser_driver", browser)
sys.modules.setdefault("desktop_commands", desktop)

import app_launcher
import commands
import youtube_controller

class Link:
    def __init__(self, title, href): self.title, self.href, self.text = title, href, title
    def get_attribute(self, name): return self.href if name == "href" else self.title if name == "title" else ""

class Driver:
    def __init__(self, links=()):
        self.links, self.urls, self.scripts, self.current_url = list(links), [], [], ""
        self.title, self.page_source, self.scan_responses = "YouTube", "", None
        self.playback_states, self._state_calls, self.ad_showing = None, 0, False
    def get(self, url): self.urls.append(url); self.current_url = url
    def find_elements(self, *_): return self.links
    def execute_script(self, script, *_):
        self.scripts.append(script)
        if "querySelectorAll('a[href*=" in script:
            if self.scan_responses is not None:
                return self.scan_responses.pop(0) if self.scan_responses else []
            return [{"href": link.href, "title": link.title} for link in self.links]
        if "readyState" in script and "adShowing" in script:
            if self.playback_states is not None:
                return self.playback_states.pop(0) if self.playback_states else {"exists": False}
            self._state_calls += 1
            return {"exists": True, "paused": False, "ended": False,
                    "currentTime": float(self._state_calls), "readyState": 4,
                    "adShowing": self.ad_showing}
        if "v.pause()" in script: return {"ok": True, "time": 924}
        if "v.play()" in script: return {"ok": True}
        return True
    def save_screenshot(self, *_): return True

class VoiceFeaturesTests(unittest.TestCase):
    def setUp(self):
        youtube_controller.session.query = ""
        youtube_controller.session.results = []
        self.driver = Driver([Link("First Cats", "https://www.youtube.com/watch?v=one"), Link("Second Cats", "https://www.youtube.com/watch?v=two")])
        self.driver_patch = patch("youtube_controller.get_driver", return_value=self.driver)
        self.driver_patch.start()
        self.video_sleep_patch = patch("youtube_controller.time.sleep")
        self.video_sleep_patch.start()

    def tearDown(self):
        self.video_sleep_patch.stop()
        self.driver_patch.stop()

    def test_search_stores_query_and_results(self):
        self.assertIn("Searching", commands.execute_command("search cats on youtube"))
        self.assertEqual(youtube_controller.session.query, "cats")
        self.assertEqual(len(youtube_controller.session.results), 2)

    def test_play_generic_uses_first_previous_result(self):
        commands.execute_command("search cats")
        self.assertIn("First Cats", commands.execute_command("play a video"))
        self.assertEqual(self.driver.urls[-1], "https://www.youtube.com/watch?v=one")

    def test_play_second_uses_second_previous_result(self):
        commands.execute_command("search cats")
        self.assertIn("Second Cats", commands.execute_command("play the second video"))
        self.assertEqual(self.driver.urls[-1], "https://www.youtube.com/watch?v=two")

    def test_generic_play_without_search_is_safe(self):
        self.assertIn("First Cats", commands.execute_command("play a video"))

    @patch("app_launcher.platform.system", return_value="Windows")
    @patch("app_launcher._find_target", return_value="edge.exe")
    @patch("app_launcher._launch")
    def test_open_edge(self, launch, *_):
        self.assertIn("Microsoft Edge", commands.execute_command("open Microsoft Edge")); launch.assert_called_once()

    @patch("app_launcher.platform.system", return_value="Windows")
    @patch("app_launcher._find_target", return_value="explorer.exe")
    @patch("app_launcher._launch")
    def test_open_explorer(self, launch, *_):
        self.assertIn("File Explorer", commands.execute_command("launch File Explorer")); launch.assert_called_once()

    def test_aliases(self):
        expected = {"edge": "Microsoft Edge", "ms edge": "Microsoft Edge", "note pad": "Notepad", "vs code": "Visual Studio Code", "calc": "Calculator"}
        for alias, name in expected.items(): self.assertEqual(app_launcher.resolve_app(alias).name, name)

    @patch("app_launcher.platform.system", return_value="Windows")
    @patch("app_launcher._find_target", return_value=None)
    def test_unknown_or_not_installed_is_clear(self, *_):
        self.assertIn("not installed", app_launcher.launch_app("edge").lower())
        self.assertIn("don't know", app_launcher.launch_app("made up app").lower())

    def test_dangerous_unknown_text_runs_nothing(self):
        with patch("subprocess.Popen") as popen, patch.object(app_launcher, "_launch") as launch:
            self.assertEqual(commands.execute_command("format c drive"), "Command not recognized")
            self.assertEqual(commands.execute_command("open app rm -rf"), "Command not recognized")
            popen.assert_not_called(); launch.assert_not_called()

    def test_existing_routes_and_shutdown_predicate(self):
        with patch("commands.get_driver", return_value=self.driver):
            self.assertEqual(commands.execute_command("scroll down"), "Scrolled down")
            self.assertIn("Screenshot saved", commands.execute_command("screenshot"))
        self.assertIn("Searching", commands.execute_command("search cats"))
        with patch("commands.send_whatsapp_message_to", return_value="Message sent"):
            self.assertEqual(commands.execute_command("message sam saying hello"), "Message sent")
        self.assertFalse(commands.is_shutdown_command("stop the video"))
        self.assertTrue(commands.is_shutdown_command("shutdown"))

    @patch("commands.time.sleep")
    @patch("commands.set_browser")
    @patch("app_launcher._launch")
    def test_chains_open_search_and_play_in_order(self, launch, set_browser, _sleep):
        reply = commands.execute_command(
            "open microsoft edge then search bbs on yt then play the second video"
        )
        self.assertIn("Opening Microsoft Edge", reply)
        self.assertIn("Searching YouTube for bbs", reply)
        self.assertIn("Second Cats", reply)
        set_browser.assert_called_once_with("edge")
        launch.assert_not_called()
        self.assertEqual(youtube_controller.session.query, "bbs")
        self.assertEqual(self.driver.urls[-1], "https://www.youtube.com/watch?v=two")

    @patch("commands.time.sleep")
    def test_search_play_chain_forms(self, _sleep):
        for utterance in (
            "search bbs and play the second video",
            "search bbs then play any video",
            "search bbs play the first video",
        ):
            with self.subTest(utterance=utterance):
                self.driver.urls.clear()
                reply = commands.execute_command(utterance)
                self.assertIn("Searching YouTube for bbs", reply)
                self.assertIn("Playing", reply)

    def test_and_inside_titles_does_not_split(self):
        with patch("youtube_controller.search", return_value="Searching YouTube for tom and jerry") as search:
            commands.execute_command("search tom and jerry")
            search.assert_called_once_with("tom and jerry")
        with patch("youtube_controller.play_title", return_value="Playing Fast and Furious") as play:
            commands.execute_command("play fast and furious")
            play.assert_called_once_with("fast and furious")

    def test_message_body_is_never_split(self):
        with patch("commands.send_whatsapp_message_to", return_value="Message sent") as send:
            self.assertEqual(commands.execute_command("message rahul saying hi and play music"), "Message sent")
            send.assert_called_once_with("rahul", "hi and play music")

    @patch("commands.time.sleep")
    def test_failed_step_stops_chain(self, _sleep):
        reply = commands.execute_command("open app imaginary then search bbs")
        self.assertIn("Step 1 failed", reply)
        self.assertEqual(youtube_controller.session.query, "")

    def test_more_than_five_steps_is_safe(self):
        reply = commands.execute_command(
            "search one then search two then search three then search four then search five then search six"
        )
        self.assertIn("up to 5", reply)
        self.assertEqual(youtube_controller.session.query, "")

    def test_stop_and_pause_preserve_position(self):
        self.assertEqual(youtube_controller.control("stop"), "Stopped at 15 minutes 24 seconds.")
        self.assertNotIn("currentTime=0", self.driver.scripts[-1])
        self.assertNotIn("currentTime = 0", self.driver.scripts[-1])
        self.assertEqual(youtube_controller.control("pause"), "Paused at 15 minutes 24 seconds.")
        self.assertNotIn("currentTime=0", self.driver.scripts[-1])

    def test_stop_then_resume_never_seeks(self):
        youtube_controller.control("stop")
        youtube_controller.control("resume")
        self.assertEqual(youtube_controller.control("resume"), "Resuming.")
        self.assertTrue(all("currentTime=0" not in script for script in self.driver.scripts))

    def test_playing_the_current_video_does_not_reload_it(self):
        self.driver.current_url = "https://www.youtube.com/watch?v=one"
        before = list(self.driver.urls)
        self.assertIn("First Cats", youtube_controller._start(("First Cats", self.driver.current_url)))
        self.assertEqual(self.driver.urls, before)

    @patch("app_launcher.platform.system", return_value="Windows")
    @patch("app_launcher._find_target", return_value="edge.exe")
    @patch("app_launcher._launch")
    def test_standalone_edge_still_uses_app_launcher(self, launch, *_):
        self.assertIn("Opening Microsoft Edge", commands.execute_command("open microsoft edge"))
        launch.assert_called_once_with("edge.exe")

    @patch("commands.time.sleep")
    @patch("commands.set_browser")
    @patch("app_launcher._launch")
    def test_chrome_chain_uses_selenium_not_app_launcher(self, launch, set_browser, _sleep):
        reply = commands.execute_command("open chrome then search bbs on yt then play the second video")
        self.assertIn("Opening Google Chrome", reply)
        set_browser.assert_called_once_with("chrome")
        launch.assert_not_called()
        self.assertEqual(self.driver.urls[-1], "https://www.youtube.com/watch?v=two")

    def test_dom_scan_dedupes_in_order_and_excludes_shorts(self):
        self.driver.scan_responses = [[
            {"href": "https://www.youtube.com/watch?v=abcdefghijk", "title": "First"},
            {"href": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Duplicate"},
            {"href": "https://www.youtube.com/shorts/zzzzzzzzzzz", "title": "Short"},
            {"href": "https://www.youtube.com/watch?v=lmnopqrstuv", "title": "Second"},
        ]]
        self.assertIn("Searching", youtube_controller.search("lofi"))
        self.assertEqual(youtube_controller.session.results, [
            ("First", "https://www.youtube.com/watch?v=abcdefghijk"),
            ("Second", "https://www.youtube.com/watch?v=lmnopqrstuv"),
        ])

    @patch("youtube_controller.time.sleep")
    @patch("youtube_controller.time.monotonic", side_effect=[0, 0])
    def test_empty_poll_then_dom_links_succeeds(self, _monotonic, _sleep):
        self.driver.scan_responses = [[], [{"href": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Found"}]]
        self.assertIn("Searching", youtube_controller.search("lofi"))
        self.assertEqual(youtube_controller.session.results[0][0], "Found")

    @patch("youtube_controller.RESULT_WAIT_SECONDS", 0)
    def test_page_source_fallback(self):
        self.driver.scan_responses = [[]]
        self.driver.page_source = '"videoId":"abcdefghijk" xx "videoId":"abcdefghijk" xx "videoId":"lmnopqrstuv"'
        self.assertIn("Searching", youtube_controller.search("lofi"))
        self.assertEqual(youtube_controller.session.results, [
            ("video 1", "https://www.youtube.com/watch?v=abcdefghijk"),
            ("video 2", "https://www.youtube.com/watch?v=lmnopqrstuv"),
        ])

    @patch("youtube_controller.RESULT_WAIT_SECONDS", 0)
    def test_empty_results_reply_and_session(self):
        self.driver.scan_responses = [[], []]
        self.assertIn("couldn't find", youtube_controller.search("empty"))
        self.assertEqual(youtube_controller.session.results, [])

    @patch("commands.time.sleep")
    def test_chain_search_then_second_video_uses_one_driver(self, _sleep):
        reply = commands.execute_command("search lofi music and play the second video")
        self.assertIn("Searching YouTube for lofi music", reply)
        self.assertIn("Second Cats", reply)
        self.assertEqual(self.driver.urls[-1], "https://www.youtube.com/watch?v=two")

    @patch("youtube_controller.time.sleep")
    def test_playing_video_with_progress_is_confirmed(self, _sleep):
        self.assertEqual(youtube_controller._start(("First Cats", "https://www.youtube.com/watch?v=one")), "Playing First Cats.")

    @patch("youtube_controller.time.sleep")
    def test_play_escalation_starts_paused_video_in_order(self, _sleep):
        paused = {"exists": True, "paused": True, "ended": False, "currentTime": 0, "readyState": 4, "adShowing": False}
        moving_one = {"exists": True, "paused": False, "ended": False, "currentTime": 0, "readyState": 4, "adShowing": False}
        moving_two = {**moving_one, "currentTime": 1}
        self.driver.playback_states = [paused, paused, moving_one, moving_two]
        self.assertIn("Playing First Cats", youtube_controller._start(("First Cats", "https://www.youtube.com/watch?v=one")))
        escalation_scripts = [script for script in self.driver.scripts if "v.play()" in script]
        self.assertEqual(len(escalation_scripts), 1)
        self.assertFalse(any("ytp-play-button" in script for script in self.driver.scripts))

    @patch("youtube_controller.time.sleep")
    def test_no_progress_is_not_claimed_as_playing(self, _sleep):
        state = {"exists": True, "paused": False, "ended": False, "currentTime": 3, "readyState": 4, "adShowing": False}
        with patch("youtube_controller._wait_for_ready_video", return_value=state), patch("youtube_controller._confirm_playing", return_value=(False, state)), patch("youtube_controller._escalate_playback", return_value=True):
            reply = youtube_controller._start(("First Cats", "https://www.youtube.com/watch?v=one"))
        self.assertIn("couldn't confirm", reply)
        self.assertNotIn("Playing First Cats", reply)

    @patch("youtube_controller.time.sleep")
    def test_ad_playback_note_and_no_click_when_already_playing(self, _sleep):
        self.driver.ad_showing = True
        reply = youtube_controller._start(("First Cats", "https://www.youtube.com/watch?v=one"))
        self.assertIn("an ad is playing first", reply)
        self.assertFalse(any(".click()" in script or "ytp-play-button" in script for script in self.driver.scripts))

    def test_browser_options_include_autoplay_flag(self):
        source = Path("browser_driver.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("--autoplay-policy=no-user-gesture-required"), 1)
        self.assertIn("webdriver.Edge(options=_browser_options(\"edge\"))", source)
        self.assertIn("webdriver.Chrome(options=_browser_options(\"chrome\"))", source)

if __name__ == "__main__": unittest.main()
