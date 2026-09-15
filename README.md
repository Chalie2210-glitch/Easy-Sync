# Easy Sync

Windows에서 오디오 파일을 Wwise로 가져오는 데스크톱 도구입니다.
파일 묶기, 컨테이너 선택, 이벤트 생성, 임포트 위치 확인을 한 화면에서 처리합니다.

## 설치

1. [최신 릴리스](https://github.com/Chalie2210-glitch/Easy-Sync/releases/latest)에서 **Easy-Sync-Setup-x.y.z-x64.exe**를 받습니다.
2. 설치 파일을 실행합니다. Python을 별도로 설치할 필요가 없습니다.
3. 기본 위치는 `%LOCALAPPDATA%\Programs\Easy Sync`입니다. 바로가기·탐색기 메뉴·Wwise 메뉴를 함께 설치할 수 있습니다.
4. Wwise에서 WAAPI를 활성화한 뒤 Easy Sync를 실행합니다.

지원 환경: Windows 10/11 x64, WAAPI를 지원하는 Wwise Authoring.
Wwise 2025.1 계층과 이전 버전 Actor-Mixer 계층을 처리합니다.
Wwise 자체와 오디오 파일은 포함되지 않습니다.

## 사용

- 파일을 창에 끌어 놓거나 **파일 → 파일 추가**를 사용합니다.
- 탐색기에서 파일 또는 폴더를 우클릭 → **Easy Sync 로 보내기**로 추가합니다. Windows 11에서는 **추가 옵션 표시**에 있습니다.
- 오디오 위치와 이벤트 위치를 정하고, 생성될 경로를 확인한 뒤 임포트합니다.
- 자동 묶기의 기본 컨테이너는 Random입니다. 경로 추천은 기본으로 꺼져 있습니다.
- 이벤트 이름에 `Play_`를 자동으로 붙이지 않습니다. 이벤트의 재생 액션은 Play입니다.
- **오디오만 교체**는 같은 경로·이름의 Sound ID와 이벤트 참조를 유지합니다. 이름이나 위치를 바꾸면 새 오브젝트가 됩니다.
- 기존 Switch/Sequence와 요청한 Random이 충돌하면 임포트 전에 알려줍니다.
- Wwise Sound/Audio Source 우클릭 → **Easy Sync → 가져온 원본 파일 찾기**로 최초 원본을 찾습니다. 원본 이동·삭제 또는 과거 임포트에 기록이 없으면 찾을 수 없습니다.

기본 Wwise 단축키는 등록하지 않습니다. 필요한 키는 Wwise 단축키 관리자에서 지정하세요.

## 업데이트

**도움말 → 업데이트 확인**에서 최신 정식 릴리스를 확인하고 다운로드합니다.
크기와 GitHub SHA-256 값을 검증한 후 설치를 누르면 앱이 종료되고 설치 프로그램이 열립니다.
업데이트를 강제 실행하지 않습니다. 인터넷이 없거나 검증에 실패해도 기존 앱을 사용할 수 있습니다.

새 설치 파일을 직접 실행해도 같은 위치에 갱신됩니다. 버전 간 설치 ID는 유지됩니다.
임포트 중에는 종료·업데이트를 막습니다. 설치 프로그램은 Easy Sync가 종료될 때까지 기다리며 Wwise를 강제 종료하지 않습니다.

- 설정/즐겨찾기: `%APPDATA%\EasySync\settings.json`
- 로그: `%LOCALAPPDATA%\EasySync\Logs`
- 다운로드: `%LOCALAPPDATA%\EasySync\Updates`

설정은 업데이트와 프로그램 제거 후에도 보존됩니다.

## 알려진 제한

- 탐색기 정적 메뉴는 최대 100개 선택 모델입니다. 더 많은 파일은 폴더 자체 보내기 또는 드래그 앤 드롭을 사용하세요.
- 일부 실행 중인 탐색기에서 16개 이상 선택 시 메뉴가 사라지는 현상을 확인했습니다. 원인은 확인 중입니다. 폴더 보내기·드래그 앤 드롭을 사용할 수 있습니다.
- 첫 공개 빌드는 코드 서명 인증서가 없습니다.
- 설치된 Wwise의 아이콘을 런타임에 읽으며 해당 아이콘을 재배포하지 않습니다.

## 소스 실행 / 빌드

Python 3.12 x64와 Inno Setup 6이 필요합니다. PowerShell에서:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe run_easysync.pyw
.\.venv\Scripts\python.exe -m unittest discover -s tests_release -v
.\packaging\build.ps1 -Python .\.venv\Scripts\python.exe
```

결과: `dist/release/Easy-Sync-Setup-x.y.z-x64.exe`, `SHA256SUMS.txt`.
PyInstaller 폴더 배포 방식으로 실행 시마다 임시 폴더에 압축을 풀지 않습니다.
Qt 공유 라이브러리는 `_internal`에 별도로 배치됩니다.

`easysync/version.py` 버전을 올리고 `vX.Y.Z` 태그를 푸시하면 GitHub Actions가
테스트, Windows 빌드, 설치/업데이트/제거 검증 후 릴리스를 발행합니다.
개인 경로·오디오·Wwise 프로젝트·로그·작업 메모는 Git에 포함하지 않습니다.

## 라이선스

Easy Sync 소스는 [MIT](LICENSE)입니다. 포함된 라이브러리는 각자의 라이선스를 따릅니다.
[서드파티 고지](THIRD_PARTY_NOTICES.md)를 확인하세요.
이 프로젝트는 Audiokinetic과 관련 없는 독립 도구입니다.
