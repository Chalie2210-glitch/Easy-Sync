# -*- coding: utf-8 -*-
"""WAAPI 호출을 UI 스레드 밖에서 돌리는 작은 도구.

창(ui)과 연결 관리자(link)가 둘 다 써야 해서 따로 뺐다.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(object)     # 예외 객체 그대로. 부른 쪽이 종류를 본다.


class Task(QRunnable):
    """백그라운드에서 함수 하나를 돌린다.

    Wwise 가 모달 창에 막혀 있으면 호출이 오래 걸릴 수 있다. 그동안 창이
    얼어붙으면 사용자는 툴이 죽은 줄 안다.
    """

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self.signals = TaskSignals()
        self._fn, self._args, self._kwargs = fn, args, kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001
            log.debug("백그라운드 작업 실패: %s", exc, exc_info=True)
            self._emit(self.signals.failed, exc)
            return
        self._emit(self.signals.done, result)

    @staticmethod
    def _emit(signal, payload) -> None:
        """결과를 보낸다. 받을 쪽이 이미 사라졌으면 조용히 넘어간다.

        창을 닫는 순간에도 작업이 돌고 있을 수 있다. 그때 Qt 객체가 먼저
        정리되면 emit 이 ``Signal source has been deleted`` 로 터진다 —
        실제 문제가 아니라 종료 순서일 뿐이라 로그만 남긴다.
        """
        try:
            signal.emit(payload)
        except RuntimeError as exc:
            log.debug("결과를 전달할 대상이 이미 사라졌습니다: %s", exc)


class TaskRunner:
    """실행 중인 Task 를 붙잡아 두는 자리.

    ``QThreadPool.start()`` 에 넘긴 QRunnable 은 C++ 쪽이 소유하지만, 파이썬
    ``Task`` 객체와 그 안의 ``signals`` QObject 는 파이썬이 소유한다. 참조를
    남기지 않으면 가비지 컬렉터가 시그널 객체를 먼저 거둬 가고, 작업이 끝나도
    ``done`` 이 아무 데도 닿지 않는다 — 화면이 "읽는 중..." 에서 멈춘다.
    """

    def __init__(self, pool: QThreadPool | None = None) -> None:
        self._pool = pool or QThreadPool.globalInstance()
        self._live: set[Task] = set()

    def run(self, fn, *args, on_done=None, on_fail=None, **kwargs) -> None:
        task = Task(fn, *args, **kwargs)
        self._live.add(task)

        def release(*_ignored) -> None:
            self._live.discard(task)

        if on_done is not None:
            task.signals.done.connect(on_done)
        if on_fail is not None:
            task.signals.failed.connect(on_fail)
        task.signals.done.connect(release)
        task.signals.failed.connect(release)
        self._pool.start(task)
