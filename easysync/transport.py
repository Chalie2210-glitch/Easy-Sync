# -*- coding: utf-8 -*-
"""WAAPI 전송 계층 — HTTP 우선, WAMP 예비.

Wwise 는 Authoring API 를 두 가지로 연다.

  * **HTTP** (기본 8090) — 요청/응답만 되는 단순한 JSON 엔드포인트.
  * **WAMP** (기본 8080) — 구독까지 되는 웹소켓 프로토콜. ``waapi-client``
    라이브러리가 쓰는 쪽이다.

Easy Sync 는 구독이 필요 없고 호출만 하므로 **HTTP 를 먼저** 쓴다. 이유는
순전히 속도다. ``import waapi`` 는 autobahn 스택을 끌어와서 이 PC 에서 약
1.0~1.5초가 걸린다 — 툴 전체 시작 시간의 3분의 2였다. HTTP 쪽은 표준
라이브러리만 쓰므로 임포트 비용이 0 이고, 호출 자체도 더 빠르다
(측정: 호출당 약 1.5ms).

HTTP 가 꺼져 있는 환경을 위해 WAMP 예비 경로를 남겨 둔다. 그쪽은 실제로
필요해질 때만 ``waapi`` 를 임포트하므로, HTTP 로 붙는 보통의 경우에는
느린 임포트가 아예 일어나지 않는다.
"""
from __future__ import annotations

import http.client
import json
import logging
import threading
import time

log = logging.getLogger(__name__)

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8090
HTTP_PATH = "/waapi"
# Only reads may be repeated after an ambiguous response failure.
READ_ONLY_CALLS = frozenset({
    "ak.wwise.core.getInfo", "ak.wwise.core.getProjectInfo",
    "ak.wwise.core.object.get", "ak.wwise.ui.getSelectedObjects",
})

#: 처음 붙어 볼 때의 제한 시간(초). 살아 있으면 수십 ms 안에 답한다.
PROBE_TIMEOUT = 5.0


class ConnectionFailed(Exception):
    """Wwise 에 닿지 못했을 때."""


class WaapiError(Exception):
    """Wwise 가 호출을 거부했을 때.

    ``uri`` 는 ``ak.wwise.query.unknown_object`` 같은 오류 종류이고
    ``message`` 는 사람이 읽을 설명이다. WAMP 예외의 통짜 repr 과 달리
    바로 화면에 보여 줄 수 있다.
    """

    def __init__(self, uri: str, message: str) -> None:
        super().__init__(message or uri)
        self.uri = uri
        self.message = message or uri


class HttpTransport:
    """Wwise HTTP 엔드포인트에 JSON 을 던지는 전송.

    연결 하나를 계속 재사용한다(keep-alive). 매번 새로 붙으면 호출마다
    TCP 핸드셰이크가 붙는다.

    ``http.client.HTTPConnection`` 은 스레드 안전하지 않으므로 잠금으로
    감싼다. 호출이 보통 2ms 라 경합은 문제되지 않고, Wwise 자체가 어차피
    요청을 하나씩 처리한다.
    """

    name = "HTTP"

    def __init__(self, host: str = DEFAULT_HTTP_HOST, port: int = DEFAULT_HTTP_PORT,
                 timeout: float = 60.0) -> None:
        self._host, self._port = host, port
        self._lock = threading.Lock()
        self.last_activity = 0.0
        self._conn: http.client.HTTPConnection | None = None
        # 처음 붙어 볼 때는 짧게 끊는다. Wwise 가 포트만 열어 두고 응답하지
        # 않는 상태(종료 중, 프로젝트 전환 중)가 실제로 있는데, 여기서 오래
        # 매달리면 창이 뜨지 않은 채 프로세스만 남는다.
        self._timeout = PROBE_TIMEOUT
        try:
            self.call("ak.wwise.core.getInfo")
        finally:
            # 연결이 확인된 뒤에는 넉넉하게. 임포트는 파일이 많으면 오래 걸린다.
            self._timeout = timeout
            # 살아 있는 연결은 만들어질 때의 제한 시간을 그대로 들고 있다.
            # 버리고 다시 붙어야 위의 값이 실제로 적용된다.
            self._drop()

    def _connect(self) -> http.client.HTTPConnection:
        if self._conn is None:
            self._conn = http.client.HTTPConnection(
                self._host, self._port, timeout=self._timeout)
        return self._conn

    def _drop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def _exchange(self, payload: bytes, headers: dict,
                  *, read_only: bool = False) -> tuple[int, bytes]:
        """Recover stale keep-alive sockets for reads; never replay mutations."""
        attempts = 2 if read_only else 1
        for attempt in range(attempts):
            try:
                conn = self._connect()
                conn.request("POST", HTTP_PATH, body=payload, headers=headers)
                response = conn.getresponse()
                return response.status, response.read()
            except (http.client.HTTPException, OSError) as exc:
                self._drop()
                log.debug("WAAPI HTTP request failed: %r", exc)
                if attempt + 1 == attempts:
                    message = (self._unreachable() if read_only else
                               "Wwise 응답을 받지 못했습니다. 요청이 처리됐을 수 있으므로 "
                               "Wwise에서 결과를 확인하세요. 자동으로 재실행하지 않습니다.")
                    raise ConnectionFailed(message) from exc

    def _unreachable(self) -> str:
        return ("Wwise 에 연결하지 못했습니다.\n"
                "Wwise 가 실행 중인지, 프로젝트 설정 > Authoring API 의\n"
                f"HTTP 포트({self._port})가 켜져 있는지 확인하세요.")

    def call(self, uri: str, args: dict | None = None,
             options: dict | None = None) -> dict:
        # WAMP 쪽 관례대로 options 를 args 안에 넣어 부르는 곳이 있다.
        # 여기서 꺼내 준다 — 부르는 쪽이 전송 방식을 신경 쓰지 않게.
        args = dict(args or {})
        options = options or args.pop("options", None) or {}
        payload = json.dumps(
            {"uri": uri, "args": args, "options": options},
            ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}

        with self._lock:
            try:
                status, body = self._exchange(
                    payload, headers, read_only=uri in READ_ONLY_CALLS)
            finally:
                self.last_activity = time.monotonic()

        text = body.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise WaapiError("ak.wwise.invalid_response", text[:300]) from exc

        if status >= 400:
            raise WaapiError(parsed.get("uri", "ak.wwise.error"),
                             parsed.get("message", text[:300]))
        return parsed

    def close(self) -> None:
        with self._lock:
            self._drop()


