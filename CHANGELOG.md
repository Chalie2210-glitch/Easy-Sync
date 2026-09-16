# 0.1.3

- 탐색기 우클릭 실행 시 첫 창의 시작이 늦으면 별도 창이 열리던 문제를 수정했습니다.
- 파일 전달 응답을 최대 30초 기다리고, 기존 실행이 응답하지 않아도 중복 창을 열지 않습니다. 전달 확인 실패는 안내합니다.
- 기존 실행이 종료된 경우에만 새 창으로 이어서 실행합니다. 여러 파일의 동시 전달 대기열을 확대했습니다.
- 파일 없이 다시 실행해도 기존 창을 활성화하며, 최소화된 창은 복원합니다.

이미 열린 Easy Sync 창을 모두 종료한 뒤 `Easy-Sync-Setup-0.1.3-x64.exe`를 설치하세요. 기존 설정은 유지됩니다.

# 0.1.2

- 없는 핀 경로를 조회할 때 Wwise에 `from path cannot be resolved` 오류가 남던 문제를 수정했습니다.
- 오디오·이벤트 핀의 경로가 없으면 선택을 해제하고 전체 보기로 돌아가며, 해당 탭의 임포트 위치를 다시 선택하도록 안내합니다.
- 저장된 핀 목록은 유지합니다. 정상적으로 존재하는 빈 컨테이너는 그대로 선택할 수 있습니다.
- 연결 오류 등 실제 조회 실패는 계속 처리하며, 프로젝트 전환 전에 요청한 결과는 새 프로젝트에 적용하지 않습니다.

Easy Sync를 종료한 뒤 `Easy-Sync-Setup-0.1.2-x64.exe`를 설치하세요. 기존 설정은 유지됩니다.

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
