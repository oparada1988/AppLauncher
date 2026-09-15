# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.InputIdentifier import Input

# Import python & gtk modules
import os
from loguru import logger
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, GObject, Pango, Gio


class AppItem(GObject.Object):
    __gtype_name__ = "AppLauncherItem"

    title = GObject.Property(type=str, default="")
    app_name = GObject.Property(type=str, default="")
    desktop_id = GObject.Property(type=str, default="")
    desktop_path = GObject.Property(type=str, default="")
    icon_name = GObject.Property(type=str, default="")
    icon_path = GObject.Property(type=str, default="")

    def __init__(self, title: str = "", app_name: str = "", desktop_id: str = "",
                 desktop_path: str = "", icon_name: str = "", icon_path: str = ""):
        super().__init__()
        self.title = title
        self.app_name = app_name
        self.desktop_id = desktop_id
        self.desktop_path = desktop_path
        self.icon_name = icon_name
        self.icon_path = icon_path


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

    def _setup_combo_item(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_valign(Gtk.Align.CENTER)

        image = Gtk.Image()
        image.set_pixel_size(24)
        image.set_valign(Gtk.Align.CENTER)

        label = Gtk.Label(xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_valign(Gtk.Align.CENTER)

        box.append(image)
        box.append(label)
        list_item.set_child(box)

    def _bind_combo_item(self, factory, list_item):
        box = list_item.get_child()
        if not box:
            return
        image = box.get_first_child()
        label = image.get_next_sibling()
        item = list_item.get_item()
        if not item:
            return

        label.set_text(item.title)

        if not item.desktop_id:
            # Placeholder item "-- Select an Application --"
            image.set_visible(False)
        elif item.icon_path and os.path.exists(item.icon_path):
            try:
                image.set_from_file(item.icon_path)
                image.set_visible(True)
            except Exception:
                self._fallback_icon(image, item)
        elif item.icon_name:
            self._fallback_icon(image, item)
        else:
            image.set_visible(False)

    def _fallback_icon(self, image: Gtk.Image, item: AppItem):
        if item.icon_name:
            try:
                image.set_from_icon_name(item.icon_name)
                image.set_visible(True)
                return
            except Exception:
                pass

        default_icon = os.path.join(self.plugin_base.PATH, "assets", "default_app.png")
        if os.path.exists(default_icon):
            try:
                image.set_from_file(default_icon)
                image.set_visible(True)
                return
            except Exception:
                pass

        image.set_from_icon_name("application-x-executable-symbolic")
        image.set_visible(True)

    def get_config_rows(self) -> list:
        rows = []
        settings = self.get_settings()
        current_desktop_id = settings.get("desktop_id", "")

        # Fetch apps from plugin base
        apps_dict = self.plugin_base.get_apps()
        self._sorted_apps = sorted(apps_dict.values(), key=lambda a: a.name.lower())

        # 1. Application Dropdown Selector with Application Icons
        self._app_store = Gio.ListStore.new(AppItem)
        self._apps_by_title = {}
        selected_idx = 0

        # Placeholder first item
        self._app_store.append(AppItem(title="-- Select an Application --", desktop_id=""))

        for idx, app in enumerate(self._sorted_apps, start=1):
            title = app.name
            if title in self._apps_by_title:
                title = f"{app.name} ({app.desktop_id})"
            self._apps_by_title[title] = app

            icon_path = app.resolved_icon_path
            if not icon_path and hasattr(self.plugin_base, "app_scanner"):
                icon_path = self.plugin_base.app_scanner.resolve_icon(app.icon_name)
                app.resolved_icon_path = icon_path

            item = AppItem(
                title=title,
                app_name=app.name,
                desktop_id=app.desktop_id,
                desktop_path=app.desktop_path,
                icon_name=app.icon_name,
                icon_path=icon_path or ""
            )
            self._app_store.append(item)
            if app.desktop_id == current_desktop_id:
                selected_idx = idx

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_combo_item)
        factory.connect("bind", self._bind_combo_item)

        self._app_combo = Adw.ComboRow(
            title="Application",
            subtitle="Choose an installed application to launch",
            model=self._app_store
        )
        self._app_combo.set_factory(factory)
        self._app_combo.set_list_factory(factory)

        # Enable text filtering and search expression for Adw.ComboRow
        expression = Gtk.PropertyExpression.new(AppItem, None, "title")
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

        settings = self.get_settings()

        if not selected_item.desktop_id:
            settings["desktop_id"] = ""
            settings["desktop_path"] = ""
            settings["app_name"] = ""
            settings["icon_name"] = ""
            settings["icon_path"] = ""
            self.set_settings(settings)
            self.update_key_visuals()
            return

        settings["desktop_id"] = selected_item.desktop_id
        settings["desktop_path"] = selected_item.desktop_path
        settings["app_name"] = selected_item.app_name or selected_item.title
        settings["icon_name"] = selected_item.icon_name

        icon_path = selected_item.icon_path
        if not icon_path and hasattr(self.plugin_base, "app_scanner"):
            icon_path = self.plugin_base.app_scanner.resolve_icon(selected_item.icon_name)
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
            new_store = Gio.ListStore.new(AppItem)
            new_store.append(AppItem(title="-- Select an Application --", desktop_id=""))

            self._apps_by_title = {}
            current_desktop_id = self.get_settings().get("desktop_id", "")
            selected_idx = 0

            for idx, app in enumerate(self._sorted_apps, start=1):
                title = app.name
                if title in self._apps_by_title:
                    title = f"{app.name} ({app.desktop_id})"
                self._apps_by_title[title] = app

                icon_path = app.resolved_icon_path
                if not icon_path and hasattr(self.plugin_base, "app_scanner"):
                    icon_path = self.plugin_base.app_scanner.resolve_icon(app.icon_name)
                    app.resolved_icon_path = icon_path

                item = AppItem(
                    title=title,
                    app_name=app.name,
                    desktop_id=app.desktop_id,
                    desktop_path=app.desktop_path,
                    icon_name=app.icon_name,
                    icon_path=icon_path or ""
                )
                new_store.append(item)
                if app.desktop_id == current_desktop_id:
                    selected_idx = idx

            self._app_store = new_store
            self._app_combo.set_model(self._app_store)
            expression = Gtk.PropertyExpression.new(AppItem, None, "title")
            self._app_combo.set_expression(expression)
            self._app_combo.set_selected(selected_idx)
        finally:
            self._updating_config = False
