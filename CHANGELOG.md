# 0.1.0

First public MIT release of Easy Sync for Windows x64.

- Standalone installer with Explorer/Wwise menu registration.
- Settings and favorites survive upgrades and uninstall.
- Explicit update check with SHA-256 verified installer download.
- Random defaults, long-path display and original source lookup.
- Audio replacement preserves Sound IDs and event references.
- No default Wwise keyboard shortcut, avoiding the backtick conflict.

Known limitation: a previously registered Explorer menu can remain hidden above
15 selected files in an already-running Explorer session. Folder import and
drag-and-drop remain available. See README for details.
