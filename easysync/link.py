# -*- coding: utf-8 -*-
"""Wwise 연결 관리 — 붙을 때까지 기다리고, 끊기면 다시 붙는다.

예전에는 시작할 때 Wwise 에 못 붙으면 오류 창만 띄우고 끝났다. 사운드
작업은 Wwise 를 자주 껐다 켜고 프로젝트도 바꾸는데, 그때마다 툴을 다시
띄워야 했다.

지금은 창이 먼저 뜬다. 연결은 뒤에서 알아서 된다.

  * Wwise 가 아직 없으면 — 창은 뜨고 "연결 대기 중" 으로 있는다.
    Wwise 를 켜면 몇 초 안에 스스로 붙는다.
  * 쓰던 중에 Wwise 가 꺼지면 — 끊긴 것을 알아채고 임포트를 막은 뒤
    다시 붙을 때까지 기다린다. 가져온 파일과 묶음은 그대로 둔다.
  * 프로젝트가 바뀌면 — 다른 프로젝트임을 알아채고 다시 붙은 것으로
    취급한다(경로가 전부 달라지므로 트리를 새로 읽어야 한다).

살아 있는지는 기본 15초마다 확인하며, 임포트 중에는 확인을 미룬다.
연속 두 번 실패하거나 상태 확인이 시간 제한을 넘기면 재연결한다.
"""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .tasks import ConnectionTasks
from .waapi_bridge import ProjectInfo, WwiseBridge

log = logging.getLogger(__name__)

#: Wwise 를 찾는 동안 다시 시도하는 간격(초).
#: 사용자가 Wwise 를 켜고 "왜 안 붙지" 하기 전에 붙어야 한다.
RETRY_SECONDS = 2.0

#: 붙은 뒤 살아 있는지 확인하는 간격(초).
HEARTBEAT_SECONDS = 15.0
FAILURE_THRESHOLD = 2

#: 몇 번에 한 번씩 WAMP 까지 시도할지. HTTP 포트를 꺼 둔 환경을 위한 보험.
WAMP_EVERY = 10

#: 한 번의 연결 시도가 이보다 오래 걸리면 매달린 것으로 보고 다시 시도한다.
#:
#: 이게 없어서 실제로 사고가 났다. WAMP 연결 시도가 응답 없이 멈추자
#: "시도 중" 표시가 영원히 남았고, 그 뒤로는 Wwise 를 켜도 재시도 자체가
#: 일어나지 않았다 — 사용자 눈에는 "Wwise 를 켰는데도 안 붙는다" 였다.
ATTEMPT_TIMEOUT = 20.0


class NotReady(Exception):
    """붙긴 했는데 아직 쓸 상태가 아니다(프로젝트를 여는 중)."""


