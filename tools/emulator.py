import argparse
import logging
import os
import queue
import sys
import tempfile
import threading
import time
import types
from unittest.mock import MagicMock


"""
Runs the SeedSigner app on a normal computer, in a window.

Why this exists:
    The app is written against a Raspberry Pi: it imports `RPi.GPIO` at module scope,
    talks to an SPI display, and reads a camera. None of that exists on a laptop, so
    `python src/main.py` fails on the first import.

    Everything the emulator replaces is at the very edge of the app: the GPIO pin reads,
    the display driver, and the camera. The Controller, every View, every Screen and all
    of the gui components are the real ones -- including `HardwareButtons`' debounce and
    repeat logic, which is driven by faked pin states rather than bypassed. What you see
    in the window is what the device draws.

    That makes it useful for trying a flow end to end, checking a layout at a real
    resolution, and reviewing a translation in context, without flashing a card.

Usage:
    python tools/emulator.py                    # open the window
    python tools/emulator.py --scale 3          # bigger window
    python tools/emulator.py --locale de        # start in a given language
    python tools/emulator.py --headless --frames 40 --out-dir /tmp/frames

Controls:
    Arrow keys      joystick up / down / left / right
    Enter or Space  joystick press (select)
    1 / 2 / 3       the three side buttons
    Esc             quit

    There is no dedicated "back": on the device you go back by pressing the joystick
    left to reach the `<` in the top bar, then pressing it. The emulator keeps that
    exactly as it is, because learning it is part of learning the device.

What is NOT emulated:
    The camera. Anything that wants to scan raises `CameraConnectionError`, which the
    app already handles -- you land on its "Cannot access camera" screen instead of
    crashing. So scanning a QR code, the photo entropy flow and address verification by
    scan cannot be exercised here.

Requirements:
    pip install embit Pillow qrcode
    Tkinter, which ships with python.org and Windows python builds. On Debian/Ubuntu:
    `sudo apt install python3-tk`. Without it, `--headless` still works.
"""


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)


# Keysym (as Tk reports it) -> the attribute on `HardwareButtonsConstants` it stands for.
# Resolved to pin numbers after the seedsigner import, since those depend on the faked
# `RPI_INFO` below.
KEY_MAP = {
    "Up": "KEY_UP",
    "Down": "KEY_DOWN",
    "Left": "KEY_LEFT",
    "Right": "KEY_RIGHT",
    "Return": "KEY_PRESS",
    "KP_Enter": "KEY_PRESS",
    "space": "KEY_PRESS",
    "1": "KEY1",
    "2": "KEY2",
    "3": "KEY3",
}

# Names accepted by --script, for headless runs.
SCRIPT_KEY_MAP = dict(
    up="KEY_UP",
    down="KEY_DOWN",
    left="KEY_LEFT",
    right="KEY_RIGHT",
    press="KEY_PRESS",
    select="KEY_PRESS",
    key1="KEY1",
    key2="KEY2",
    key3="KEY3",
)


def install_hardware_fakes() -> set:
    """
        Puts stand-ins for the Raspberry Pi-only modules into `sys.modules`.

        Must run before anything from `seedsigner` is imported: `hardware/buttons.py`
        reads `GPIO.RPI_INFO` at class-definition time to decide which pin numbering to
        use, so a mock that arrives later is already too late.

        Returns the set of currently-pressed pins. Adding a pin to it is exactly what a
        button press looks like to the app.
    """
    pressed_pins = set()

    gpio = types.ModuleType("RPi.GPIO")
    gpio.BOARD = 10
    gpio.BCM = 11
    gpio.IN = 1
    gpio.OUT = 0
    gpio.PUD_UP = 22
    gpio.PUD_DOWN = 21
    gpio.LOW = 0
    gpio.HIGH = 1

    # P1_REVISION 3 is the 40-pin header, i.e. every Pi the project supports.
    gpio.RPI_INFO = {"P1_REVISION": 3}

    gpio.setmode = lambda *args, **kwargs: None
    gpio.setwarnings = lambda *args, **kwargs: None
    gpio.setup = lambda *args, **kwargs: None
    gpio.cleanup = lambda *args, **kwargs: None
    gpio.output = lambda *args, **kwargs: None

    # Pins are wired with pull-ups, so LOW means pressed.
    gpio.input = lambda pin: gpio.LOW if pin in pressed_pins else gpio.HIGH

    rpi = types.ModuleType("RPi")
    rpi.GPIO = gpio
    sys.modules["RPi"] = rpi
    sys.modules["RPi.GPIO"] = gpio

    # Display drivers: unused, because the Renderer is replaced wholesale below, but
    # they are imported eagerly in places.
    sys.modules["seedsigner.hardware.displays.st7789_mpy"] = MagicMock()
    sys.modules["seedsigner.hardware.displays.ili9341"] = MagicMock()

    # Camera stack. `pivideostream` imports picamera, which does not install off-Pi.
    sys.modules["picamera"] = MagicMock()
    sys.modules["picamera2"] = MagicMock()
    sys.modules["seedsigner.hardware.pivideostream"] = MagicMock()

    # numpy is in the Raspi requirements only, and is imported by the background import
    # thread. Leave a real installation alone; stub it when it is missing.
    try:
        import numpy  # noqa: F401
    except ImportError:
        sys.modules["numpy"] = MagicMock()

    return pressed_pins


