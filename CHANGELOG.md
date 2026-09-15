# 0.1.1

## 주요 변경

- 오디오·이벤트 핀을 Wwise 프로젝트별로 저장하고, 추가·삭제 즉시 반영합니다.
- 기존 Wwise를 닫고 다른 프로젝트를 열었을 때 재연결을 개선했습니다.
- 자동 이벤트는 실행할 때마다 직접 켜야 하며, 이전 체크 상태를 저장하지 않습니다.

## 업데이트 안내

Easy Sync를 종료한 뒤 `Easy-Sync-Setup-0.1.1-x64.exe`를 실행하세요.
기존 설치 위치와 설정은 유지됩니다. 기존 공용 핀은 설정 파일에 보관되지만 자동 적용하지 않으므로,
필요한 핀을 각 프로젝트에서 한 번씩 다시 등록하세요.
프로젝트는 `.wproj` 전체 경로로 구분하므로 파일을 이동하거나 이름을 바꾸면 핀을 다시 등록해야 합니다.

## Details

- Store audio and event pins per Wwise project path, save edits immediately, and restore each project's list on reconnect. Legacy shared pins remain in settings without being applied automatically.
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