class WwiseLink(QObject):
    """Wwise 연결 하나를 들고 상태를 알려 준다."""

    #: 새로 붙었다. 인자는 ProjectInfo.
    connected = Signal(object)
    #: 끊겼다. 인자는 사람이 읽을 이유.
    lost = Signal(str)
    #: 붙는 중에 상태 문구가 바뀔 때.
    status = Signal(str)

    def __init__(self, url: str | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = url
        self._tasks = ConnectionTasks(self)
        # waapi-client's WAMP constructor can wait without a timeout. Never queue
        # more WAMP attempts behind it; independent HTTP probes must still run.
        self._fallback_lock = threading.Lock()
        self._last_project_check = 0.0
        self.bridge: WwiseBridge | None = None
        self.project: ProjectInfo | None = None
        self._failures = 0
        self._suspended = False
        self._busy = False          # 시도가 이미 돌고 있는가
        self._busy_since = 0.0      # 그 시도가 시작된 시각
        # 버린 시도의 결과를 알아보기 위한 세대 번호. 시도를 버릴 때마다
        # 올라가고, 결과가 돌아왔을 때 번호가 다르면 그 결과는 버린다.
        self._generation = 0
        self._attempts = 0          # 연결 시도 횟수 (WAMP 를 언제 볼지 정하는 데 쓴다)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # -- 공개 --------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self.bridge is not None

    def start(self) -> None:
        """붙기를 시작한다. 이미 붙어 있으면 상태 확인으로 넘어간다."""
        self._tick()
        self._timer.start(int(RETRY_SECONDS * 1000))

    def stop(self) -> None:
        self._timer.stop()
        self.close()

    def close(self) -> None:
        self._generation += 1
        self._busy = False
        bridge, self.bridge = self.bridge, None
        self.project = None
        if bridge is not None:
            # A pending import may own the socket lock. Never wait on the UI thread.
            self._tasks.run(bridge.close)

    def suspend_checks(self, suspended: bool) -> None:
        self._suspended = suspended

    def note_failure(self, exc: Exception) -> None:
        """Confirm a transport failure before resetting the whole UI."""
        if self.bridge is not None and _looks_like_disconnect(exc):
            self._timer.start(int(RETRY_SECONDS * 1000))

    def check_now(self) -> None:
        """Manual refresh also wakes disconnected or overdue connection checks."""
        if self._suspended:
            return
        self._last_project_check = 0.0
        self._timer.start(int(RETRY_SECONDS * 1000))
        self._tick()

    # -- 내부 --------------------------------------------------------------
    def _tick(self) -> None:
        if self._suspended:
            return
        if self._busy:
            # 매달린 시도를 언제까지고 기다리지 않는다. 버려진 시도는
            # 스레드에 남겨 두고(데몬이라 프로세스와 함께 사라진다) 새로
            # 두드린다. 이걸 안 해서 재시도가 영영 멈춘 적이 있다.
            if time.monotonic() - self._busy_since < ATTEMPT_TIMEOUT:
                return
            log.warning("연결 시도가 %.0f초 넘게 응답이 없어 다시 시도합니다.",
                        ATTEMPT_TIMEOUT)
            if self.bridge is not None:
                self._drop("Wwise 상태 확인이 멈춰 연결을 다시 찾습니다.")
                return
            # 버린 시도가 나중에 끝나도 상태를 건드리지 못하게 한다.
            self._generation += 1
        if self.bridge is not None:
            if getattr(self.bridge, "busy", False):
                return
            if (not self._failures
                    and self._timer.interval() != int(RETRY_SECONDS * 1000)
                    and time.monotonic() - self._last_project_check < HEARTBEAT_SECONDS):
                return
        self._busy = True
        self._busy_since = time.monotonic()
        self._timer.start(int(RETRY_SECONDS * 1000))
        gen = self._generation
        if self.bridge is None:
            self._tasks.run(
                self._try_connect,
                on_done=lambda r, g=gen: self._on_connected(r, g),
                on_fail=lambda e, g=gen: self._on_attempt_failed(e, g))
        else:
            self._tasks.run(
                self._heartbeat,
                on_done=lambda r, g=gen: self._on_heartbeat(r, g),
                on_fail=lambda e, g=gen: self._on_heartbeat_failed(e, g))

    def _is_current(self, gen: int) -> bool:
        """이 결과가 지금 기다리던 시도의 것인가."""
        return gen == self._generation

    def _try_connect(self) -> tuple[WwiseBridge, ProjectInfo]:
        self._attempts += 1
        # 대부분은 HTTP 로 붙는다. 두드릴 때마다 WAMP 까지 시도하면 시도 한
        # 번이 몇 초가 되어 폴링이 폴링이 아니게 된다. 가끔만 WAMP 도 본다 —
        # HTTP 포트를 꺼 둔 환경에서도 결국 붙게.
        allow_wamp = self._attempts == 1 or self._attempts % WAMP_EVERY == 0
        owns_fallback = (bool(self._url) or allow_wamp) and self._fallback_lock.acquire(False)
        if self._url and not owns_fallback:
            raise NotReady("이전 WAMP 연결 시도가 끝나기를 기다리는 중입니다.")
        try:
            bridge = WwiseBridge(self._url, allow_wamp=bool(owns_fallback))
            try:
                project = bridge.project_info()
            except Exception:
                bridge.close()
                raise
            # WAAPI also responds while a project is still opening.
            if not project.name or not project.roots.containers_default_wu:
                bridge.close()
                raise NotReady("Wwise 가 아직 프로젝트를 여는 중입니다.")
            return bridge, project
        finally:
            if owns_fallback:
                self._fallback_lock.release()

    def _heartbeat(self) -> ProjectInfo | None:
        """살아 있는지 + 같은 프로젝트인지 확인한다."""
        bridge = self.bridge
        if bridge is None:
            return None
        return bridge.project_info()

    def _on_connected(self, result, gen: int = 0) -> None:
        bridge, project = result
        if not self._is_current(gen):
            # 버린 시도가 뒤늦게 성공했다. 그 브리지를 그대로 두면 소켓이
            # 새고, self.bridge 를 덮어쓰면 connected 가 두 번 나간다.
            log.debug("버린 연결 시도가 뒤늦게 성공해 닫습니다.")
            self._tasks.run(bridge.close)
            return
        self._busy = False
        self._failures = 0
        self._last_project_check = time.monotonic()
        self.bridge, self.project = bridge, project
        log.info("Wwise 연결됨: %s (%s)", project.name, bridge.transport_name)
        self.connected.emit(project)
        # 붙었으면 이제 하트비트 주기로 바꾼다.
        self._timer.start(int(HEARTBEAT_SECONDS * 1000))

    def _on_attempt_failed(self, exc: Exception, gen: int = 0) -> None:
        if not self._is_current(gen):
            return
        self._busy = False
        self.status.emit("Wwise 가 프로젝트를 여는 중..." if isinstance(exc, NotReady)
                         else "Wwise 를 기다리는 중...")

    def _on_heartbeat(self, project: ProjectInfo | None, gen: int = 0) -> None:
        if not self._is_current(gen):
            return
        self._busy = False
        # 이 하트비트가 도는 사이에 연결이 끊겼을 수 있다. 그때 project 를
        # 되살리면 "브리지는 없는데 프로젝트는 있는" 상태가 되고, 경로가
        # 다르면 connected 까지 나가 빈 트리로 "연결됨" 이 표시된다.
        if project is None or self.bridge is None:
            return
        self._failures = 0
        self._last_project_check = time.monotonic()
        self._timer.start(int(HEARTBEAT_SECONDS * 1000))
        if not project.name or not project.roots.containers_default_wu:
            self._drop("Wwise 프로젝트를 전환하는 중입니다.")
            return
        previous = self.project
        self.project = project
        # 프로젝트가 바뀌면 경로가 전부 달라진다. 새로 붙은 것으로 다룬다.
        if previous is not None and project.path != previous.path:
            log.info("프로젝트가 바뀌었습니다: %s -> %s", previous.name, project.name)
            self.connected.emit(project)

    def _on_heartbeat_failed(self, exc: Exception, gen: int = 0) -> None:
        if not self._is_current(gen):
            return
        self._busy = False
        # 연결이 끊긴 것과 Wwise 가 요청을 거절한 것은 다르다. 모달 창이
        # 떠 있으면 WAAPI 가 잠시 거절하는데, 그걸 끊김으로 보면 창이
        # 통째로 잠겼다가 다시 붙느라 트리가 깜빡인다.
        if _looks_like_disconnect(exc):
            self._failures += 1
            if self._failures >= FAILURE_THRESHOLD:
                self._drop("Wwise 응답을 연속으로 받지 못했습니다.")
            else:
                self._timer.start(int(RETRY_SECONDS * 1000))
        else:
            log.debug("하트비트 실패(연결은 유지): %s", exc)
            self._last_project_check = time.monotonic()
            self._timer.start(int(HEARTBEAT_SECONDS * 1000))

    def _drop(self, reason: str) -> None:
        log.info("연결 해제: %s", reason)
        # 돌고 있는 하트비트의 결과가 끊긴 상태를 되돌리지 못하게 한다.
        self._generation += 1
        self._busy = False
        self.close()
        self.lost.emit(reason)
        # 다시 찾기 시작한다.
        self._timer.start(int(RETRY_SECONDS * 1000))


def _looks_like_disconnect(exc: Exception) -> bool:
    """이 예외가 '연결이 끊겼다' 를 뜻하는가.

    Wwise 가 그냥 거절한 요청(없는 경로 등)과 구분해야 한다. 그건 연결
    문제가 아니라 정상적인 대답이다.
    """
    from .transport import ConnectionFailed, WaapiError

    if isinstance(exc, WaapiError):
        return False
    if isinstance(exc, (ConnectionFailed, ConnectionError, TimeoutError)):
        return True
    text = str(exc).lower()
    return any(word in text for word in
               ("connection refused", "connection reset", "timed out", "not connected", "10061", "10054"))
