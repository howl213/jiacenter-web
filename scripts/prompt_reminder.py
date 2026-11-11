#!/usr/bin/env python3
"""UserPromptSubmit 훅. 사용자가 질문을 보낼 때마다 작업 규칙 네 줄을 Claude 에게 다시 넣는다.

대화가 길어져 세션 시작 때 읽은 규칙이 흐려지는 것을 줄이려는 것이다. 막지는 못한다 — Claude 가 지킬지는 Claude 몫이다.
무엇이든 실패하면 아무 말도 하지 않는다 — 질문 전달을 막으면 안 된다.
"""
import json
import sys

REMINDER = """[작업 규칙 요약 — CLAUDE.md 기준]
1. 이 일이 목표 ①(main 안전한 껍데기)·②(vuln 팀 실습용) 중 어느 쪽인지 먼저 말한다.
2. 사용자가 질문("맞아?", "이해한 거야?")이나 확인을 요청하면 설명만 하고 멈춘다. 수정은 사용자가 고치라고 한 뒤에 한다.
3. 근거는 이번에 직접 연 코드와 실행 결과다. 문서는 낡았을 수 있으니 코드와 맞는 것만 사실로 쓰고, 다르면 코드대로 일하고 문서가 낡았다고 알린다. 추측으로 채우지 않는다. 보고는 시킨 일의 결과 중심으로 쓰고, "확인하지 못한 것"은 시킨 일 자체에서 못 한 부분만 쓴다(상관없는 기존 미확인은 옮기지 않는다 — 이 항목이 시킨 일의 결과를 바꾸는가? 아니면 쓰지 않는다). 끝났으면 "완료"로 보고한다. "안전하다/문제없다"는 쓰지 않는다.
4. 일이 목표대로 끝나면 커밋까지 한다. 푸시·PR·병합, 폴더·브랜치 만들기는 사용자가 시킬 때만 한다."""


if __name__ == '__main__':
    try:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                                 'additionalContext': REMINDER}}, ensure_ascii=False))
    except Exception:
        sys.exit(0)