def build_renderer(frame_callback, width: int, height: int):
    """
        Patches a canvas-only Renderer over the real one.

        Same approach the screenshot generator uses: the app keeps calling
        `Renderer.get_instance()` and drawing into `renderer.canvas`; only the final
        handoff to the SPI display is replaced, here by `frame_callback`.
    """
    from PIL import Image, ImageDraw
    from seedsigner.gui.renderer import Renderer

    class EmulatorRenderer(Renderer):
        @classmethod
        def configure_instance(cls):
            renderer = cls.__new__(cls)
            cls._instance = renderer
            renderer.canvas_width = width
            renderer.canvas_height = height
            renderer.canvas = Image.new("RGB", (width, height))
            renderer.draw = ImageDraw.Draw(renderer.canvas)
            renderer.frame_count = 0

        def emit(self):
            self.frame_count += 1
            frame_callback(self.canvas.copy())

        def show_image(self, image=None, alpha_overlay=None, show_direct=False, is_background_thread: bool = False):
            if show_direct:
                self.canvas.paste(image)
                self.emit()
                return

            if alpha_overlay:
                if image is None:
                    image = self.canvas
                image = Image.alpha_composite(image, alpha_overlay)

            if image:
                self.canvas.paste(image)

            self.emit()

        def show_image_pan(self, image, start_x, start_y, end_x, end_y, rate, alpha_overlay=None):
            # Same walk as the real Renderer, minus the display driver writes.
            cur_x, cur_y = start_x, start_y
            rate_x = rate if end_x - start_x >= 0 else -rate
            rate_y = rate if end_y - start_y >= 0 else -rate

            while (cur_x != end_x or cur_y != end_y) and (rate_x != 0 or rate_y != 0):
                cur_x += rate_x
                if (rate_x > 0 and cur_x > end_x) or (rate_x < 0 and cur_x < end_x):
                    cur_x -= rate_x
                    rate_x = 0

                cur_y += rate_y
                if (rate_y > 0 and cur_y > end_y) or (rate_y < 0 and cur_y < end_y):
                    cur_y -= rate_y
                    rate_y = 0

                crop = image.crop((cur_x, cur_y, cur_x + self.canvas_width, cur_y + self.canvas_height))
                if alpha_overlay:
                    crop = Image.alpha_composite(crop, alpha_overlay)

                self.canvas.paste(crop)
                self.emit()

    EmulatorRenderer.configure_instance()
    instance = EmulatorRenderer.get_instance()

    # The Controller calls `Renderer.configure_instance()` during its own setup; ours is
    # already built, so make that a no-op and hand out our instance instead.
    Renderer.configure_instance = classmethod(lambda cls: None)
    Renderer.get_instance = classmethod(lambda cls: instance)

    return instance


def disable_camera():
    """
        Makes every camera call fail the way a disconnected camera does.

        `UnhandledExceptionView` recognizes `CameraConnectionError` by name and routes to
        `CameraConnectionErrorView`, so this surfaces the app's own "Cannot access
        camera" screen rather than a traceback.
    """
    from seedsigner.hardware.camera import Camera, CameraConnectionError

    def refuse(*args, **kwargs):
        raise CameraConnectionError()

    Camera.start_video_stream_mode = refuse
    Camera.start_single_frame_mode = refuse
    Camera.read_video_stream = refuse
    Camera.capture_frame = refuse
    Camera.stop_video_stream_mode = lambda self, *args, **kwargs: None
    Camera.stop_single_frame_mode = lambda self, *args, **kwargs: None


