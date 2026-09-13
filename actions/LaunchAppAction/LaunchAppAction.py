# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.InputIdentifier import Input

# Import python & gtk modules
import os
from loguru import logger
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib


class LaunchAppAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._sorted_apps = []
        self._apps_by_title = {}
        self._updating_config = False

    def on_ready(self) -> None:
        # Request visual control of key image and label
        try:
            state = self.get_state()
            if state is not None:
                apm = state.action_permission_manager
                own_index = self.get_own_action_index()
                if own_index is not None and own_index != -1:
                    if apm.get_image_control_index() is None or not self.get_is_multi_action():
                        if apm.get_image_control_index() != own_index:
                            apm.set_image_control_index(own_index, reload_pages=False, reload_self=False)
                    if apm.get_label_control_index(2) is None or not self.get_is_multi_action():
                        if apm.get_label_control_index(2) != own_index:
                            apm.set_label_control_index(2, own_index, reload_pages=False, reload_self=False)
        except Exception as e:
            logger.debug(f"Permission control setup: {e}")

        # Update visuals on key
        self.update_key_visuals()

    def update_key_visuals(self) -> None:
        settings = self.get_settings()
        desktop_id = settings.get("desktop_id", "")
        app_name = settings.get("app_name", "")
        icon_path = settings.get("icon_path", "")
        custom_label = settings.get("custom_label", "")
        show_label = settings.get("show_label", True)

        # 1. Resolve and set icon
        if icon_path and os.path.exists(icon_path):
            self.set_media(media_path=icon_path)
        elif desktop_id and hasattr(self.plugin_base, "app_scanner"):
            resolved = self.plugin_base.app_scanner.resolve_icon(settings.get("icon_name", ""))
            settings["icon_path"] = resolved
            self.set_settings(settings)
            self.set_media(media_path=resolved)
        else:
            default_icon = os.path.join(self.plugin_base.PATH, "assets", "action_launch.png")
            self.set_media(media_path=default_icon)

        # 2. Set label
        if show_label:
            display_label = custom_label if custom_label.strip() else app_name
            self.set_label(display_label, position="bottom")
        else:
            self.set_label("", position="bottom")

    def event_callback(self, event, data=None):
        # Trigger on key down or dial press
        if event == Input.Key.Events.DOWN:
            self.launch_current_app()
        elif hasattr(Input, "Dial") and hasattr(Input.Dial, "Events") and event in [Input.Dial.Events.DOWN, Input.Dial.Events.SHORT_TOUCH_PRESS]:
            self.launch_current_app()

    def launch_current_app(self) -> None:
        settings = self.get_settings()
        desktop_id = settings.get("desktop_id", "")
        desktop_path = settings.get("desktop_path", "")
        if not desktop_id:
            logger.warning("AppLauncher: No application selected for this key")
            return

        logger.info(f"AppLauncher: Key pressed, launching application: {desktop_id}")
        if hasattr(self.plugin_base, "app_scanner"):
            self.plugin_base.app_scanner.launch(desktop_id, desktop_path=desktop_path)

    def get_config_rows(self) -> list:
        rows = []
        settings = self.get_settings()
        current_desktop_id = settings.get("desktop_id", "")

        # Fetch apps from plugin base
        apps_dict = self.plugin_base.get_apps()
        self._sorted_apps = sorted(apps_dict.values(), key=lambda a: a.name.lower())

        # 1. Application Dropdown Selector
        self._app_model = Gtk.StringList()
        self._apps_by_title = {}
        selected_idx = 0

        # Placeholder first item
        self._app_model.append("-- Select an Application --")

        for idx, app in enumerate(self._sorted_apps, start=1):
            title = app.name
            if title in self._apps_by_title:
                title = f"{app.name} ({app.desktop_id})"
            self._apps_by_title[title] = app
            self._app_model.append(title)
            if app.desktop_id == current_desktop_id:
                selected_idx = idx

        self._app_combo = Adw.ComboRow(
            title="Application",
            subtitle="Choose an installed application to launch",
            model=self._app_model
        )

        # Enable text filtering and search expression for Adw.ComboRow
        expression = Gtk.PropertyExpression.new(Gtk.StringObject, None, "string")
        self._app_combo.set_expression(expression)
        if hasattr(self._app_combo, "set_enable_search"):
            self._app_combo.set_enable_search(True)

        self._app_combo.set_selected(selected_idx)
        self._app_combo.connect("notify::selected", self._on_app_changed)
        rows.append(self._app_combo)

        # 2. Show Label Switch
        self._show_label_switch = Adw.SwitchRow(
            title="Show Label",
            subtitle="Show application title text on key"
        )
        self._show_label_switch.set_active(settings.get("show_label", True))
        self._show_label_switch.connect("notify::active", self._on_show_label_changed)
        rows.append(self._show_label_switch)

        # 3. Custom Label Entry
        self._custom_label_entry = Adw.EntryRow(
            title="Custom Label"
        )
        self._custom_label_entry.set_text(settings.get("custom_label", ""))
        self._custom_label_entry.connect("notify::text", self._on_custom_label_changed)
        rows.append(self._custom_label_entry)

        # 4. Rescan Applications Button
        rescan_row = Adw.ActionRow(
            title="Rescan System Applications",
            subtitle="Refresh the application list for newly installed apps"
        )
        rescan_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        rescan_btn.set_valign(Gtk.Align.CENTER)
        rescan_btn.connect("clicked", self._on_rescan_clicked)
        rescan_row.add_suffix(rescan_btn)
        rows.append(rescan_row)

        return rows

    def _on_app_changed(self, combo, _param) -> None:
        if self._updating_config:
            return

        selected_item = combo.get_selected_item()
        if not selected_item:
            return

        selected_title = selected_item.get_string()
        settings = self.get_settings()

        if not selected_title or selected_title == "-- Select an Application --":
            settings["desktop_id"] = ""
            settings["app_name"] = ""
            settings["icon_name"] = ""
            settings["icon_path"] = ""
            self.set_settings(settings)
            self.update_key_visuals()
            return

        selected_app = self._apps_by_title.get(selected_title)
        if not selected_app:
            idx = combo.get_selected()
            if 0 < idx <= len(self._sorted_apps):
                selected_app = self._sorted_apps[idx - 1]

        if not selected_app:
            return

        settings["desktop_id"] = selected_app.desktop_id
        settings["desktop_path"] = selected_app.desktop_path
        settings["app_name"] = selected_app.name
        settings["icon_name"] = selected_app.icon_name

        # Resolve icon
        icon_path = self.plugin_base.app_scanner.resolve_icon(selected_app.icon_name)
        settings["icon_path"] = icon_path

        self.set_settings(settings)
        self.update_key_visuals()

    def _on_show_label_changed(self, switch, _param) -> None:
        settings = self.get_settings()
        settings["show_label"] = switch.get_active()
        self.set_settings(settings)
        self.update_key_visuals()

    def _on_custom_label_changed(self, entry, _param) -> None:
        settings = self.get_settings()
        settings["custom_label"] = entry.get_text()
        self.set_settings(settings)
        self.update_key_visuals()

    def _on_rescan_clicked(self, _btn) -> None:
        self._updating_config = True
        try:
            apps_dict = self.plugin_base.scan_apps()
            self._sorted_apps = sorted(apps_dict.values(), key=lambda a: a.name.lower())

            # Rebuild model
            new_model = Gtk.StringList()
            new_model.append("-- Select an Application --")

            self._apps_by_title = {}
            current_desktop_id = self.get_settings().get("desktop_id", "")
            selected_idx = 0

            for idx, app in enumerate(self._sorted_apps, start=1):
                title = app.name
                if title in self._apps_by_title:
                    title = f"{app.name} ({app.desktop_id})"
                self._apps_by_title[title] = app
                new_model.append(title)
                if app.desktop_id == current_desktop_id:
                    selected_idx = idx

            self._app_combo.set_model(new_model)
            expression = Gtk.PropertyExpression.new(Gtk.StringObject, None, "string")
            self._app_combo.set_expression(expression)
            self._app_combo.set_selected(selected_idx)
        finally:
            self._updating_config = False
