# Import StreamController modules
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.DeckManagement.InputIdentifier import Input

# Import python & gtk modules
import os
import threading
from loguru import logger
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

# Import local modules
from .app_scanner import AppScanner
from .actions.LaunchAppAction.LaunchAppAction import LaunchAppAction


class PluginTemplate(PluginBase):
    def __init__(self):
        super().__init__()

        # Initialize Application Scanner
        assets_dir = os.path.join(self.PATH, "assets")
        self.app_scanner = AppScanner(plugin_assets_dir=assets_dir)
        self._apps_cache = {}
        self._initial_scan_done = False

        # Start initial application scan in background thread to avoid blocking startup
        self._scan_thread = threading.Thread(target=self._initial_scan, daemon=True)
        self._scan_thread.start()

        # Register Launch Application Action
        self.launch_app_action_holder = ActionHolder(
            plugin_base=self,
            action_base=LaunchAppAction,
            action_id="com_oparada_AppLauncher::LaunchAppAction",
            action_name="Launch App",
            icon=Gtk.Image(file=os.path.join(self.PATH, "assets", "action_launch.png")),
            action_support={
                Input.Key: ActionInputSupport.SUPPORTED,
                Input.Dial: ActionInputSupport.UNSUPPORTED,
                Input.Touchscreen: ActionInputSupport.SUPPORTED
            }
        )
        self.add_action_holder(self.launch_app_action_holder)

    def _initial_scan(self):
        try:
            self._apps_cache = self.app_scanner.scan_applications()
            self._initial_scan_done = True
            logger.info(f"AppLauncher: Loaded {len(self._apps_cache)} installed applications")
        except Exception as e:
            logger.error(f"AppLauncher initial scan failed: {e}")

    def get_apps(self) -> dict:
        """Returns the dictionary of scanned applications, scanning if needed."""
        if not self._apps_cache:
            self._apps_cache = self.app_scanner.scan_applications()
        return self._apps_cache

    def scan_apps(self) -> dict:
        """Forces a fresh scan of installed applications."""
        self._apps_cache = self.app_scanner.scan_applications()
        return self._apps_cache
