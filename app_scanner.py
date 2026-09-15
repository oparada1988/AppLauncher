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
    return os.path.isfile('/.flatpak-info') or os.environ.get('FLATPAK_ID') is not None


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
import os, glob, json, shutil

cache_dir = os.path.expanduser('~/.cache/streamcontroller_apps/icons')
os.makedirs(cache_dir, exist_ok=True)

dirs = [
    os.path.expanduser('~/.local/share/applications'),
    os.path.expanduser('~/.local/share/flatpak/exports/share/applications'),
    '/var/lib/flatpak/exports/share/applications',
    '/usr/local/share/applications',
    '/usr/share/applications',
    '/var/lib/snapd/desktop/applications'
]

def find_host_icon(icon_name):
    if not icon_name:
        return None
    if os.path.isabs(icon_name) and os.path.isfile(icon_name):
        return icon_name

    clean_name = os.path.basename(icon_name) if os.path.isabs(icon_name) else icon_name

    # 1. Flatpak app direct export & files dirs
    for base in ['/var/lib/flatpak/app', os.path.expanduser('~/.local/share/flatpak/app')]:
        d = os.path.join(base, clean_name, 'current/active')
        if not os.path.isdir(d):
            continue
        for sub in ['export/share/icons', 'files/share/icons']:
            sub_d = os.path.join(d, sub)
            if not os.path.isdir(sub_d):
                continue
            for sz in ['scalable', '512x512', '256x256', '128x128', '64x64', '48x48']:
                for ext in ['.svg', '.png']:
                    m = glob.glob(os.path.join(sub_d, '**', sz, 'apps', f'{clean_name}{ext}'), recursive=True)
                    if m:
                        return m[0]
            m = glob.glob(os.path.join(sub_d, '**', f'{clean_name}.*'), recursive=True)
            non_sym = [x for x in m if 'symbolic' not in x]
            if non_sym:
                return non_sym[0]
            if m:
                return m[0]

    # 2. Pixmaps
    for p_dir in ['/usr/share/pixmaps', '/usr/local/share/pixmaps', os.path.expanduser('~/.local/share/pixmaps')]:
        for ext in ['', '.png', '.svg', '.xpm']:
            cand = os.path.join(p_dir, clean_name + ext)
            if os.path.isfile(cand):
                return cand

    # 3. Hicolor icon dirs
    for i_dir in [
        '/usr/share/icons/hicolor',
        os.path.expanduser('~/.local/share/icons/hicolor'),
        '/var/lib/flatpak/exports/share/icons/hicolor',
        os.path.expanduser('~/.local/share/flatpak/exports/share/icons/hicolor')
    ]:
        if not os.path.isdir(i_dir):
            continue
        for sz in ['scalable', '512x512', '256x256', '128x128', '64x64', '48x48']:
            for ext in ['.svg', '.png']:
                cand = os.path.join(i_dir, sz, 'apps', f'{clean_name}{ext}')
                if os.path.isfile(cand):
                    return cand

    # 4. System theme icons (Papirus, Yaru, Adwaita)
    for theme_dir in ['/usr/share/icons/Papirus', '/usr/share/icons/Yaru', '/usr/share/icons/Adwaita']:
        if not os.path.isdir(theme_dir):
            continue
        for sz in ['128x128/apps', 'scalable/apps', '64x64/apps', '48x48/apps']:
            for ext in ['.svg', '.png']:
                cand = os.path.join(theme_dir, sz, f'{clean_name}{ext}')
                if os.path.isfile(cand):
                    return cand

    return None

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
            resolved_icon = None
            if icon:
                clean_icon_name = os.path.basename(icon) if os.path.isabs(icon) else icon
                # Check if already cached in ~/.cache
                for ext in ['.svg', '.png', '.jpg', '.xpm', '']:
                    cand_cached = os.path.join(cache_dir, f'{clean_icon_name}{ext}')
                    if os.path.isfile(cand_cached):
                        resolved_icon = cand_cached
                        break
                if not resolved_icon:
                    src = find_host_icon(icon)
                    if src and os.path.isfile(src):
                        _, ext = os.path.splitext(src)
                        if not ext:
                            ext = '.png'
                        dst = os.path.join(cache_dir, f'{clean_icon_name}{ext}')
                        try:
                            if not os.path.exists(dst):
                                shutil.copyfile(src, dst)
                            resolved_icon = dst
                        except Exception:
                            resolved_icon = src

            apps[desktop_id] = {
                'desktop_id': desktop_id,
                'name': name,
                'icon': icon,
                'categories': categories,
                'comment': comment,
                'desktop_path': f,
                'resolved_icon_path': resolved_icon
            }

