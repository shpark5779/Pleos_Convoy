"""ADB-forwarded Pleos Virtual Console controls. No TMAP SDK or third-party packages."""
import json
from http.client import RemoteDisconnected
import math
import threading
import time
import uuid
from urllib.request import Request, urlopen

from demo_city_drive import adb


class VirtualConsole:
    def __init__(self, device, port):
        self.device = device
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.client = "convoy-replay-" + uuid.uuid4().hex
        self.done = threading.Event()
        self.worker = None
        self.error = None
        self.gear = None

    def request(self, path, method="GET"):
        # Controls set absolute values and the lease uses a stable client ID:
        # repeating after a dropped local HTTP connection is safe.
        for attempt in range(3):
            try:
                with urlopen(Request(self.base + path, method=method), timeout=3) as response:
                    return json.load(response)
            except (RemoteDisconnected, ConnectionResetError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(.2)

    def pulse(self):
        return self.request("/browser/session?client=" + self.client, "POST")

    def _heartbeat(self):
        while not self.done.wait(.7):
            try:
                self.pulse()
            except Exception as error:
                self.error = error
                return

    def start(self):
        adb(self.device, "forward", "tcp:" + str(self.port), "tcp:8088")
        self.pulse()
        self.worker = threading.Thread(target=self._heartbeat, daemon=True)
        self.worker.start()
        deadline = time.monotonic() + 6
        while True:
            state = self.snapshot()
            if state["dds_ready"] and state["gear"] is not None:
                return self
            if time.monotonic() > deadline:
                raise RuntimeError(self.device + ": Virtual Console DDS is not ready")
            time.sleep(.2)

    def motion(self, speed_kph, parked=False):
        if self.error:
            raise RuntimeError(self.device + ": Virtual Console heartbeat failed") from self.error
        if not math.isfinite(speed_kph) or not 0 <= speed_kph <= 240 or (parked and speed_kph != 0):
            raise ValueError("Invalid virtual vehicle speed/gear")
        gear = "Park" if parked else "Drive"
        # Clear motion before engaging P; keep D with the brake held at intermediate stops.
        if parked:
            self.request("/vehicle/controls?speed=0&accelerator=0&brake=100", "PUT")
        if gear != self.gear:
            self.request("/vehicle/gear?gear=" + gear, "PUT")
            self.gear = gear
        speed = round(speed_kph)  # Console controls accept integer km/h, as its own UI does.
        brake = 100 if speed == 0 else 0
        self.request(f"/vehicle/controls?speed={speed}&accelerator=0&brake={brake}", "PUT")

    def snapshot(self):
        state = self.request("/vehicle/state")
        return {"device": self.device, "gear": (state["gear"].get("actual") or {}).get("value"),
                "speed_kph": state["controls"]["speed_kph"],
                "brake_pct": state["controls"]["brake_pct"],
                "dds_ready": state["controls"]["dds_ready"]["all"],
                "emulator_active": state["controls"]["emulator_active"]}

    def close(self):
        try:
            self.pulse()
            self.request("/vehicle/controls?speed=0&accelerator=0&brake=0", "PUT")
            self.request("/vehicle/gear?gear=Park", "PUT")
            state = self.snapshot()
            if state["speed_kph"] != 0 or state["gear"] != "Park":
                raise RuntimeError(self.device + ": failed to restore Park/zero speed")
            return state
        finally:
            self.done.set()
            if self.worker:
                self.worker.join(timeout=4)
            self.request("/browser/session?client=" + self.client + "&closing=1", "POST")
