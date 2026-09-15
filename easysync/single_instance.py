# -*- coding: utf-8 -*-
"""여러 번 실행된 것을 창 하나로 모은다.

탐색기에서 파일 다섯 개를 골라 우클릭하면 Windows 는 프로그램을 **다섯 번**
띄운다. 각 프로세스에는 파일이 하나씩 인자로 들어온다. 그대로 두면 창이
다섯 개 뜨고 각각 파일 하나씩만 들고 있게 된다 — 여러 파일을 컨테이너로
묶는다는 이 툴의 목적이 완전히 무너진다.

그래서 첫 번째 프로세스가 로컬 포트를 잡아 "주인" 이 되고, 나머지는 자기
파일 경로만 주인에게 넘기고 끝난다.

**가장 중요한 규칙: 모으기에 실패해도 실행은 되어야 한다.**

실제로 겪은 사고가 그것이다. 시작 도중 멈춘 프로세스가 창도 없이 포트만
쥐고 있었고, 그 뒤로 우클릭을 아무리 눌러도 새 프로세스가 "이미 떠 있네"
하고 조용히 종료했다. 사용자 눈에는 프로그램이 그냥 안 켜지는 것으로 보였고,
로그를 보기 전에는 원인을 알 수 없었다.

그래서 지금은 넘기기가 **응답(ack)** 을 요구한다. 주인은 창이 실제로 뜬
뒤에만 응답한다. 응답이 없으면 그쪽은 죽었거나 멈춘 것으로 보고, 넘기려던
프로세스가 자기 창을 연다. 창이 두 개 뜨는 쪽이 하나도 안 뜨는 것보다 낫다.

127.0.0.1 에만 바인딩한다. 바깥에서 접속할 수 없고, 받는 것은 이 PC 의
파일 경로뿐이다.
"""
from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
#: 고정 포트. 다른 프로그램과 겹칠 가능성이 낮은 대역에서 골랐다.
PORT = 49731
ENCODING = "utf-8"

#: 주인이 "받았다" 고 보내는 응답. 이게 와야 넘기기가 성공한 것이다.
ACK = b"EASYSYNC-OK\n"

#: 넘긴 쪽이 응답을 기다리는 시간(초).
#: 양쪽으로 틀릴 수 있는 값이라 실제 시작 시간을 재고 잡았다. 창이 뜨기까지
#: 보통 2초 안팎이므로 그 두 배 남짓.
#:   너무 짧으면 — 정상적으로 시작 중인 주인을 죽은 것으로 보고 형제들이
#:                제각기 창을 연다.
#:   너무 길면   — 주인이 정말 멈췄을 때 사용자가 그만큼 빈 화면을 본다.
ACK_TIMEOUT = 6.0

#: 주인이 "창 떴다" 신호를 기다리는 시간(초). 이 안에 안 뜨면 응답하지 않아
#: 넘기려던 쪽이 자기 창을 열게 한다. ACK_TIMEOUT 보다 짧아야 상대가
#: 기다리다 끊기 전에 결론이 난다.
READY_TIMEOUT = 5.0


def claim() -> socket.socket | None:
    """주인이 되려 시도한다. 성공하면 듣는 소켓, 이미 주인이 있으면 None."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # SO_REUSEADDR 를 켜지 않는다. 켜면 이미 듣고 있는 인스턴스가 있어도
        # 바인딩이 성공해 버려서 창이 두 개 뜬다.
        server.bind((HOST, PORT))
        server.listen(16)
        return server
    except OSError:
        server.close()
        return None


def forward(files: list[Path]) -> bool:
    """이미 떠 있는 창에 파일 경로를 넘긴다. 응답을 받으면 True.

    False 면 저쪽이 죽었거나 멈춘 것이다. 부른 쪽은 종료하지 말고 자기 창을
    열어야 한다.
    """
    payload = "\n".join(str(f) for f in files) or "\n"
    try:
        with socket.create_connection((HOST, PORT), timeout=ACK_TIMEOUT) as client:
            client.sendall(payload.encode(ENCODING))
            # 보낼 것이 끝났음을 알린다. 안 그러면 주인이 계속 recv 로 기다린다.
            client.shutdown(socket.SHUT_WR)
            client.settimeout(ACK_TIMEOUT)
            reply = b""
            while len(reply) < len(ACK):
                chunk = client.recv(64)
                if not chunk:
                    break
                reply += chunk
            if reply.startswith(ACK):
                return True
            log.warning("이미 떠 있는 창이 응답하지 않았습니다 (받은 값: %r)", reply)
            return False
    except OSError as exc:
        log.warning("이미 떠 있는 창에 넘기지 못했습니다: %s", exc)
        return False


def serve(server: socket.socket, on_files: Callable[[list[Path]], None],
          ready: threading.Event) -> None:
    """형제 프로세스가 보내는 파일 경로를 계속 받는다.

    ``ready`` 가 서 있을 때만 응답한다. 창이 아직 없는데 응답해 버리면
    상대는 "전달됐구나" 하고 종료하는데 그 파일은 아무 데도 안 나타난다.

    데몬 스레드로 돈다. 창이 닫히면 프로세스와 함께 사라진다.
    """
    def handle(conn: socket.socket) -> None:
        with conn:
            try:
                conn.settimeout(ACK_TIMEOUT)
                chunks = []
                while True:
                    data = conn.recv(8192)
                    if not data:
                        break
                    chunks.append(data)
            except OSError:
                return

            text = b"".join(chunks).decode(ENCODING, errors="replace")
            paths = [Path(line) for line in text.splitlines() if line.strip()]

            # 창이 뜰 때까지 기다렸다가 넘긴다. 시작 직후에 형제들이 몰려
            # 들어오는 것이 정상이라 여기서 잠깐 기다리는 것이 맞다.
            if not ready.wait(READY_TIMEOUT):
                log.warning("창이 준비되지 않아 %d개를 받지 못했습니다", len(paths))
                return
            if paths:
                on_files(paths)
            try:
                conn.sendall(ACK)
            except OSError:
                pass

    def loop() -> None:
        while True:
            try:
                conn, _addr = server.accept()
            except OSError:
                return  # 소켓이 닫혔다
            # 한 연결이 ready 를 기다리는 동안 다음 연결을 막지 않는다.
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=loop, daemon=True, name="easysync-ipc").start()
