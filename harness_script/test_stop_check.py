"""stop_check.py 의 시험. 실제 세션 기록 모양(assistant → message.content[] 의 text·tool_use,
user → tool_result 의 tool_use_id·is_error)을 흉내 낸다. 실제 테스트·마이그레이션은 돌리지 않고 가짜 manage.py 만 쓴다.

실행: python -m unittest discover -s harness_script
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name('stop_check.py').resolve()
_spec = importlib.util.spec_from_file_location('stop_check', SCRIPT)
stop_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stop_check)


def git_init(tmp):
    subprocess.run(['git', 'init', '-q'], cwd=tmp, check=True)


def hook(tmp, stdin_text, cwd=None):
    """stop_check.py 를 훅처럼 돌려 stdout 을 돌려준다. tmp 가 프로젝트 폴더다."""
    r = subprocess.run(['python3', str(SCRIPT)], input=stdin_text, capture_output=True, text=True, cwd=cwd or tmp,
                       env={'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': tmp})
    return r.stdout


def transcript(tmp, *texts):
    path = Path(tmp) / 't.jsonl'
    lines = [json.dumps({'type': 'user', 'message': {'role': 'user', 'content': '질문'}})]
    for t in texts:
        lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'tool_use', 'name': 'Bash'}, {'type': 'text', 'text': t}]}}))
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


class Overclaim(unittest.TestCase):
    def run_hook(self, *texts):
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            return hook(tmp, json.dumps({'transcript_path': str(transcript(tmp, *texts))}))

    def test_flags_unhedged_absolute_claims(self):
        self.assertIn('단정 표현', self.run_hook('테스트가 통과했고 문제없습니다. 안전합니다.'))

    def test_hedged_report_passes(self):
        self.assertEqual(self.run_hook('테스트 49개 통과. 확인하지 못한 것: 브라우저 화면. 문제없다고는 말할 수 없다.'), '')

    def test_negated_sentences_are_not_claims(self):
        self.assertEqual(self.run_hook('통과가 곧 안전하다는 뜻은 아니다. 안전하다고 말하지 않는다.'), '')

    def test_only_the_last_assistant_message_counts(self):
        self.assertEqual(self.run_hook('완벽합니다.', '테스트 3개 통과. 미확인: HTTPS.'), '')

    def test_missing_transcript_file_is_silent(self):
        # 경로가 없거나 파일이 없으면 기록으로 볼 것이 없다 — 이 경우만 조용히 통과시키는 기존 동작을 유지한다.
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            self.assertEqual(hook(tmp, json.dumps({'transcript_path': '/nonexistent'})), '')
            self.assertEqual(hook(tmp, '{}'), '')

    def test_blocks_with_a_reason_for_claude(self):
        out = json.loads(self.run_hook('테스트가 통과했고 문제없습니다. 안전합니다.'))
        self.assertEqual(out['decision'], 'block')
        self.assertIn('막힌 이유', out['reason'])


def tool(name, result='ok', **inp):
    """result: 'ok'(성공 결과), 'error'(is_error 가 true 인 결과), None(결과 기록 없음)."""
    return {'type': 'tool_use', 'name': name, 'input': inp, '_result': result}


class UntestedEdit(unittest.TestCase):
    """코드를 고쳤는데 그 뒤로 테스트 기록이 없거나 마지막 테스트가 실패했으면 막는다. 세션 기록의 도구 호출과 결과로 판정한다."""

    def run_hook(self, *turn, extra=None):
        """turn: 한 턴에서 assistant 가 부른 도구 블록들(차례대로). 마지막 글은 확인 못 한 것을 적은 보고."""
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            lines = [json.dumps({'type': 'user', 'message': {'role': 'user', 'content': '고쳐 줘'}})]
            for n, block in enumerate(turn):
                block = json.loads(json.dumps(block).replace('ROOT', tmp))
                result = block.pop('_result')
                block['id'] = f'toolu_{n}'
                lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [block]}}))
                if result is not None:
                    lines.append(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [
                        {'type': 'tool_result', 'tool_use_id': f'toolu_{n}', 'is_error': result == 'error',
                         'content': 'FAILED' if result == 'error' else 'ok'}]}}))
            lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
                {'type': 'text', 'text': '완료. 확인하지 못한 것: 없음.'}]}}))
            path = Path(tmp) / 't.jsonl'
            path.write_text('\n'.join(lines), encoding='utf-8')
            return hook(tmp, json.dumps({'transcript_path': str(path), **(extra or {})}))

    EDIT = tool('Edit', file_path='ROOT/src/center/views.py')
    TEST = tool('Bash', command='.venv/bin/python manage.py test')

    def reason(self, *turn, **kw):
        out = self.run_hook(*turn, **kw)
        self.assertNotEqual(out, '', '막혀야 하는데 통과했다')
        return json.loads(out)['reason']

    # -- 정상 동작
    def test_edit_then_test_passes(self):
        self.assertEqual(self.run_hook(self.EDIT, self.TEST), '')

    def test_verify_script_counts_as_a_test(self):
        self.assertEqual(self.run_hook(self.EDIT, tool('Bash', command='bash harness_script/verify.sh')), '')

    def test_real_test_command_forms_count(self):
        for cmd in ['cd src && ../.venv/bin/python manage.py test', '(cd src && ../.venv/bin/python manage.py test center)',
                    'FOO=1 python manage.py test', 'python3 -m unittest discover -s harness_script',
                    'python3 -m pytest -q', 'pytest', './harness_script/verify.sh', './manage.py test']:
            self.assertEqual(self.run_hook(self.EDIT, tool('Bash', command=cmd)), '', cmd)

    def test_edit_outside_code_dirs_is_ignored(self):
        self.assertEqual(self.run_hook(tool('Edit', file_path='ROOT/docs/확인사항.md')), '')

    def test_failed_test_outside_an_edit_turn_is_not_this_hooks_business(self):
        self.assertEqual(self.run_hook(tool('Bash', result='error', command='python manage.py test')), '')

    # -- 차단 동작
    def test_edit_without_test_is_blocked(self):
        out = json.loads(self.run_hook(self.EDIT))
        self.assertEqual(out['decision'], 'block')
        self.assertIn('src/center/views.py', out['reason'])
        self.assertIn('테스트를 돌린 기록이 없다', out['reason'])

    def test_test_before_the_last_edit_does_not_count(self):
        self.assertIn('block', self.run_hook(self.TEST, self.EDIT))

    def test_failed_test_is_blocked(self):
        self.assertIn('마지막으로 돌린 테스트가 실패했다',
                      self.reason(self.EDIT, tool('Bash', result='error', command='python manage.py test')))

    def test_the_last_test_run_decides(self):
        failing = tool('Bash', result='error', command='python manage.py test')
        self.assertEqual(self.run_hook(self.EDIT, failing, self.TEST), '')      # 실패 뒤 고쳐서 통과
        self.assertIn('실패했다', self.reason(self.EDIT, self.TEST, failing))    # 통과 뒤 다시 실패

    # -- 우회 시도: 명령에 테스트라는 글자만 들어 있는 것
    def test_commands_that_only_mention_a_test_are_not_a_test_run(self):
        for cmd in ['echo pytest', 'echo manage.py test', 'grep "manage.py test" README.md',
                    'cat harness_script/verify.sh', 'ls tests/pytest', 'git log --grep=unittest',
                    'python manage.py check', "python3 - <<'EOF'\nprint('manage.py test')\nEOF"]:
            self.assertIn('테스트를 돌린 기록이 없다', self.reason(self.EDIT, tool('Bash', command=cmd)), cmd)

    # -- 예외 상황
    def test_test_without_a_recorded_result_is_not_a_success(self):
        self.assertIn('결과 기록을 찾지 못해',
                      self.reason(self.EDIT, tool('Bash', result=None, command='python manage.py test')))

    def test_only_this_turn_counts(self):
        # 앞 턴에서 고친 것은 새 사용자 입력이 오면 지난 일이다.
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            old = {'type': 'assistant', 'message': {'content': [tool('Edit', file_path=f'{tmp}/src/center/views.py')]}}
            new_prompt = {'type': 'user', 'message': {'content': '다음 질문'}}
            reply = {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '설명만 했다.'}]}}
            path = Path(tmp) / 't.jsonl'
            path.write_text('\n'.join(json.dumps(e) for e in [old, new_prompt, reply]), encoding='utf-8')
            self.assertEqual(hook(tmp, json.dumps({'transcript_path': str(path)})), '')

    def test_already_continuing_because_of_this_hook_passes(self):
        self.assertEqual(self.run_hook(self.EDIT, extra={'stop_hook_active': True}), '')

    def test_uses_last_assistant_message_from_the_hook_input(self):
        out = self.run_hook(self.EDIT, self.TEST, extra={'last_assistant_message': '문제없습니다. 완벽합니다.'})
        self.assertIn('단정 표현', out)

    def test_unreadable_transcript_is_reported_not_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            path = Path(tmp) / 't.jsonl'
            path.write_bytes(b'\xff\xfe\x00 not utf-8')
            reason = json.loads(hook(tmp, json.dumps({'transcript_path': str(path)})))['reason']
        self.assertIn('점검을 하지 못했다', reason)
        self.assertIn('세션 기록', reason)


def project(tmp, check_exit=0, check_msg=''):
    """src/ 가 바뀐 git 저장소. manage.py 는 check 만 지정한 대로 끝나는 가짜다."""
    git_init(tmp)
    (Path(tmp) / 'src').mkdir()
    (Path(tmp) / 'src' / 'manage.py').write_text(
        "import sys\nif sys.argv[1] == 'check':\n"
        f"    sys.stderr.write({check_msg!r})\n    sys.exit({check_exit})\n", encoding='utf-8')


class DjangoCheck(unittest.TestCase):
    def run_hook(self, stdin_text='{}', **kw):
        with tempfile.TemporaryDirectory() as tmp:
            project(tmp, **kw)
            return hook(tmp, stdin_text)

    def test_passing_check_is_silent(self):
        self.assertEqual(self.run_hook(), '')

    def test_failing_check_with_output_is_blocked(self):
        self.assertIn('boom', json.loads(self.run_hook(check_exit=1, check_msg='SystemCheckError: boom'))['reason'])

    def test_failing_check_without_any_output_is_still_blocked(self):
        reason = json.loads(self.run_hook(check_exit=1))['reason']
        self.assertIn('manage.py check 실패', reason)
        self.assertIn('출력 없음', reason)

    def test_active_stop_hook_is_not_checked_again(self):
        self.assertEqual(self.run_hook(json.dumps({'stop_hook_active': True}), check_exit=1), '')

    def test_timeout_is_a_failure(self):
        code, out = stop_check.run(sys.executable, '-c', 'import time; time.sleep(5)', timeout=1)
        self.assertIsNone(code)
        with tempfile.TemporaryDirectory() as tmp:
            project(tmp)

            def fake_run(*cmd, timeout=30, cwd=None):
                return (0, '?? src/') if cmd[:2] == ('git', 'status') else (None, '시간 초과')
            with mock.patch.object(stop_check, 'run', fake_run):
                problems, _ = stop_check.check({}, tmp)
        self.assertTrue(any('시간 초과' in p for p in problems), problems)

    def test_missing_executable_is_a_failure_not_a_crash(self):
        self.assertEqual(stop_check.run('/nonexistent/prog')[0], 127)


class BadInput(unittest.TestCase):
    """입력이 깨졌으면 검증한 척하지 않고 점검하지 못했다고 알리며 막는다."""

    def assert_unverified(self, out):
        data = json.loads(out)
        self.assertEqual(data['decision'], 'block')
        self.assertIn('점검을 하지 못했다', data['reason'])
        self.assertIn('검증했다', data['reason'])   # "검증했다고 쓰지 말라"는 안내

    def test_invalid_json_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            for raw in ['{not json', '', '[]', '"x"', 'null']:
                self.assert_unverified(hook(tmp, raw))

    def test_outside_a_git_repository_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:    # git init 을 하지 않은 폴더
            out = hook(tmp, '{}')
        self.assert_unverified(out)
        self.assertIn('git status', out)

    def test_unexpected_exception_is_reported(self):
        with mock.patch.object(stop_check, 'check', side_effect=RuntimeError('boom')), \
                mock.patch('sys.stdin', io.StringIO('{}')), contextlib.redirect_stdout(io.StringIO()) as out:
            stop_check.main()
        self.assert_unverified(out.getvalue())
        self.assertIn('RuntimeError', out.getvalue())

    def test_non_string_fields_do_not_crash_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            self.assert_unverified(hook(tmp, json.dumps({'transcript_path': 5})))


if __name__ == '__main__':
    unittest.main()
