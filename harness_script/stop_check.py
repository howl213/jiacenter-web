#!/usr/bin/env python3
"""Stop 훅. 끝내려 할 때 아래 중 하나라도 걸리면 한 번 막고, 이유를 Claude 에게 돌려준다(Claude Code 가 그 이유를 받아 이어서 일한다).

  1) 이번 턴에 src/ 코드를 고쳤는데 그 뒤로 테스트(manage.py test, verify.sh 등)를 돌린 기록이 없거나,
     마지막으로 돌린 테스트가 실패했거나, 그 결과 기록을 찾지 못했다
     — "할 수 있는데 안 한 확인"의 증거라서 기록으로 판정한다(세션 기록의 도구 호출과 그 결과).
  2) 코드가 바뀐 채인데 manage.py check 나 마이그레이션 검사가 실패하거나 시간 안에 끝나지 않는다
  3) 방금 한 마지막 답변에 "완벽하다/문제없다/안전하다" 같은 단정이 있는데 "확인하지 못한 것"이 없다
  4) 점검 자체를 못 했다(입력 JSON 이 깨졌다, 세션 기록을 못 읽었다, git status 가 실패했다, 점검 중 예기치 않은 오류)
     — 이때는 "통과"로 두지 않고 막되, 답에 "점검하지 못했다"고 알리게 한다. 검증했다고 쓰게 두지 않기 위해서다.

되풀이 방지: stop_hook_active 가 켜져 있으면(이미 이 훅 때문에 이어서 일하는 중) 통과시킨다. Claude Code 쪽에도 연속 차단 상한이 있다.
"사용자가 직접 확인해야 하는가"는 스크립트가 알 수 없다 — 그 판단은 CLAUDE.md 2절 3번 줄이 Claude 에게 맡긴다.
3)번은 문장 모양만 보는 거친 검사라 틀릴 수 있다. 전체 테스트는 여기서 돌리지 않는다(harness_script/verify.sh 와 CI 가 한다).

이 훅이 쓰는 입력 필드(확인한 것만): 훅 입력의 transcript_path · stop_hook_active · last_assistant_message,
세션 기록(JSONL)의 assistant tool_use(id, name, input), user tool_result(tool_use_id, is_error).
그 밖의 필드는 확인하지 않았고 쓰지 않는다.

테스트 성공 여부의 근거와 한계: 이 저장소 세션 기록에서 실패한 Bash 결과가 `is_error: true`·`Exit code N` 으로 남은 것을 1건 직접 봤다.
다만 `manage.py test | tail` 처럼 파이프로 종료 코드가 가려지거나 `|| true` 가 붙으면 실패해도 is_error 는 false 로 남아 이 훅은 못 본다.
is_error 가 모든 비정상 종료를 가려낸다고 가정하지 않는다. is_error 가 true/false 로 명시되지 않은 결과는 성공으로 치지 않는다.
세션 기록 파일이 아예 없을 때만(경로 없음·파일 없음) 기록으로 볼 것이 없어 이 검사를 건너뛴다.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_guard import SHELLS, segments, split_heredocs, strip_wrappers  # noqa: E402  (같은 폴더의 모듈)

CLAIM = re.compile(r'완벽|문제\s*없|안전합니다|안전해요|안전하다|허점이?\s*없|걱정\s*없')
NEGATION = re.compile(r'않|아니|못\s|금지|말하지|쓰지|뜻이|라고\s*(말|쓰|적)')
HEDGE = re.compile(r'확인하지\s*못|확인\s*못|미확인|검증하지\s*못|보지\s*못|못\s*봤|안\s*한\s*것')
EDIT_TOOLS = {'Edit', 'Write', 'NotebookEdit'}


def entries(transcript_path):
    for line in Path(transcript_path).read_text(encoding='utf-8').splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def last_assistant_text(transcript_path):
    """세션 기록(JSONL)에서 마지막 assistant 글을 꺼낸다. 형식이 다르면 빈 문자열."""
    text = ''
    for entry in entries(transcript_path):
        if entry.get('type') != 'assistant':
            continue
        content = (entry.get('message') or {}).get('content')
        if isinstance(content, list):
            parts = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
            if parts:
                text = '\n'.join(parts)
    return text


def turn_tool_uses(transcript_path):
    """마지막 사용자 입력 이후에 부른 도구들을 (이름, 입력, 결과) 순서대로 돌려준다.

    결과는 짝이 되는 tool_result 의 is_error 가 true 면 'error', false 면 'ok', 결과가 없거나 is_error 가 명시되지 않았으면 None.
    """
    uses, by_id = [], {}
    for entry in entries(transcript_path):
        content = (entry.get('message') or {}).get('content')
        if entry.get('type') == 'user':
            # 도구 결과(tool_result)만 든 항목은 사용자 입력이 아니다.
            if isinstance(content, str) or (isinstance(content, list) and any(
                    isinstance(b, dict) and b.get('type') == 'text' for b in content)):
                uses, by_id = [], {}
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') in by_id \
                            and isinstance(b.get('is_error'), bool):
                        uses[by_id[b['tool_use_id']]][2] = 'error' if b['is_error'] else 'ok'
        elif entry.get('type') == 'assistant' and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    if b.get('id'):
                        by_id[b['id']] = len(uses)
                    uses.append([b.get('name'), b.get('input') or {}, None])
    return [tuple(u) for u in uses]


def is_test_tokens(toks):
    """단순 명령 하나가 테스트를 실제로 돌리는 것인가. `echo pytest` 처럼 글자만 든 것은 아니다."""
    name, args = os.path.basename(toks[0]), toks[1:]
    if re.fullmatch(r'python[\d.]*', name):
        for k, a in enumerate(args):
            if os.path.basename(a) == 'manage.py':
                return args[k + 1:k + 2] == ['test']
            if a == '-m':
                return args[k + 1:k + 2] in (['unittest'], ['pytest'])
        return False
    if name == 'manage.py':
        return args[:1] == ['test']
    if name in ('pytest', 'py.test'):
        return True
    if name in SHELLS:
        return bool(args) and os.path.basename(args[0]) == 'verify.sh'
    return name == 'verify.sh'


def is_test_command(command):
    segs = segments(split_heredocs(command)[0])
    return any(toks and is_test_tokens(toks) for toks in (strip_wrappers(t)[1] for t, _ in (segs or [])))


def untested_edit(uses, root):
    """이번 턴의 마지막 코드 수정 파일과 그 뒤 테스트의 문제를 돌려준다 — (파일, 이유). 문제없으면 None."""
    last = None
    for i, (name, inp, _) in enumerate(uses):
        path = inp.get('file_path') or inp.get('notebook_path') or ''
        if name in EDIT_TOOLS and path:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
            if rel.startswith('src/'):
                last = (i, rel)
    if last is None:
        return None
    runs = [res for n, inp, res in uses[last[0] + 1:] if n == 'Bash' and is_test_command(str(inp.get('command', '')))]
    if not runs:
        return last[1], '그 뒤로 테스트를 돌린 기록이 없다'
    if runs[-1] == 'error':
        return last[1], '그 뒤 마지막으로 돌린 테스트가 실패했다 (is_error)'
    if runs[-1] is None:
        return last[1], '그 뒤 마지막으로 돌린 테스트의 결과 기록을 찾지 못해 성공을 확인하지 못했다'
    return None


def overclaims(text):
    """단정 문장이 있는데 확인하지 못한 것(헤지)이 하나도 없으면 그 문장들을 돌려준다."""
    if not text or HEDGE.search(text):
        return []
    sentences = re.split(r'(?<=[.!?다요])\s+|\n', text)
    return [s.strip()[:60] for s in sentences if CLAIM.search(s) and not NEGATION.search(s)]


def run(*cmd, timeout=30, cwd=None):
    """(종료 코드, 출력). 시간 안에 안 끝나면 코드는 None, 실행 파일이 없으면 127."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return None, f'{timeout}초 안에 끝나지 않았다'
    except OSError as e:
        return 127, str(e)
    return r.returncode, (r.stdout + r.stderr).strip()