print(json.dumps(apps))
"""
        home_dir = os.path.expanduser("~")
        try:
            res = subprocess.run(
                [
                    "flatpak-spawn",
                    "--host",
                    f"--directory={home_dir}",
                    "python3",
                    "-c",
                    scanner_code
                ],
                capture_output=True,
                text=True,
                cwd=home_dir,
                timeout=15
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                apps = {}
                for did, item in data.items():
                    app = AppInfo(
                        desktop_id=item["desktop_id"],
                        name=item["name"],
                        icon_name=item.get("icon"),
                        categories=item.get("categories", ""),
                        comment=item.get("comment", ""),
                        desktop_path=item.get("desktop_path", "")
                    )
                    app.resolved_icon_path = item.get("resolved_icon_path")
                    apps[did] = app
                logger.info(f"AppLauncher: Scanned {len(apps)} applications via flatpak-spawn on host")
                return apps
            else:
                logger.error(f"AppLauncher: flatpak-spawn error (rc={res.returncode}): {res.stderr}")
        except Exception as e:
            logger.error(f"Error scanning apps via flatpak-spawn: {e}")

        # Fallback to whatever is accessible inside sandbox
        logger.warning("AppLauncher: Falling back to sandbox-local desktop scan")
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

        clean_name = os.path.basename(icon_name_or_path) if os.path.isabs(icon_name_or_path) else icon_name_or_path

        # 2. Check already cached icons in ~/.cache/streamcontroller_apps/icons
        for ext in [".svg", ".png", ".jpg", ".xpm", ""]:
            cached = os.path.join(self.cache_dir, f"{clean_name}{ext}")
            if os.path.exists(cached) and os.path.isfile(cached):
                return cached

        # 3. Check Gtk.IconTheme (only if theme actually contains the icon)
        if self._icon_theme is not None and self._icon_theme.has_icon(clean_name):
            try:
                paintable = self._icon_theme.lookup_icon(
                    clean_name, None, 128, 1, Gtk.TextDirection.NONE, 0
                )
                if paintable and paintable.get_file():
                    p = paintable.get_file().get_path()
                    if p and os.path.exists(p) and "image-missing" not in p:
                        return p
            except Exception as e:
                logger.debug(f"Gtk.IconTheme lookup error for {clean_name}: {e}")

        # 4. If in flatpak, search host icon directories and cache if located
        if is_in_flatpak():
            cached_path = self._cache_icon_from_host(clean_name)
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

clean_name = os.path.basename(icon_name) if os.path.isabs(icon_name) else icon_name

# 1. Flatpak app direct export & files dirs
found = None
for base in ['/var/lib/flatpak/app', os.path.expanduser('~/.local/share/flatpak/app')]:
    d = os.path.join(base, clean_name, 'current/active')
    if not os.path.isdir(d):
        continue
    for sub in ['export/share/icons', 'files/share/icons']:
        sub_d = os.path.join(d, sub)
        if not os.path.isdir(sub_d):
            continue
        for sz in ['scalable', '512x512', '256x256', '128x128', '64x64', '48x48']:
            for ext in ['.svg', '.png']:
                m = glob.glob(os.path.join(sub_d, '**', sz, 'apps', f'{{clean_name}}{{ext}}'), recursive=True)
                if m:
                    found = m[0]
                    break
            if found:
                break
        if not found:
            m = glob.glob(os.path.join(sub_d, '**', f'{{clean_name}}.*'), recursive=True)
            non_sym = [x for x in m if 'symbolic' not in x]
            if non_sym:
                found = non_sym[0]
            elif m:
                found = m[0]
        if found:
            break
    if found:
        break

# 2. Pixmaps
if not found:
    for p_dir in ['/usr/share/pixmaps', '/usr/local/share/pixmaps', os.path.expanduser('~/.local/share/pixmaps')]:
        for ext in ['', '.png', '.svg', '.xpm']:
            cand = os.path.join(p_dir, clean_name + ext)
            if os.path.isfile(cand):
                found = cand
                break
        if found:
            break

# 3. Hicolor icon dirs
if not found:
    for i_dir in [
        '/usr/share/icons/hicolor',
        os.path.expanduser('~/.local/share/icons/hicolor'),
        '/var/lib/flatpak/exports/share/icons/hicolor',
        os.path.expanduser('~/.local/share/flatpak/exports/share/icons/hicolor')
    ]:
        if not os.path.isdir(i_dir):
            continue
        for sz in ['scalable', '512x512', '256x256', '128x128', '64x64', '48x48']:
            for ext in ['.svg', '.png']:
                cand = os.path.join(i_dir, sz, 'apps', f'{{clean_name}}{{ext}}')
                if os.path.isfile(cand):
                    found = cand
                    break
            if found:
                break
        if found:
            break

# 4. System theme icons
if not found:
    for theme_dir in ['/usr/share/icons/Papirus', '/usr/share/icons/Yaru', '/usr/share/icons/Adwaita']:
        if not os.path.isdir(theme_dir):
            continue
        for sz in ['128x128/apps', 'scalable/apps', '64x64/apps', '48x48/apps']:
            for ext in ['.svg', '.png']:
                cand = os.path.join(theme_dir, sz, f'{{clean_name}}{{ext}}')
                if os.path.isfile(cand):
                    found = cand
                    break
            if found:
                break
        if found:
            break

if found and os.path.isfile(found):
    _, ext = os.path.splitext(found)
    if not ext:
        ext = '.png'
    dst = os.path.join(cache_dir, f'{{clean_name}}{{ext}}')
    if not os.path.exists(dst):
        try:
            shutil.copyfile(found, dst)
        except Exception:
            dst = found
    print(dst)
"""
        home_dir = os.path.expanduser("~")
        try:
            res = subprocess.run(
                [
                    "flatpak-spawn",
                    "--host",
                    f"--directory={home_dir}",
                    "python3",
                    "-c",
                    copy_script
                ],
                capture_output=True,
                text=True,
                cwd=home_dir,
                timeout=5
            )
            if res.returncode == 0 and res.stdout.strip():
                cached = res.stdout.strip()
                if os.path.exists(cached):
                    return cached
        except Exception as e:
            logger.debug(f"Host icon caching error: {e}")
        return None

    def launch(self, desktop_id: str, desktop_path: str = "") -> bool:
        """
        Launches an application cleanly on the host via gtk-launch or gio launch.
        Supports native system apps, Flatpaks, Snaps, and local desktop files.
        Never blocks the caller.
        """
        if not desktop_id:
            logger.warning("AppLauncher: Attempted to launch empty desktop_id")
            return False

        # Clean desktop_id for gtk-launch (e.g. 'code.desktop' -> 'code')
        clean_id = desktop_id[:-8] if desktop_id.endswith(".desktop") else desktop_id
        home_dir = os.path.expanduser("~")

        # Robust launch command: gtk-launch first, fallback to gio launch with full file path
        if desktop_path:
            inner_cmd = f"gtk-launch {shlex.quote(clean_id)} 2>/dev/null || gio launch {shlex.quote(desktop_path)}"
        else:
            inner_cmd = f"gtk-launch {shlex.quote(clean_id)}"

        if is_in_flatpak():
            cmd = f"flatpak-spawn --host --directory={shlex.quote(home_dir)} sh -c {shlex.quote(inner_cmd)}"
        else:
            cmd = inner_cmd

        logger.info(f"AppLauncher: Launching application with command: {cmd}")

        try:
            subprocess.Popen(
                cmd,
                shell=True,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=home_dir
            )
            return True
        except Exception as e:
            logger.error(f"AppLauncher: Failed to spawn {cmd}: {e}")
            return False