def resolve_canvas_size() -> tuple:
    """ Canvas dimensions for the configured display, matching `Renderer` """
    from seedsigner.hardware.displays.display_driver import DISPLAY_TYPE__ST7789
    from seedsigner.models.settings import Settings
    from seedsigner.models.settings_definition import SettingsConstants

    display_config = Settings.get_instance().get_value(
        SettingsConstants.SETTING__DISPLAY_CONFIGURATION, default_if_none=True
    )
    display_type = display_config.split("_")[0]
    width, height = (int(value) for value in display_config.split("_")[1].split("x"))

    if display_type == DISPLAY_TYPE__ST7789:
        return width, height

    # The other panels are natively portrait; the driver rotates them.
    return height, width


def resolve_pins() -> dict:
    """ keysym -> pin number, for both the window and --script """
    from seedsigner.hardware.buttons import HardwareButtonsConstants

    by_keysym = {keysym: getattr(HardwareButtonsConstants, attr) for keysym, attr in KEY_MAP.items()}
    by_name = {name: getattr(HardwareButtonsConstants, attr) for name, attr in SCRIPT_KEY_MAP.items()}
    return by_keysym, by_name


def start_controller() -> threading.Thread:
    """ The app's main loop, on its own thread so the window can own the main thread. """
    from seedsigner.controller import Controller

    def run():
        try:
            Controller.get_instance().start()
        except Exception:
            logger.exception("The controller exited")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def run_window(frames: queue.Queue, pressed_pins: set, pins_by_keysym: dict, scale: int, press_ms: int):
    import tkinter
    from PIL import Image, ImageTk

    root = tkinter.Tk()
    root.title("SeedSigner emulator")
    root.resizable(False, False)
    root.configure(bg="black")

    screen = tkinter.Label(root, bd=0, bg="black", highlightthickness=0)
    screen.pack()

    tkinter.Label(
        root,
        text="arrows: joystick    enter/space: select    1 2 3: side buttons    esc: quit",
        font=("TkDefaultFont", 8),
        fg="#999999",
        bg="black",
        pady=4,
    ).pack(fill="x")

    def on_key(event):
        if event.keysym == "Escape":
            root.destroy()
            return

        pin = pins_by_keysym.get(event.keysym)
        if pin is None:
            return

        # A keystroke is modelled as a press that releases itself shortly after. Holding
        # a key down therefore produces repeated discrete clicks rather than one long
        # press, which sidesteps the auto-repeat press/release pairs the window system
        # synthesizes and keeps `HardwareButtons`' repeat thresholds meaningful.
        pressed_pins.add(pin)
        root.after(press_ms, lambda: pressed_pins.discard(pin))

    root.bind("<KeyPress>", on_key)

    def pump():
        frame = None
        while True:
            try:
                frame = frames.get_nowait()
            except queue.Empty:
                break

        if frame is not None:
            if scale != 1:
                frame = frame.resize((frame.width * scale, frame.height * scale), Image.NEAREST)
            photo = ImageTk.PhotoImage(frame)
            screen.configure(image=photo)
            # Tk does not keep a reference of its own; without this the image is
            # garbage collected and the label goes blank.
            screen.image = photo

        root.after(20, pump)

    pump()
    root.mainloop()


