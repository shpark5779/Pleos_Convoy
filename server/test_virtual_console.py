import unittest
import io
from http.client import RemoteDisconnected
from unittest.mock import patch

from virtual_console import VirtualConsole


class VirtualConsoleTest(unittest.TestCase):
    def test_disconnected_request_retries_same_absolute_control_and_is_bounded(self):
        console = VirtualConsole("emulator-test", 18088)
        with patch("virtual_console.time.sleep"), patch("virtual_console.urlopen", side_effect=[
                RemoteDisconnected("closed"), io.BytesIO(b'{"ok": true}')]) as request:
            self.assertEqual(console.request("/vehicle/controls?speed=20", "PUT"), {"ok": True})
        self.assertEqual([c.args[0].full_url for c in request.call_args_list],
                         [console.base+"/vehicle/controls?speed=20"]*2)
        with patch("virtual_console.time.sleep"), patch("virtual_console.urlopen",
                side_effect=RemoteDisconnected("closed")) as request:
            with self.assertRaises(RemoteDisconnected):
                console.request("/vehicle/state")
        self.assertEqual(request.call_count, 3)

    def test_motion_wait_brake_and_stop_before_park(self):
        console = VirtualConsole("emulator-test", 18088)
        with patch.object(console, "request", return_value={}) as request:
            console.motion(36)
            console.motion(0)
            console.motion(36)
            console.motion(0, parked=True)
        paths = [c.args[0] for c in request.call_args_list]
        self.assertEqual(paths[0], "/vehicle/gear?gear=Drive")
        self.assertIn("speed=0&accelerator=0&brake=100", paths[2])
        park = paths.index("/vehicle/gear?gear=Park")
        self.assertEqual(paths[park-1], "/vehicle/controls?speed=0&accelerator=0&brake=100")
        with self.assertRaises(ValueError):
            console.motion(36, parked=True)
        console.error = OSError("disconnected")
        with self.assertRaises(RuntimeError):
            console.motion(36)

    def test_cleanup_closes_lease_even_if_parking_fails(self):
        console = VirtualConsole("emulator-test", 18088)
        calls = []
        def request(path, method="GET"):
            calls.append(path)
            if path == "/vehicle/gear?gear=Park":
                raise OSError("failed gear write")
            return {}
        with patch.object(console, "request", side_effect=request), self.assertRaises(OSError):
            console.close()
        self.assertTrue(calls[-1].endswith("&closing=1"))
        self.assertTrue(console.done.is_set())


if __name__ == "__main__":
    unittest.main()