def failed(label, code, out):
    if code is None:
        return f'{label} 시간 초과 ({out})'
    return f'{label} 실패 (종료 코드 {code}): ' + (out.splitlines() or ['출력 없음'])[-1][:120]


def check(data, root):
    """(고칠 수 있는 문제들, 점검 자체를 못 한 이유들)."""
    problems, unverified = [], []
    path = data.get('transcript_path')
    if path is not None and not isinstance(path, str):
        unverified.append('훅 입력의 transcript_path 가 글자가 아니다')
        path = None
    last = data.get('last_assistant_message')
    last = last if isinstance(last, str) else ''
    if path and Path(path).exists():
        try:
            edited = untested_edit(turn_tool_uses(path), root)
            last = last or last_assistant_text(path)   # 종료 시점에는 세션 기록에 아직 없을 수 있어 훅 입력 값을 먼저 쓴다
        except (OSError, UnicodeDecodeError) as e:
            edited = None
            unverified.append(f'세션 기록을 읽지 못해 테스트 기록을 확인하지 못했다 ({type(e).__name__})')
        if edited:
            problems.append(f'이번 턴에 {edited[0]} 를 고쳤는데 {edited[1]}')
    claims = overclaims(last)
    if claims:
        problems.append(f'단정 표현이 있는데 "확인하지 못한 것"이 없다: "{claims[0]}"')
    code, out = run('git', 'status', '--porcelain', cwd=root)
    if code != 0:
        unverified.append(failed('git status', code, out) + ' — 바뀐 파일을 알 수 없어 manage.py check 를 건너뛰었다')
    elif any(l[3:].startswith('src/') for l in out.splitlines()):
        venv_py = Path(root) / '.venv' / 'bin' / 'python'
        py = str(venv_py) if venv_py.exists() else 'python3'
        src = str(Path(root) / 'src')
        code, out = run(py, 'manage.py', 'check', cwd=src)
        if code != 0:
            problems.append(failed('manage.py check', code, out))
        code, out = run(py, 'manage.py', 'makemigrations', '--check', '--dry-run', cwd=src)
        if code is None:
            problems.append(failed('makemigrations 검사', code, out))
        elif code:
            problems.append('모델이 바뀌었는데 마이그레이션 파일이 없다 (makemigrations)')
    return problems, unverified


