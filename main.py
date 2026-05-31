import json
import os
import queue
import sys
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import mido
import paho.mqtt.client as mqtt

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None

try:
    from winotify import Notification
except ImportError:
    Notification = None


# ============================================================
# STANDARD-EINSTELLUNGEN
# ============================================================

APP_NAME = "RodecasterHomeAssistantBridge"
STARTUP_BAT_NAME = f"{APP_NAME}.bat"

DEFAULT_CONFIG = {
    "mqtt_host": "homeassistant.local",
    "mqtt_port": 1883,
    "mqtt_username": "mqtt",
    "mqtt_password": "mqtt",
    "windows_autostart": False,
    "start_minimized": False,
    "start_bridge_on_app_start": True,
}

MIDI_PRESSED_VALUE = 127
MIDI_RELEASED_VALUE = 0

AVAILABILITY_TOPIC = "rodecaster/status"

PADS = {
    64: {"name": "Pad 1", "unique_id": "rodecaster_pad_1", "object_id": "rodecaster_pad_1", "event_topic": "rodecaster/pad/1", "state_topic": "rodecaster/pad/1/state", "discovery_topic": "homeassistant/binary_sensor/rodecaster_pro_2/pad_1/config"},
    65: {"name": "Pad 2", "unique_id": "rodecaster_pad_2", "object_id": "rodecaster_pad_2", "event_topic": "rodecaster/pad/2", "state_topic": "rodecaster/pad/2/state", "discovery_topic": "homeassistant/binary_sensor/rodecaster_pro_2/pad_2/config"},
    66: {"name": "Pad 3", "unique_id": "rodecaster_pad_3", "object_id": "rodecaster_pad_3", "event_topic": "rodecaster/pad/3", "state_topic": "rodecaster/pad/3/state", "discovery_topic": "homeassistant/binary_sensor/rodecaster_pro_2/pad_3/config"},
    67: {"name": "Pad 4", "unique_id": "rodecaster_pad_4", "object_id": "rodecaster_pad_4", "event_topic": "rodecaster/pad/4", "state_topic": "rodecaster/pad/4/state", "discovery_topic": "homeassistant/binary_sensor/rodecaster_pro_2/pad_4/config"},
    68: {"name": "Pad 5", "unique_id": "rodecaster_pad_5", "object_id": "rodecaster_pad_5", "event_topic": "rodecaster/pad/5", "state_topic": "rodecaster/pad/5/state", "discovery_topic": "homeassistant/binary_sensor/rodecaster_pro_2/pad_5/config"},
    69: {"name": "Pad 6", "unique_id": "rodecaster_pad_6", "object_id": "rodecaster_pad_6", "event_topic": "rodecaster/pad/6", "state_topic": "rodecaster/pad/6/state", "discovery_topic": "homeassistant/binary_sensor/rodecaster_pro_2/pad_6/config"},
    70: {"name": "Pad 7", "unique_id": "rodecaster_pad_7", "object_id": "rodecaster_pad_7", "event_topic": "rodecaster/pad/7", "state_topic": "rodecaster/pad/7/state", "discovery_topic": "homeassistant/binary_sensor/rodecaster_pro_2/pad_7/config"},
    71: {"name": "Pad 8", "unique_id": "rodecaster_pad_8", "object_id": "rodecaster_pad_8", "event_topic": "rodecaster/pad/8", "state_topic": "rodecaster/pad/8/state", "discovery_topic": "homeassistant/binary_sensor/rodecaster_pro_2/pad_8/config"},
}

OLD_DISCOVERY_TOPICS = [
    "homeassistant/binary_sensor/rodecaster_pad_64/config",
    "homeassistant/binary_sensor/rodecaster_pad_1/config",
    "homeassistant/binary_sensor/rodecaster_pad_2/config",
    "homeassistant/binary_sensor/rodecaster_pad_3/config",
    "homeassistant/binary_sensor/rodecaster_pad_4/config",
    "homeassistant/binary_sensor/rodecaster_pad_5/config",
    "homeassistant/binary_sensor/rodecaster_pad_6/config",
    "homeassistant/binary_sensor/rodecaster_pad_7/config",
    "homeassistant/binary_sensor/rodecaster_pad_8/config",
]