class WampTransport:
    """``waapi-client`` 를 쓰는 예비 전송.

    HTTP 가 꺼져 있을 때만 쓴다. ``waapi`` 임포트가 느리므로 이 클래스를
    실제로 만들 때 임포트한다 — 모듈 최상단에서 하면 안 된다.
    """

    name = "WAMP"

    def __init__(self, url: str | None = None) -> None:
        try:
            from waapi import CannotConnectToWaapiException, WaapiClient
            from waapi.wamp.interface import WaapiRequestFailed
        except ImportError as exc:  # pragma: no cover - 설치 문제
            raise ConnectionFailed("waapi-client 가 설치되어 있지 않습니다.") from exc

        self._request_failed = WaapiRequestFailed
        try:
            # allow_exception=True 가 반드시 필요하다. 기본값에서는 실패한
            # 호출이 예외 대신 None 을 돌려준다 — 임포트가 실패해도
            # "성공했다" 고 보고하게 된다.
            self._client = (WaapiClient(url=url, allow_exception=True) if url
                            else WaapiClient(allow_exception=True))
        except CannotConnectToWaapiException as exc:
            raise ConnectionFailed(
                "Wwise 에 연결하지 못했습니다.\n\n"
                "Wwise 가 실행 중인지, 그리고\n"
                "프로젝트 > 프로젝트 설정 > Authoring API 가 켜져 있는지 "
                "확인하세요."
            ) from exc

    def call(self, uri: str, args: dict | None = None,
             options: dict | None = None) -> dict:
        payload = dict(args or {})
        if options:
            payload["options"] = options
        try:
            return self._client.call(uri, payload) or {}
        except self._request_failed as exc:
            kwargs = getattr(exc, "kwargs", None) or {}
            raise WaapiError(getattr(exc, "uri", "ak.wwise.error"),
                             kwargs.get("message") or str(exc)) from exc

    def close(self) -> None:
        try:
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def connect(url: str | None = None, *, prefer_http: bool = True,
            allow_wamp: bool = True):
    """전송을 하나 만들어 돌려준다. HTTP 를 먼저 시도한다.

    ``allow_wamp=False`` 면 HTTP 로 못 붙었을 때 바로 포기한다. Wwise 가
    켜지기를 기다리며 반복해서 두드릴 때 쓴다 — WAMP 쪽은 ``import waapi``
    만 1초 가까이 걸려서, 매번 시도하면 몇 초에 한 번씩 밖에 못 두드린다.
    """
    if prefer_http and not url:
        try:
            transport = HttpTransport()
            log.info("WAAPI 전송: HTTP %s:%s", DEFAULT_HTTP_HOST, DEFAULT_HTTP_PORT)
            return transport
        except (ConnectionFailed, WaapiError) as exc:
            if not allow_wamp:
                raise ConnectionFailed(str(exc)) from exc
            log.info("HTTP 로 붙지 못해 WAMP 로 넘어갑니다: %s", exc)
    elif not allow_wamp and not url:
        raise ConnectionFailed("HTTP 전송이 꺼져 있습니다.")
    transport = WampTransport(url)
    log.info("WAAPI 전송: WAMP")
    return transport