def emit(problems, unverified):
    parts = []
    if problems:
        parts.append('끝내기 전 점검에 걸렸다: ' + ' / '.join(problems) +
                     '. 할 수 있는 확인이면 지금 하고, 못 하는 것만 이유와 함께 "확인하지 못한 것"에 적어라. '
                     '답의 첫머리에 막힌 이유와 한 조치를 쓴다.')
    if unverified:
        parts.append('끝내기 전 점검을 하지 못했다: ' + ' / '.join(unverified) +
                     '. 점검을 통과했다·검증했다고 쓰지 말고, 점검하지 못했다는 사실을 답의 첫머리에 알려라.')
    if parts:
        print(json.dumps({'decision': 'block', 'reason': ' '.join(parts)}, ensure_ascii=False))


def main():
    try:
        data = json.load(sys.stdin) if not sys.stdin.isatty() else {}
        if not isinstance(data, dict):
            raise ValueError('JSON 객체가 아니다')
    except ValueError as e:
        return emit([], [f'훅 입력(JSON)을 읽지 못했다 ({type(e).__name__})'])
    if data.get('stop_hook_active'):
        return
    root = os.path.abspath(os.environ.get('CLAUDE_PROJECT_DIR') or '.')
    try:
        problems, unverified = check(data, root)
    except Exception as e:   # 점검 코드 자체의 버그. 조용히 통과시키지 않고 점검하지 못했다고 알린다
        problems, unverified = [], [f'점검 중 예기치 않은 오류 ({type(e).__name__}: {str(e)[:100]})']
    emit(problems, unverified)


if __name__ == '__main__':
    main()
