# Unreleased

- Recover when Wwise closes and another project opens, even with stalled background work.
- Clear the previous project's destinations, active pins, event checks and switch assignments on project change.
- Automatic events require explicit opt-in on each launch; the setting is no longer saved.
- Public source tree excludes tests and unused upstream example/test notices.
- Added a Korean guide for everyday import, audio replacement and event creation.

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
