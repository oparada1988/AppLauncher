import os
import sys
import json
import shlex
import glob
import shutil
import subprocess
import multiprocessing
from typing import Dict, List, Optional
from loguru import logger

# Import GTK for native icon lookup
try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk
    HAS_GTK = True
except Exception:
    HAS_GTK = False


def is_in_flatpak() -> bool:
    return os.path.isfile('/.flatpak-info')


class AppInfo:
    def __init__(self, desktop_id: str, name: str, icon_name: Optional[str] = None,
                 categories: str = "", comment: str = "", desktop_path: str = ""):
        self.desktop_id = desktop_id
        self.name = name
        self.icon_name = icon_name or ""
        self.categories = categories
        self.comment = comment
        self.desktop_path = desktop_path
        self.resolved_icon_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "desktop_id": self.desktop_id,
            "name": self.name,
            "icon_name": self.icon_name,
            "categories": self.categories,
            "comment": self.comment,
            "desktop_path": self.desktop_path,
            "resolved_icon_path": self.resolved_icon_path
        }


class AppScanner:
    def __init__(self, plugin_assets_dir: str):
        self.plugin_assets_dir = plugin_assets_dir
        self.default_icon_path = os.path.join(plugin_assets_dir, "default_app.png")
        self.cache_dir = os.path.expanduser("~/.cache/streamcontroller_apps/icons")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.apps: Dict[str, AppInfo] = {}
        self._icon_theme = None
        if HAS_GTK:
            try:
                display = Gdk.Display.get_default()
                if display:
                    self._icon_theme = Gtk.IconTheme.get_for_display(display)
            except Exception as e:
                logger.warning(f"Could not initialize Gtk.IconTheme: {e}")

    def scan_applications(self) -> Dict[str, AppInfo]:
        """
        Scans all installed applications from standard XDG paths.
        Uses flatpak-spawn --host when in flatpak sandbox.
        """
        if is_in_flatpak():
            self.apps = self._scan_via_flatpak_spawn()
        else:
            self.apps = self._scan_local_host()
            
        return self.apps

    def _scan_local_host(self) -> Dict[str, AppInfo]:
        """Direct filesystem scan when running natively on the host."""
        dirs = [
            os.path.expanduser("~/.local/share/applications"),
            os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
            "/var/lib/flatpak/exports/share/applications",
            "/usr/local/share/applications",
            "/usr/share/applications",
            "/var/lib/snapd/desktop/applications"
        ]
        return self._parse_desktop_directories(dirs)

    def _scan_via_flatpak_spawn(self) -> Dict[str, AppInfo]:
        """Fast scan executed on the host via flatpak-spawn."""
        scanner_code = """
import os, glob, json

dirs = [
    os.path.expanduser('~/.local/share/applications'),
    os.path.expanduser('~/.local/share/flatpak/exports/share/applications'),
    '/var/lib/flatpak/exports/share/applications',
    '/usr/local/share/applications',
    '/usr/share/applications',
    '/var/lib/snapd/desktop/applications'
]

apps = {}
for d in dirs:
    if not os.path.exists(d):
        continue
    for f in glob.glob(os.path.join(d, '*.desktop')):
        desktop_id = os.path.basename(f)
        if desktop_id in apps:
            continue
        name = None
        icon = None
        nodisplay = False
        app_type = 'Application'
        categories = ''
        comment = ''
        try:
            with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
                in_entry = False
                for line in fp:
                    line = line.strip()
                    if line == '[Desktop Entry]':
                        in_entry = True
                        continue
                    elif line.startswith('[') and in_entry:
                        break
                    if in_entry:
                        if line.startswith('Name=') and name is None:
                            name = line[5:]
                        elif line.startswith('Icon=') and icon is None:
                            icon = line[5:]
                        elif line.startswith('NoDisplay='):
                            nodisplay = line[10:].lower() == 'true'
                        elif line.startswith('Type='):
                            app_type = line[5:]
                        elif line.startswith('Categories='):
                            categories = line[11:]
                        elif line.startswith('Comment=') and not comment:
                            comment = line[8:]
        except Exception:
            continue
        if app_type == 'Application' and not nodisplay and name:
            apps[desktop_id] = {
                'desktop_id': desktop_id,
                'name': name,
                'icon': icon,
                'categories': categories,
                'comment': comment,
                'desktop_path': f
            }

print(json.dumps(apps))
"""
        try:
            res = subprocess.run(
                ["flatpak-spawn", "--host", "python3", "-c", scanner_code],
                capture_output=True,
                text=True,
                timeout=10
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                apps = {}
                for did, item in data.items():
                    apps[did] = AppInfo(
                        desktop_id=item["desktop_id"],
                        name=item["name"],
                        icon_name=item.get("icon"),
                        categories=item.get("categories", ""),
                        comment=item.get("comment", ""),
                        desktop_path=item.get("desktop_path", "")
                    )
                return apps
        except Exception as e:
            logger.error(f"Error scanning apps via flatpak-spawn: {e}")

        # Fallback to whatever is accessible inside sandbox
        return self._scan_local_host()

    def _parse_desktop_directories(self, dirs: List[str]) -> Dict[str, AppInfo]:
        apps = {}
        for d in dirs:
            if not os.path.exists(d):
                continue
            for f in glob.glob(os.path.join(d, "*.desktop")):
                desktop_id = os.path.basename(f)
                if desktop_id in apps:
                    continue
                name = None
                icon = None
                nodisplay = False
                app_type = "Application"
                categories = ""
                comment = ""
                try:
                    with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                        in_entry = False
                        for line in fp:
                            line = line.strip()
                            if line == "[Desktop Entry]":
                                in_entry = True
                                continue
                            elif line.startswith("[") and in_entry:
                                break
                            if in_entry:
                                if line.startswith("Name=") and name is None:
                                    name = line[5:]
                                elif line.startswith("Icon=") and icon is None:
                                    icon = line[5:]
                                elif line.startswith("NoDisplay="):
                                    nodisplay = line[10:].lower() == "true"
                                elif line.startswith("Type="):
                                    app_type = line[5:]
                                elif line.startswith("Categories="):
                                    categories = line[11:]
                                elif line.startswith("Comment=") and not comment:
                                    comment = line[8:]
                except Exception:
                    continue
                if app_type == "Application" and not nodisplay and name:
                    apps[desktop_id] = AppInfo(
                        desktop_id=desktop_id,
                        name=name,
                        icon_name=icon,
                        categories=categories,
                        comment=comment,
                        desktop_path=f
                    )
        return apps

    def resolve_icon(self, icon_name_or_path: str) -> str:
        """
        Resolves an icon name or path to a file readable by StreamController.
        Returns the absolute path to a PNG/SVG or default fallback.
        """
        if not icon_name_or_path:
            return self.default_icon_path

        # 1. Direct path check
        if os.path.isabs(icon_name_or_path) and os.path.exists(icon_name_or_path):
            return icon_name_or_path

        # 2. Check Gtk.IconTheme (works inside flatpak mapped to /run/host/share/icons)
        if self._icon_theme is not None:
            try:
                paintable = self._icon_theme.lookup_icon(
                    icon_name_or_path, None, 128, 1, Gtk.TextDirection.NONE, 0
                )
                if paintable and paintable.get_file():
                    p = paintable.get_file().get_path()
                    if p and os.path.exists(p):
                        return p
            except Exception as e:
                logger.debug(f"Gtk.IconTheme lookup error for {icon_name_or_path}: {e}")

        # 3. Check already cached icons
        for ext in [".svg", ".png", ".jpg"]:
            cached = os.path.join(self.cache_dir, f"{icon_name_or_path}{ext}")
            if os.path.exists(cached):
                return cached

        # 4. If in flatpak, copy from host icon directories to cache if located
        if is_in_flatpak():
            cached_path = self._cache_icon_from_host(icon_name_or_path)
            if cached_path and os.path.exists(cached_path):
                return cached_path

        return self.default_icon_path

    def _cache_icon_from_host(self, icon_name: str) -> Optional[str]:
        """Searches host icon directories via flatpak-spawn and caches file to home."""
        copy_script = f"""
import os, glob, shutil

icon_name = {json.dumps(icon_name)}
cache_dir = os.path.expanduser('~/.cache/streamcontroller_apps/icons')
os.makedirs(cache_dir, exist_ok=True)

search_dirs = [
    os.path.expanduser('~/.local/share/icons'),
    os.path.expanduser('~/.local/share/flatpak/exports/share/icons'),
    '/var/lib/flatpak/exports/share/icons',
    '/usr/share/pixmaps',
    '/usr/share/icons'
]

found = None
# Check exact or ext
for d in search_dirs:
    for ext in ['', '.png', '.svg']:
        cand = os.path.join(d, icon_name + ext)
        if os.path.exists(cand):
            found = cand
            break
    if found:
        break

if not found:
    for d in search_dirs:
        for sz in ['256x256', '128x128', '512x512', 'scalable', '64x64']:
            matches = glob.glob(os.path.join(d, '**', sz, '**', icon_name + '.*'), recursive=True)
            if matches:
                found = matches[0]
                break
        if found:
            break

if found:
    _, ext = os.path.splitext(found)
    dst = os.path.join(cache_dir, icon_name + ext)
    shutil.copyfile(found, dst)
    print(dst)
"""
        try:
            res = subprocess.run(
                ["flatpak-spawn", "--host", "python3", "-c", copy_script],
                capture_output=True,
                text=True,
                timeout=5
            )
            if res.returncode == 0 and res.stdout.strip():
                cached = res.stdout.strip()
                if os.path.exists(cached):
                    return cached
        except Exception as e:
            logger.debug(f"Host icon caching error: {e}")
        return None

    def launch(self, desktop_id: str) -> bool:
        """
        Launches an application cleanly on the host via gtk-launch or gio launch.
        Never blocks the caller.
        """
        if not desktop_id:
            logger.warning("Attempted to launch empty desktop_id")
            return False

        # Clean desktop_id for gtk-launch (e.g. 'code.desktop' -> 'code')
        clean_id = desktop_id[:-8] if desktop_id.endswith(".desktop") else desktop_id

        # Command to run on host
        cmd = f"gtk-launch {shlex.quote(clean_id)}"
        if is_in_flatpak():
            cmd = f"flatpak-spawn --host {cmd}"

        logger.info(f"Launching application: {cmd}")

        def _spawn():
            try:
                subprocess.Popen(
                    cmd,
                    shell=True,
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=os.path.expanduser("~")
                )
            except Exception as e:
                logger.error(f"Failed to spawn {cmd}: {e}")

        p = multiprocessing.Process(target=_spawn)
        p.daemon = True
        p.start()
        return True