def run_headless(frames: queue.Queue, pressed_pins: set, pins_by_name: dict, args):
    """
        Runs without a window: saves frames as PNGs, optionally replaying a key script.

        This is how the emulator is verified in an environment with no display, and it
        doubles as a way to capture a flow as images.
    """
    out_dir = args.out_dir or os.path.join(tempfile.gettempdir(), "seedsigner-emulator-frames")
    os.makedirs(out_dir, exist_ok=True)

    script_done = threading.Event()

    if args.script:
        def replay():
            time.sleep(args.script_start / 1000.0)
            for name in args.script.split(","):
                pin = pins_by_name.get(name.strip().lower())
                if pin is None:
                    print(f"  !! unknown key in --script: {name!r}", file=sys.stderr)
                    continue
                pressed_pins.add(pin)
                time.sleep(args.press_ms / 1000.0)
                pressed_pins.discard(pin)
                time.sleep(args.script_delay / 1000.0)
            script_done.set()

        threading.Thread(target=replay, daemon=True).start()

    saved = 0
    deadline = time.time() + args.timeout
    last_frame_at = time.time()

    while saved < args.frames and time.time() < deadline:
        try:
            frame = frames.get(timeout=0.5)
        except queue.Empty:
            # A finished script that has stopped producing frames means the flow has
            # settled; no point waiting out the full timeout for frames that are not
            # coming.
            if args.script and script_done.is_set() and time.time() - last_frame_at > args.idle_exit:
                break
            continue

        last_frame_at = time.time()
        path = os.path.join(out_dir, f"frame_{saved:04d}.png")
        frame.save(path)
        saved += 1

    print(f"Saved {saved} frame(s) to {out_dir}")
    return 0 if saved else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the SeedSigner app on this computer, with the display in a window.",
    )
    parser.add_argument("--scale", type=int, default=2, help="window magnification (default: %(default)s)")
    parser.add_argument("--locale", type=str, default=None, help="start in this language, e.g. de, es, tlh")
    parser.add_argument("--loglevel", type=str, default="WARNING", choices=list(logging._nameToLevel.keys()))
    parser.add_argument(
        "--settings-file",
        type=str,
        default=os.path.join(tempfile.gettempdir(), "seedsigner-emulator", "settings.json"),
        help="where persistent settings are read from and written to (default: %(default)s)",
    )
    parser.add_argument("--press-ms", type=int, default=120, help="how long a keystroke holds the button down (default: %(default)s)")
    parser.add_argument("--headless", action="store_true", help="no window; save frames as PNGs")
    parser.add_argument("--frames", type=int, default=20, help="headless: how many frames to save (default: %(default)s)")
    parser.add_argument("--out-dir", type=str, default=None, help="headless: where to save frames")
    parser.add_argument("--timeout", type=float, default=60.0, help="headless: give up after this many seconds (default: %(default)s)")
    parser.add_argument("--script", type=str, default=None, help="headless: comma-separated keys to replay, e.g. down,down,select")
    parser.add_argument("--script-start", type=int, default=4000, help="headless: wait this long before the script starts, in ms (default: %(default)s)")
    parser.add_argument("--script-delay", type=int, default=600, help="headless: pause between scripted keys, in ms (default: %(default)s)")
    parser.add_argument("--idle-exit", type=float, default=3.0, help="headless: stop this many seconds after a --script run stops producing frames (default: %(default)s)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.getLevelName(args.loglevel),
        format="%(asctime)s %(levelname)8s [%(name)s]: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("PIL").setLevel(logging.WARNING)

    # Works from a plain clone, with or without `pip install -e .`
    src_path = os.path.join(REPO_ROOT, "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    pressed_pins = install_hardware_fakes()

    from seedsigner.models.settings import Settings
    from seedsigner.models.settings_definition import SettingsConstants

    os.makedirs(os.path.dirname(os.path.abspath(args.settings_file)), exist_ok=True)
    Settings.SETTINGS_FILENAME = args.settings_file

    if args.locale:
        available = [code for code, name in SettingsConstants.get_detected_languages()]
        if args.locale not in available:
            print(f"Unknown locale {args.locale!r}. Available: {', '.join(available)}", file=sys.stderr)
            print("Languages other than English need their catalogs compiled; see the README.", file=sys.stderr)
            return 1
        Settings.get_instance().set_value(SettingsConstants.SETTING__LOCALE, args.locale)

    # In the window, only the newest frame matters, so the queue is bounded and older
    # frames are dropped rather than slowing the app down. A headless capture wants
    # every frame, so it takes an unbounded queue.
    frames = queue.Queue(maxsize=0 if args.headless else 8)

    def on_frame(image):
        try:
            frames.put_nowait(image)
        except queue.Full:
            try:
                frames.get_nowait()
                frames.put_nowait(image)
            except (queue.Empty, queue.Full):
                pass

    canvas_width, canvas_height = resolve_canvas_size()
    build_renderer(on_frame, canvas_width, canvas_height)
    disable_camera()

    pins_by_keysym, pins_by_name = resolve_pins()

    start_controller()

    if args.headless:
        return run_headless(frames, pressed_pins, pins_by_name, args)

    try:
        import tkinter  # noqa: F401
        from PIL import ImageTk  # noqa: F401
    except ImportError as e:
        print(f"Cannot open a window: {e}", file=sys.stderr)
        print("Install Tkinter (Debian/Ubuntu: sudo apt install python3-tk), or use --headless.", file=sys.stderr)
        return 1

    run_window(frames, pressed_pins, pins_by_keysym, max(1, args.scale), args.press_ms)

    # The controller thread is a daemon blocked on button input; nothing to join.
    return 0


if __name__ == "__main__":
    sys.exit(main())