# ============================================================
# CONFIG
# ============================================================

def get_config_dir():
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / f".{APP_NAME}"


def get_config_file():
    return get_config_dir() / "config.json"


def load_config():
    config = dict(DEFAULT_CONFIG)
    config_file = get_config_file()

    try:
        if config_file.exists():
            saved = json.loads(config_file.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                config.update(saved)
    except Exception:
        pass

    return config


def save_config(config):
    get_config_dir().mkdir(parents=True, exist_ok=True)
    get_config_file().write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ============================================================
# WINDOWS AUTOSTART
# ============================================================

def get_startup_folder():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None

    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def get_autostart_file():
    startup_folder = get_startup_folder()
    if startup_folder is None:
        return None

    return startup_folder / STARTUP_BAT_NAME


def get_current_launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    python_exe = sys.executable

    if python_exe.lower().endswith("python.exe"):
        pythonw_exe = python_exe[:-10] + "pythonw.exe"
        if Path(pythonw_exe).exists():
            python_exe = pythonw_exe

    script_path = Path(__file__).resolve()
    return f'"{python_exe}" "{script_path}"'


def is_windows_autostart_enabled():
    autostart_file = get_autostart_file()
    return autostart_file is not None and autostart_file.exists()


def set_windows_autostart(enabled):
    autostart_file = get_autostart_file()

    if autostart_file is None:
        raise RuntimeError("APPDATA wurde nicht gefunden. Autostart-Ordner konnte nicht bestimmt werden.")

    autostart_file.parent.mkdir(parents=True, exist_ok=True)

    if enabled:
        command = get_current_launch_command()
        autostart_file.write_text(
            "@echo off\n"
            f"start \"\" {command}\n",
            encoding="utf-8",
        )
    else:
        if autostart_file.exists():
            autostart_file.unlink()


# ============================================================
# BRIDGE-LOGIK
# ============================================================

class RodecasterBridge:
    def __init__(self, app):
        self.app = app
        self.client = None
        self.running = False
        self.thread = None
        self.midi_input_name = None
        self.pad_states = {control: False for control in PADS}

    def log(self, text):
        self.app.log(text)

    def start(self):
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

        try:
            if self.client:
                for control, pad in PADS.items():
                    self.client.publish(pad["state_topic"], "released", retain=True)
                    self.pad_states[control] = False

                self.client.publish(AVAILABILITY_TOPIC, "offline", retain=True)
                self.client.loop_stop()
                self.client.disconnect()
                self.client = None
        except Exception:
            pass

        self.app.set_mqtt_status(False)
        self.app.set_midi_status(False)
        self.app.set_running(False)

        for control in PADS:
            self.app.set_pad_pressed(control, False)

        self.log("Bridge gestoppt.")

    def find_midi_input(self):
        inputs = mido.get_input_names()

        self.log("Gefundene MIDI-Eingänge:")
        if not inputs:
            self.log("Keine MIDI-Eingänge gefunden.")
            return None

        for index, name in enumerate(inputs):
            self.log(f"{index}: {name}")

        keywords = ["RØDE", "RODE", "Rode", "RØDECaster", "RODECaster", "RCPII", "RCP", "MIDI function"]

        for name in inputs:
            if any(keyword in name for keyword in keywords):
                self.log(f"Verwende MIDI-Eingang: {name}")
                return name

        self.log(f"Kein eindeutiger RØDECaster gefunden. Verwende: {inputs[0]}")
        return inputs[0]

    def connect_mqtt(self):
        config = self.app.config_data

        host = str(config.get("mqtt_host", "")).strip()
        port = int(config.get("mqtt_port", 1883))
        username = str(config.get("mqtt_username", ""))
        password = str(config.get("mqtt_password", ""))

        if not host:
            raise RuntimeError("MQTT Host/IP ist leer. Bitte in den Einstellungen eintragen.")

        self.log(f"Verbinde mit MQTT: {host}:{port}")

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if username or password:
            client.username_pw_set(username, password)

        client.connect(host, port, 60)
        client.loop_start()

        self.client = client
        self.app.set_mqtt_status(True)
        self.log("MQTT verbunden.")

    def clear_old_discovery(self):
        for topic in OLD_DISCOVERY_TOPICS:
            self.client.publish(topic, payload=None, retain=True)

    def publish_discovery(self):
        self.clear_old_discovery()

        for control, pad in PADS.items():
            config = {
                "name": pad["name"],
                "object_id": pad["object_id"],
                "unique_id": pad["unique_id"],
                "state_topic": pad["state_topic"],
                "payload_on": "pressed",
                "payload_off": "released",
                "device_class": "occupancy",
                "availability_topic": AVAILABILITY_TOPIC,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": {
                    "identifiers": ["rodecaster_pro_2"],
                    "name": "RØDECaster Pro II",
                    "manufacturer": "RØDE",
                    "model": "RØDECaster Pro II",
                },
            }

            self.client.publish(pad["discovery_topic"], json.dumps(config), retain=True)
            self.client.publish(pad["state_topic"], "released", retain=True)

        self.client.publish(AVAILABILITY_TOPIC, "online", retain=True)
        self.log("Home Assistant MQTT Discovery für 8 Pads gesendet.")

    def publish_pad_pressed(self, control):
        if self.pad_states.get(control) is True:
            return

        pad = PADS[control]
        self.pad_states[control] = True

        self.log(f"{pad['name']} gedrückt → MQTT pressed")
        self.app.set_pad_pressed(control, True)

        self.client.publish(pad["event_topic"], "pressed")
        self.client.publish(pad["state_topic"], "pressed")

    def publish_pad_released(self, control):
        if self.pad_states.get(control) is False:
            return

        pad = PADS[control]
        self.pad_states[control] = False

        self.log(f"{pad['name']} losgelassen → MQTT released")
        self.app.set_pad_pressed(control, False)

        self.client.publish(pad["event_topic"], "released")
        self.client.publish(pad["state_topic"], "released")

    def run(self):
        try:
            self.app.set_running(True)
            self.log("Bridge startet...")

            self.connect_mqtt()
            self.publish_discovery()

            self.midi_input_name = self.find_midi_input()
            if not self.midi_input_name:
                self.log("Abbruch: Kein MIDI-Gerät gefunden.")
                self.running = False
                self.app.set_running(False)
                return

            self.app.set_midi_status(True)
            self.log("Warte auf RØDECaster MIDI-Befehle...")

            with mido.open_input(self.midi_input_name) as inport:
                while self.running:
                    for msg in inport.iter_pending():
                        self.log(f"MIDI: {msg}")

                        if msg.type == "control_change" and msg.control in PADS:
                            if msg.value == MIDI_PRESSED_VALUE:
                                self.publish_pad_pressed(msg.control)

                            elif msg.value == MIDI_RELEASED_VALUE:
                                self.publish_pad_released(msg.control)

                    time.sleep(0.01)

        except Exception as error:
            self.log("FATALER FEHLER:")
            self.log(str(error))
            self.log(traceback.format_exc())
            self.app.show_error(str(error))

        finally:
            self.running = False
            self.app.set_running(False)
            self.app.set_mqtt_status(False)
            self.app.set_midi_status(False)

            try:
                if self.client:
                    for control, pad in PADS.items():
                        self.client.publish(pad["state_topic"], "released", retain=True)
                        self.pad_states[control] = False

                    self.client.publish(AVAILABILITY_TOPIC, "offline", retain=True)
                    self.client.loop_stop()
                    self.client.disconnect()
                    self.client = None
            except Exception:
                pass


