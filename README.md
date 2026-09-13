# App Launcher for StreamController

A StreamController plugin that automatically discovers all installed desktop applications on the host Linux system (native packages, Flatpaks, and Snaps) and lets you launch them with a single tap from your Stream Deck or touchscreen.

## Features

- **No Commands Required**: Automatically scans system `.desktop` files and queues up all installed applications.
- **Searchable Application Picker**: Search and select any installed app using a native Libadwaita dropdown (`Adw.ComboRow`).
- **Automatic Icon & Label Setup**: Fetches the official application icon and sets the button label automatically.
- **Seamless Flatpak Sandbox Bypass**: Uses `flatpak-spawn --host` to launch apps in your host user session via `gtk-launch`.
- **Customizable**: Option to override the label or hide labels for an icon-only button look.
- **Rescan Anytime**: Built-in rescan button to detect newly installed software without restarting StreamController.

## Supported Formats

- Native system applications (`/usr/share/applications`, `/usr/local/share/applications`)
- User applications (`~/.local/share/applications`)
- System & user Flatpaks (`/var/lib/flatpak/exports/share/applications`, `~/.local/share/flatpak/exports/share/applications`)
- Snap packages (`/var/lib/snapd/desktop/applications`)

## License

MIT
