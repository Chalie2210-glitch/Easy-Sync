# -*- coding: utf-8 -*-
"""이름의 단어로 Wwise 경로를 추천한다.

프로젝트마다 이름 규칙이 다르지만 ``_`` 로 끊어 쓰는 것은 대체로 공통이다.
``Creature_Footstep_Grass_A_ACT_01`` 을 ``CR / NPC / SF / Grass / A / ACT / 01`` 로
쪼개면, 그 단어들이 Wwise 계층 어디에 모여 있는지 찾을 수 있다.

찾는 방식은 단순하다.

  1. 파일 이름에서 **드문 단어**부터 고른다. ``NPC`` 처럼 어디에나 있는
     단어로 찾으면 후보가 수백 개가 되어 쓸모가 없다.
  2. 그 단어로 Wwise 를 검색한다.
  3. 찾은 오브젝트의 **부모 경로**를 후보로 모은다. 파일이 들어갈 곳은
     맞은 오브젝트 자신이 아니라 그 옆자리이기 때문이다.
  4. 후보 경로에 우리 단어가 몇 개나 들어 있는지로 점수를 매긴다.

추천일 뿐이라 틀려도 된다. 사용자가 누르기 전에는 아무것도 바뀌지 않는다.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .schema import SEP

log = logging.getLogger(__name__)

#: 이 길이 이하의 단어는 검색어로 쓰지 않는다. ``A`` ``01`` 같은 것으로
#: 검색하면 프로젝트 절반이 걸린다.
MIN_WORD = 3

#: 검색어로 쓸 단어 개수. 많을수록 정확하지만 그만큼 WAAPI 호출이 는다.
MAX_QUERIES = 4

#: 한 단어당 받아올 최대 결과.
PER_QUERY = 60

#: 어느 프로젝트에나 흔해서 변별력이 없는 단어. 검색어로는 쓰지 않지만
#: 점수 계산에는 쓴다(후보를 고를 때는 도움이 된다).
STOP_WORDS = frozenset({
    "sfx", "vox", "amb", "mus", "ui", "act", "sf",
    "a", "b", "c", "d", "new", "tmp", "test", "wav",
})


def split_words(text: str) -> list[str]:
    """``_`` ``-`` 공백 ``.`` 으로 끊어 단어를 뽑는다."""
    return [w for w in re.split(r"[ _\-.]+", text) if w]


@dataclass
class Suggestion:
    path: str
    score: float
    matched: list[str]

    def reason(self) -> str:
        return "일치: " + ", ".join(self.matched[:4])


def _query_words(words: list[str]) -> list[str]:
    """검색에 쓸 단어를 고른다 — 긴 것, 흔하지 않은 것부터."""
    seen: list[str] = []
    for word in words:
        low = word.lower()
        if len(word) < MIN_WORD or low in STOP_WORDS or word.isdigit():
            continue
        if low not in [s.lower() for s in seen]:
            seen.append(word)
    # 긴 단어일수록 변별력이 있다.
    seen.sort(key=len, reverse=True)
    return seen[:MAX_QUERIES]


def suggest_paths(bridge, names: list[str], root: str, *,
                  parent_of_hit: bool = True,
                  limit: int = 5) -> list[Suggestion]:
    """이름들과 어울리는 Wwise 경로를 점수순으로 돌려준다.

    ``parent_of_hit`` 가 True 면 검색에 걸린 오브젝트의 **부모**를 후보로
    삼는다. 오디오는 "이 옆에 넣고 싶다" 이므로 부모가 맞다. 이벤트 폴더를
    찾을 때도 같다.
    """
    words: list[str] = []
    for name in names:
        words.extend(split_words(Path(name).stem))
    if not words:
        return []

    queries = _query_words(words)
    if not queries:
        return []

    lower_words = {w.lower() for w in words}
    candidates: Counter[str] = Counter()

    for word in queries:
        try:
            rows = bridge.search(word, root, limit=PER_QUERY)
        except Exception as exc:  # noqa: BLE001 - 추천은 실패해도 된다
            log.debug("'%s' 검색 실패: %s", word, exc)
            continue
        for row in rows:
            path = row.get("path") or ""
            if not path.startswith(root):
                continue
            target = path.rsplit(SEP, 1)[0] if parent_of_hit else path
            if target and target != root:
                candidates[target] += 1

    if not candidates:
        return []

    scored: list[Suggestion] = []
    for path, hits in candidates.items():
        segment_words = {w.lower() for seg in path.split(SEP)
                         for w in split_words(seg)}
        matched = sorted(lower_words & segment_words)
        if not matched:
            continue
        # 겹치는 단어 수가 주된 근거, 검색에 걸린 횟수는 보조.
        score = len(matched) + min(hits, 5) * 0.1
        scored.append(Suggestion(path=path, score=score,
                                 matched=[m for m in matched]))

    scored.sort(key=lambda s: (-s.score, len(s.path)))
    return scored[:limit]