# ============================================================
# UI
# ============================================================

class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.config_data = load_config()

        if is_windows_autostart_enabled():
            self.config_data["windows_autostart"] = True

        self.title("RØDECaster Home Assistant Bridge")
        self.geometry("1120x820")
        self.minsize(1040, 760)
        self.configure(bg="#0f1117")

        # Programm standardmäßig maximiert starten.
        self.after(50, self.start_maximized)

        self.log_queue = queue.Queue()
        self.pad_cards = {}
        self.pad_labels = {}
        self.tray_icon = None
        self.is_quitting = False
        self.background_notification_shown = False

        self.autostart_var = tk.BooleanVar(value=bool(self.config_data.get("windows_autostart", False)))
        self.minimized_var = tk.BooleanVar(value=bool(self.config_data.get("start_minimized", False)))
        self.autobridge_var = tk.BooleanVar(value=bool(self.config_data.get("start_bridge_on_app_start", True)))

        self.mqtt_host_var = tk.StringVar(value=str(self.config_data.get("mqtt_host", "")))
        self.mqtt_port_var = tk.StringVar(value=str(self.config_data.get("mqtt_port", 1883)))
        self.mqtt_username_var = tk.StringVar(value=str(self.config_data.get("mqtt_username", "")))
        self.mqtt_password_var = tk.StringVar(value=str(self.config_data.get("mqtt_password", "")))

        self.bridge = RodecasterBridge(self)

        self.create_styles()
        self.create_icon()
        self.create_layout()
        self.setup_tray_icon()

        self.after(100, self.process_log_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Unmap>", self.on_minimize)

        save_config(self.config_data)

        if bool(self.config_data.get("start_minimized", False)):
            self.after(350, self.hide_to_tray)

        if bool(self.config_data.get("start_bridge_on_app_start", True)):
            self.after(700, self.start_bridge)

    def create_icon(self):
        icon = tk.PhotoImage(width=32, height=32)

        for x in range(32):
            for y in range(32):
                icon.put("#0f1117", (x, y))

        for x in range(6, 26):
            for y in range(6, 26):
                icon.put("#7c3aed", (x, y))

        for x in range(10, 22):
            for y in range(10, 22):
                icon.put("#111827", (x, y))

        for x in range(13, 19):
            for y in range(13, 19):
                icon.put("#22c55e", (x, y))

        self.iconphoto(True, icon)
        self._icon_ref = icon

    def start_maximized(self):
        try:
            self.state("zoomed")
        except Exception:
            try:
                self.attributes("-zoomed", True)
            except Exception:
                pass

    def setup_tray_icon(self):
        if pystray is None:
            self.log("Tray-Icon nicht verfügbar. Bitte pystray und pillow installieren.")
            return

        image = Image.new("RGBA", (64, 64), (15, 17, 23, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((10, 10, 54, 54), radius=12, fill=(124, 58, 237, 255))
        draw.rounded_rectangle((18, 18, 46, 46), radius=7, fill=(17, 24, 39, 255))
        draw.ellipse((25, 25, 39, 39), fill=(34, 197, 94, 255))

        menu = pystray.Menu(
            pystray.MenuItem("Öffnen", lambda icon, item: self.after(0, self.show_from_tray), default=True),
            pystray.MenuItem("Bridge starten", lambda icon, item: self.after(0, self.start_bridge)),
            pystray.MenuItem("Bridge stoppen", lambda icon, item: self.after(0, self.stop_bridge)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden", lambda icon, item: self.after(0, self.quit_app)),
        )

        self.tray_icon = pystray.Icon(APP_NAME, image, "RØDECaster Bridge", menu)

        try:
            self.tray_icon.run_detached()
            self.log("Tray-Icon gestartet.")
        except Exception as error:
            self.log(f"Tray-Icon konnte nicht gestartet werden: {error}")
            self.tray_icon = None

    def show_background_notification(self):
        """
        Zeigt eine echte Windows-Toast-Benachrichtigung unten rechts.
        Kein Popup/Dialogfenster wird geöffnet.
        """
        if self.background_notification_shown:
            return

        self.background_notification_shown = True

        # Bevorzugt: native Windows-Toast-Benachrichtigung unten rechts.
        if Notification is not None:
            try:
                toast = Notification(
                    app_id="RØDECaster Bridge",
                    title="RØDECaster Bridge läuft im Hintergrund",
                    msg="Die App wurde in den Infobereich minimiert. Über das Icon unten rechts kannst du sie wieder öffnen.",
                    duration="short",
                )
                toast.show()
                self.log("Windows-Benachrichtigung unten rechts gesendet.")
                return
            except Exception as error:
                self.log(f"Windows-Toast konnte nicht gesendet werden: {error}")

        # Fallback: pystray-Benachrichtigung, falls winotify nicht verfügbar ist.
        if self.tray_icon is not None:
            try:
                self.tray_icon.notify(
                    "RØDECaster Bridge läuft im Hintergrund",
                    "Die App wurde in den Infobereich minimiert. Über das Icon unten rechts kannst du sie wieder öffnen.",
                )
                self.log("Tray-Benachrichtigung gesendet.")
                return
            except Exception as error:
                self.log(f"Tray-Benachrichtigung konnte nicht gesendet werden: {error}")

        # Kein Popup anzeigen. Nur in den Log schreiben.
        self.log("Hinweis: Windows-Benachrichtigung nicht verfügbar. Bitte winotify installieren.")

    def hide_to_tray(self):
        if self.is_quitting:
            return

        if pystray is None or self.tray_icon is None:
            self.iconify()
            return

        self.withdraw()
        self.log("App in den Infobereich minimiert.")
        self.show_background_notification()

    def show_from_tray(self):
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()
        self.log("App aus dem Infobereich geöffnet.")

    def on_minimize(self, event=None):
        if self.is_quitting:
            return

        if event is not None and event.widget is not self:
            return

        try:
            if self.state() == "iconic":
                self.after(50, self.hide_to_tray)
        except Exception:
            pass

    def quit_app(self):
        self.is_quitting = True

        try:
            self.save_settings_from_ui()
        except Exception:
            pass

        try:
            self.bridge.stop()
        except Exception:
            pass

        try:
            if self.tray_icon is not None:
                self.tray_icon.stop()
                self.tray_icon = None
        except Exception:
            pass

        self.destroy()

    def open_github(self, event=None):
        webbrowser.open("https://github.com/deBurki04")

    def create_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.TFrame", background="#0f1117")
        style.configure("Panel.TFrame", background="#171a23", relief="flat")

        style.configure("Title.TLabel", background="#0f1117", foreground="#f8fafc", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", background="#0f1117", foreground="#94a3b8", font=("Segoe UI", 10))
        style.configure("PanelTitle.TLabel", background="#171a23", foreground="#f8fafc", font=("Segoe UI", 13, "bold"))
        style.configure("Text.TLabel", background="#171a23", foreground="#cbd5e1", font=("Segoe UI", 10))
        style.configure("Small.TLabel", background="#171a23", foreground="#94a3b8", font=("Segoe UI", 9))
        style.configure("Footer.TLabel", background="#0f1117", foreground="#64748b", font=("Segoe UI", 9))
        style.configure("Good.TLabel", background="#171a23", foreground="#22c55e", font=("Segoe UI", 10, "bold"))
        style.configure("Bad.TLabel", background="#171a23", foreground="#ef4444", font=("Segoe UI", 10, "bold"))

        style.configure("Accent.TButton", background="#7c3aed", foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=(18, 10), borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#8b5cf6"), ("disabled", "#374151")], foreground=[("disabled", "#9ca3af")])

        style.configure("Secondary.TButton", background="#334155", foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=(12, 8), borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#475569"), ("disabled", "#374151")], foreground=[("disabled", "#9ca3af")])

        style.configure("Danger.TButton", background="#dc2626", foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=(18, 10), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#ef4444"), ("disabled", "#374151")], foreground=[("disabled", "#9ca3af")])

        style.configure("Dark.TCheckbutton", background="#171a23", foreground="#cbd5e1", font=("Segoe UI", 10))
        style.map("Dark.TCheckbutton", background=[("active", "#171a23")], foreground=[("active", "#f8fafc")])

        style.configure("Dark.TEntry", fieldbackground="#0b0f19", background="#0b0f19", foreground="#f8fafc", insertcolor="#ffffff", borderwidth=1, relief="flat", padding=8)

    def create_layout(self):
        root = ttk.Frame(self, style="Dark.TFrame", padding=22)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="Dark.TFrame")
        header.pack(fill="x", pady=(0, 18))

        title_box = ttk.Frame(header, style="Dark.TFrame")
        title_box.pack(side="left", fill="x", expand=True)

        ttk.Label(title_box, text="RØDECaster Bridge", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Steuert Home Assistant über MIDI und MQTT", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))

        button_box = ttk.Frame(header, style="Dark.TFrame")
        button_box.pack(side="right")

        self.start_button = ttk.Button(button_box, text="Bridge starten", style="Accent.TButton", command=self.start_bridge)
        self.start_button.pack(side="left", padx=(0, 10))

        self.stop_button = ttk.Button(button_box, text="Stoppen", style="Danger.TButton", command=self.stop_bridge, state="disabled")
        self.stop_button.pack(side="left")

        main = ttk.Frame(root, style="Dark.TFrame")
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main, style="Dark.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, 14))

        right = ttk.Frame(main, style="Dark.TFrame")
        right.pack(side="right", fill="both", expand=False)

        self.create_status_panel(left)
        self.create_pads_panel(left)
        self.create_settings_panel(right)
        self.create_log_panel(right)

        footer = ttk.Frame(root, style="Dark.TFrame")
        footer.pack(fill="x", pady=(10, 0))

        copyright_link = ttk.Label(
            footer,
            text="Copyright 2026 Joel Bürki",
            style="Footer.TLabel",
            cursor="hand2",
        )
        copyright_link.pack(side="right")
        copyright_link.bind("<Button-1>", self.open_github)

    def make_panel(self, parent):
        return tk.Frame(parent, bg="#171a23", highlightbackground="#2a2f3d", highlightthickness=1, bd=0)

    def create_status_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(fill="x", pady=(0, 14))

        inner = ttk.Frame(panel, style="Panel.TFrame", padding=18)
        inner.pack(fill="both", expand=True)

        ttk.Label(inner, text="Status", style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 12))

        grid = ttk.Frame(inner, style="Panel.TFrame")
        grid.pack(fill="x")

        self.mqtt_status = ttk.Label(grid, text="MQTT: getrennt", style="Bad.TLabel")
        self.mqtt_status.grid(row=0, column=0, sticky="w", padx=(0, 40))

        self.midi_status = ttk.Label(grid, text="MIDI: nicht verbunden", style="Bad.TLabel")
        self.midi_status.grid(row=0, column=1, sticky="w", padx=(0, 40))

        self.bridge_status = ttk.Label(grid, text="Bridge: gestoppt", style="Bad.TLabel")
        self.bridge_status.grid(row=0, column=2, sticky="w")

        self.details_label = ttk.Label(inner, text="", style="Text.TLabel")
        self.details_label.pack(anchor="w", pady=(14, 0))
        self.update_details_label()

    def update_details_label(self):
        host = self.config_data.get("mqtt_host", "")
        port = self.config_data.get("mqtt_port", 1883)
        username = self.config_data.get("mqtt_username", "")
        self.details_label.config(text=f"MQTT: {host}:{port}   |   Benutzer: {username or '-'}   |   Pads: 8")

    def create_pads_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(fill="both", expand=True)

        inner = ttk.Frame(panel, style="Panel.TFrame", padding=18)
        inner.pack(fill="both", expand=True)

        ttk.Label(inner, text="RØDECaster Pads", style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 14))

        pad_grid = ttk.Frame(inner, style="Panel.TFrame")
        pad_grid.pack(fill="both", expand=True)

        for index, (control, pad) in enumerate(PADS.items()):
            row = index // 4
            col = index % 4

            card = tk.Frame(pad_grid, bg="#111827", highlightbackground="#334155", highlightthickness=1, bd=0)
            card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)

            pad_grid.columnconfigure(col, weight=1)
            pad_grid.rowconfigure(row, weight=1)

            tk.Label(card, text=pad["name"], bg="#111827", fg="#f8fafc", font=("Segoe UI", 14, "bold")).pack(pady=(18, 4))
            tk.Label(card, text=f"Control {control}", bg="#111827", fg="#94a3b8", font=("Segoe UI", 10)).pack()

            state = tk.Label(card, text="bereit", bg="#111827", fg="#64748b", font=("Segoe UI", 10, "bold"))
            state.pack(pady=(10, 18))

            self.pad_cards[control] = card
            self.pad_labels[control] = state

    def create_settings_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(fill="x", pady=(0, 14))

        inner = ttk.Frame(panel, style="Panel.TFrame", padding=18)
        inner.pack(fill="x", expand=False)

        ttk.Label(inner, text="MQTT-Einstellungen", style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 12))

        form = ttk.Frame(inner, style="Panel.TFrame")
        form.pack(fill="x")

        self.add_labeled_entry(form, "Host / IP", self.mqtt_host_var, 0)
        self.add_labeled_entry(form, "Port", self.mqtt_port_var, 1)
        self.add_labeled_entry(form, "Benutzer", self.mqtt_username_var, 2)
        self.add_labeled_entry(form, "Passwort", self.mqtt_password_var, 3, show="*")

        ttk.Button(inner, text="Einstellungen speichern", style="Secondary.TButton", command=self.save_settings_from_ui).pack(anchor="w", pady=(12, 0))

        ttk.Label(inner, text="Änderungen werden beim nächsten Bridge-Start verwendet.", style="Small.TLabel", wraplength=350).pack(anchor="w", pady=(8, 14))

        ttk.Label(inner, text="App-Start", style="PanelTitle.TLabel").pack(anchor="w", pady=(4, 12))

        self.autostart_check = ttk.Checkbutton(inner, text="Mit Windows starten", variable=self.autostart_var, command=self.toggle_autostart, style="Dark.TCheckbutton")
        self.autostart_check.pack(anchor="w", pady=(0, 6))

        self.minimized_check = ttk.Checkbutton(inner, text="Minimiert starten", variable=self.minimized_var, command=self.save_settings_from_ui, style="Dark.TCheckbutton")
        self.minimized_check.pack(anchor="w", pady=(0, 6))

        self.autobridge_check = ttk.Checkbutton(inner, text="Bridge automatisch starten", variable=self.autobridge_var, command=self.save_settings_from_ui, style="Dark.TCheckbutton")
        self.autobridge_check.pack(anchor="w", pady=(0, 6))

        self.autostart_status = ttk.Label(inner, text=self.get_autostart_status_text(), style="Small.TLabel", wraplength=350)
        self.autostart_status.pack(anchor="w", pady=(8, 0))

        self.config_status = ttk.Label(inner, text="Config gespeichert in AppData", style="Small.TLabel", wraplength=350)
        self.config_status.pack(anchor="w", pady=(4, 0))

    def add_labeled_entry(self, parent, label_text, variable, row, show=None):
        label = ttk.Label(parent, text=label_text, style="Text.TLabel")
        label.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))

        entry = ttk.Entry(parent, textvariable=variable, style="Dark.TEntry", show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=4)

        parent.columnconfigure(1, weight=1)

    def create_log_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(fill="both", expand=True)

        inner = ttk.Frame(panel, style="Panel.TFrame", padding=18)
        inner.pack(fill="both", expand=True)

        ttk.Label(inner, text="Live-Log", style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 12))

        self.log_text = tk.Text(
            inner,
            width=44,
            height=12,
            bg="#0b0f19",
            fg="#d1d5db",
            insertbackground="#ffffff",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 9),
            padx=12,
            pady=12,
        )
        self.log_text.pack(fill="both", expand=True)

    def get_autostart_status_text(self):
        if is_windows_autostart_enabled():
            return "Autostart: aktiv"
        return "Autostart: deaktiviert"

    def save_settings_from_ui(self):
        try:
            port = int(str(self.mqtt_port_var.get()).strip())
            if port <= 0 or port > 65535:
                raise ValueError("Port muss zwischen 1 und 65535 liegen.")
        except Exception:
            messagebox.showerror("Einstellungsfehler", "Bitte einen gültigen MQTT-Port eingeben, z. B. 1883.")
            return False

        host = str(self.mqtt_host_var.get()).strip()
        if not host:
            messagebox.showerror("Einstellungsfehler", "Bitte Host oder IP-Adresse eintragen.")
            return False

        self.config_data["mqtt_host"] = host
        self.config_data["mqtt_port"] = port
        self.config_data["mqtt_username"] = str(self.mqtt_username_var.get())
        self.config_data["mqtt_password"] = str(self.mqtt_password_var.get())
        self.config_data["windows_autostart"] = bool(self.autostart_var.get())
        self.config_data["start_minimized"] = bool(self.minimized_var.get())
        self.config_data["start_bridge_on_app_start"] = bool(self.autobridge_var.get())

        save_config(self.config_data)
        self.update_details_label()

        self.log("Einstellungen gespeichert.")
        return True

    def toggle_autostart(self):
        enabled = bool(self.autostart_var.get())

        if not self.save_settings_from_ui():
            self.autostart_var.set(is_windows_autostart_enabled())
            return

        try:
            set_windows_autostart(enabled)
            self.config_data["windows_autostart"] = enabled
            save_config(self.config_data)
            self.autostart_status.config(text=self.get_autostart_status_text())

            if enabled:
                self.log("Windows-Autostart aktiviert.")
            else:
                self.log("Windows-Autostart deaktiviert.")

        except Exception as error:
            self.autostart_var.set(is_windows_autostart_enabled())
            self.config_data["windows_autostart"] = bool(self.autostart_var.get())
            save_config(self.config_data)
            self.autostart_status.config(text=self.get_autostart_status_text())
            messagebox.showerror("Autostart-Fehler", str(error))
            self.log(f"Autostart-Fehler: {error}")

    def start_bridge(self):
        if self.bridge.running:
            return

        if not self.save_settings_from_ui():
            return

        self.bridge.start()

    def stop_bridge(self):
        self.bridge.stop()

    def set_running(self, running):
        def update():
            if running:
                self.bridge_status.config(text="Bridge: läuft", style="Good.TLabel")
                self.start_button.config(state="disabled")
                self.stop_button.config(state="normal")
            else:
                self.bridge_status.config(text="Bridge: gestoppt", style="Bad.TLabel")
                self.start_button.config(state="normal")
                self.stop_button.config(state="disabled")

        self.after(0, update)

    def set_mqtt_status(self, connected):
        def update():
            if connected:
                self.mqtt_status.config(text="MQTT: verbunden", style="Good.TLabel")
            else:
                self.mqtt_status.config(text="MQTT: getrennt", style="Bad.TLabel")

        self.after(0, update)

    def set_midi_status(self, connected):
        def update():
            if connected:
                self.midi_status.config(text="MIDI: verbunden", style="Good.TLabel")
            else:
                self.midi_status.config(text="MIDI: nicht verbunden", style="Bad.TLabel")

        self.after(0, update)

    def set_pad_pressed(self, control, pressed):
        def update():
            card = self.pad_cards.get(control)
            label = self.pad_labels.get(control)

            if not card or not label:
                return

            if pressed:
                card.config(bg="#12351f", highlightbackground="#22c55e")
                label.config(text="gedrückt", bg="#12351f", fg="#22c55e")
            else:
                card.config(bg="#111827", highlightbackground="#334155")
                label.config(text="bereit", bg="#111827", fg="#64748b")

        self.after(0, update)

    def log(self, text):
        self.log_queue.put(text)

    def process_log_queue(self):
        try:
            while True:
                text = self.log_queue.get_nowait()
                timestamp = time.strftime("%H:%M:%S")
                self.log_text.insert("end", f"[{timestamp}] {text}\n")
                self.log_text.see("end")
        except queue.Empty:
            pass

        self.after(100, self.process_log_queue)

    def show_error(self, message):
        self.after(0, lambda: messagebox.showerror("Fehler", message))

    def on_close(self):
        self.quit_app()


if __name__ == "__main__":
    app = App()
    app.mainloop()
