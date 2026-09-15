# Third-party software

Easy Sync's own source code is licensed under MIT. Third-party components retain
their own licenses; MIT does not replace these licenses.

- Python: PSF license. https://www.python.org/downloads/source/
- PySide6 / Shiboken6 / Qt: LGPLv3 (or other licenses specified in individual
  component notices). https://doc.qt.io/qtforpython-6/licenses.html
- waapi-client: Apache-2.0. https://github.com/audiokinetic/waapi-client-python
- Autobahn and its dependencies: see the bundled component license notices.
- PyInstaller bootloader: GPL with an exception allowing distribution of bundled
  applications under their own licenses. https://pyinstaller.org/en/stable/license.html

The installer includes `ThirdPartyLicenses/` with the build's exact dependency
versions and available license texts, including Python's license. Qt DLLs and
Python bindings are distributed as separate files in `_internal/`; they are not
statically linked into Easy Sync. Users may replace these libraries with compatible
modified versions. Reverse engineering for debugging modifications to LGPL
components is permitted. Build instructions are in README.md and packaging/.

Corresponding upstream source for Qt and PySide/Shiboken is available at:

- PySide6 / Shiboken 6.11.1: https://github.com/pyside/pyside-setup/archive/refs/tags/v6.11.1.tar.gz
- Qt Base 6.11.1 (Core, Gui, Widgets, Network): https://github.com/qt/qtbase/archive/refs/tags/v6.11.1.tar.gz
- Qt SVG 6.11.1: https://github.com/qt/qtsvg/archive/refs/tags/v6.11.1.tar.gz

Full upstream license texts, copyright notices and attribution manifests for
these exact versions are included under `ThirdPartyLicenses/Upstream/`.
`sources.json` records the source archive URLs and SHA-256 hashes. Qt Virtual
Keyboard, Qt PDF, Qt Quick and other unused modules are excluded from the build.

Wwise itself, its SDK, icons and audio assets are not included in this repository
or installer. Wwise is a separate product of Audiokinetic. Easy Sync is an
independent community tool and is not affiliated with Audiokinetic.
