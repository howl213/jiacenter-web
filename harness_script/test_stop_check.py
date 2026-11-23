"""stop_check.py 의 시험. 실제 세션 기록 모양(assistant → message.content[] 의 text·tool_use,
user → tool_result 의 tool_use_id·is_error·content)을 흉내 낸다. 실제 테스트·마이그레이션은 돌리지 않는다. 훅이 manage.py 를 실행하지 않는 것은 가짜 manage.py 로 확인한다.

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

    def test_old_overclaims_check_is_kept(self):
        self.assertTrue(stop_check.overclaims('완벽합니다.'))
        self.assertEqual(stop_check.overclaims('완벽합니다. 확인하지 못한 것: 브라우저.'), [])   # 기존 층의 전체 HEDGE 면제는 그대로


OK_BODY = 'Ran 3 tests in 0.010s\n\nOK'
FAIL_BODY = 'Ran 3 tests in 0.010s\n\nFAILED (failures=1)'
CLAIM_TEXT = '테스트 3개 통과했습니다.'


def tool(name, result='ok', body=None, **inp):
    """result: 'ok'(성공 결과), 'error'(is_error 가 true 인 결과), None(결과 기록 없음).
    body: 결과 본문. 없으면 result 에 맞는 현실적인 unittest 출력을 쓴다."""
    return {'type': 'tool_use', 'name': name, 'input': inp, '_result': result, '_body': body}


def turn_transcript(tmp, turn, text):
    """한 턴의 세션 기록 파일을 만든다. turn: 도구 블록들(차례대로), text: 마지막 답변. 블록 안의 ROOT 는 tmp 로 바뀐다."""
    lines = [json.dumps({'type': 'user', 'message': {'role': 'user', 'content': '고쳐 줘'}})]
    for n, block in enumerate(turn):
        block = json.loads(json.dumps(block).replace('ROOT', tmp))
        result, body = block.pop('_result'), block.pop('_body')
        block['id'] = f'toolu_{n}'
        lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [block]}}))
        if result is not None:
            content = body if body is not None else (FAIL_BODY if result == 'error' else OK_BODY)
            lines.append(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': f'toolu_{n}', 'is_error': result == 'error', 'content': content}]}}))
    lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}))
    path = Path(tmp) / 't.jsonl'
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


class UntestedEdit(unittest.TestCase):
    """코드를 고쳤고 통과를 주장하는데 그 범위의 검증 성공 증거가 없으면 막는다(#21, D3-1). 테스트를 안 돌린 것만으로는 막지 않는다.
    세션 기록의 도구 호출·결과 본문·종료 상태로 판정한다."""

    def run_hook(self, *turn, extra=None, text='완료. 확인하지 못한 것: 없음.'):
        """turn: 한 턴에서 assistant 가 부른 도구 블록들(차례대로). text: 마지막 답변(기본은 통과 주장이 없는 보고)."""
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            path = turn_transcript(tmp, turn, text)
            return hook(tmp, json.dumps({'transcript_path': str(path), **(extra or {})}))

    EDIT = tool('Edit', file_path='ROOT/src/center/views.py')
    TEST = tool('Bash', command='.venv/bin/python manage.py test')

    def reason(self, *turn, **kw):
        out = self.run_hook(*turn, **kw)
        self.assertNotEqual(out, '', '막혀야 하는데 통과했다')
        return json.loads(out)['reason']

    # -- 정상 동작
    def test_edit_then_passing_test_with_a_claim_passes(self):
        self.assertEqual(self.run_hook(self.EDIT, self.TEST, text=CLAIM_TEXT), '')

    def test_edit_without_test_and_without_a_claim_is_not_blocked(self):
        # #21: 미실행 자체는 차단 사유가 아니다. 근거 없는 주장만 막는다.
        self.assertEqual(self.run_hook(self.EDIT), '')

    def test_unclear_result_without_a_claim_is_not_blocked_but_reported_to_the_user_only(self):
        # D3 판정표: 결과 불명 + 주장 없음 = 안내만. 막지 않고(decision 없음) 모델에게 문맥을 보내지도 않는다(systemMessage 만).
        data = json.loads(self.run_hook(self.EDIT, tool('Bash', command='python manage.py test | tail -3')))
        self.assertEqual(set(data), {'systemMessage'})
        self.assertIn('성공으로 확인하지 못했다', data['systemMessage'])

    def test_project_test_command_forms_count_as_src_evidence(self):
        for cmd in ['cd src && ../.venv/bin/python manage.py test', '(cd src && ../.venv/bin/python manage.py test center)',
                    'FOO=1 python manage.py test', './manage.py test']:
            self.assertEqual(self.run_hook(self.EDIT, tool('Bash', command=cmd), text=CLAIM_TEXT), '', cmd)

    def test_other_scope_or_unknown_scope_runs_are_not_src_evidence(self):
        # 하네스 테스트(#23), 대상을 알 수 없는 pytest, 성공 기준이 없는 verify.sh 는 src 수정의 성공 증거가 아니다.
        for cmd in ['python3 -m unittest discover -s harness_script', 'python3 -m pytest -q', 'pytest',
                    'bash harness_script/verify.sh', './harness_script/verify.sh']:
            self.assertIn('block', self.run_hook(self.EDIT, tool('Bash', command=cmd), text=CLAIM_TEXT), cmd)

    def test_edit_outside_code_dirs_is_ignored(self):
        self.assertEqual(self.run_hook(tool('Edit', file_path='ROOT/docs/확인사항.md'), text=CLAIM_TEXT), '')

    def test_failed_test_outside_an_edit_turn(self):
        failing = tool('Bash', result='error', command='python manage.py test')
        self.assertEqual(self.run_hook(failing), '')    # 편집도 주장도 없으면 이 훅이 상관할 일이 아니다
        self.assertIn('실패', self.reason(failing, text=CLAIM_TEXT))    # 실패한 검증을 두고 통과를 주장하면 막는다

    # -- 차단 동작
    def test_edit_without_test_but_with_a_claim_is_blocked(self):
        out = json.loads(self.run_hook(self.EDIT, text=CLAIM_TEXT))
        self.assertEqual(out['decision'], 'block')
        self.assertIn('src/center/views.py', out['reason'])
        self.assertIn('검증 실행 기록이 없다', out['reason'])

    def test_test_before_the_last_edit_does_not_count(self):
        self.assertIn('block', self.run_hook(self.TEST, self.EDIT, text=CLAIM_TEXT))

    def test_failed_test_with_a_claim_is_blocked(self):
        self.assertIn('마지막 검증이 실패했다',
                      self.reason(self.EDIT, tool('Bash', result='error', command='python manage.py test'), text=CLAIM_TEXT))

    def test_the_last_test_run_decides(self):
        failing = tool('Bash', result='error', command='python manage.py test')
        self.assertEqual(self.run_hook(self.EDIT, failing, self.TEST, text=CLAIM_TEXT), '')      # 실패 뒤 고쳐서 통과
        self.assertIn('실패했다', self.reason(self.EDIT, self.TEST, failing, text=CLAIM_TEXT))    # 통과 뒤 다시 실패

    # -- 우회 시도: 명령에 테스트라는 글자만 들어 있는 것
    def test_commands_that_only_mention_a_test_are_not_a_test_run(self):
        for cmd in ['echo pytest', 'echo manage.py test', 'grep "manage.py test" README.md',
                    'cat harness_script/verify.sh', 'ls tests/pytest', 'git log --grep=unittest',
                    'python manage.py shell', "python3 - <<'EOF'\nprint('manage.py test')\nEOF"]:
            self.assertIn('검증 실행 기록이 없다', self.reason(self.EDIT, tool('Bash', command=cmd), text=CLAIM_TEXT), cmd)

    # -- 예외 상황
    def test_test_without_a_recorded_result_is_not_a_success(self):
        self.assertIn('성공으로 확인하지 못했다',
                      self.reason(self.EDIT, tool('Bash', result=None, command='python manage.py test'), text=CLAIM_TEXT))

    def test_piped_test_is_not_a_success_even_if_the_body_looks_fine(self):
        self.assertIn('성공으로 확인하지 못했다',
                      self.reason(self.EDIT, tool('Bash', command='python manage.py test | tail -3'), text=CLAIM_TEXT))

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

    def test_already_continuing_is_rechecked_and_not_blocked_again(self):
        # 예전에는 stop_hook_active 면 검사 없이 통과했다. 이제는 다시 점검하고, 문제가 남아도 두 번째로 막지 않는다(D3-6).
        data = json.loads(self.run_hook(self.EDIT, text=CLAIM_TEXT, extra={'stop_hook_active': True}))
        self.assertNotIn('decision', data)
        self.assertIn('검증 실행 기록이 없다', data['systemMessage'])

    def test_uses_last_assistant_message_from_the_hook_input(self):
        out = self.run_hook(self.EDIT, self.TEST, extra={'last_assistant_message': '문제없습니다. 완벽합니다.'})
        self.assertIn('단정 표현', out)

    def test_claim_in_the_hook_input_message_is_judged(self):
        out = self.run_hook(self.EDIT, extra={'last_assistant_message': CLAIM_TEXT})
        self.assertIn('검증 실행 기록이 없다', out)

    def test_unreadable_transcript_is_reported_not_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            path = Path(tmp) / 't.jsonl'
            path.write_bytes(b'\xff\xfe\x00 not utf-8')
            reason = json.loads(hook(tmp, json.dumps({'transcript_path': str(path)})))['reason']
        self.assertIn('점검을 하지 못했다', reason)
        self.assertIn('세션 기록', reason)


class CheckWiring(unittest.TestCase):
    """check() 가 새 증거 판정에 연결된 모양: 반환은 그대로 2개, 경고는 선택 인자로, 판정부 예외는 삼키지 않는다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        git_init(self.tmp.name)

    def transcript(self, text, *turn):
        return turn_transcript(self.tmp.name, turn, text)

    def test_notices_are_filled_in_the_passed_list_and_return_shape_is_unchanged(self):
        path = self.transcript('완료.', UntestedEdit.EDIT, tool('Bash', command='python manage.py test | tail -3'))
        notices = []
        result = stop_check.check({'transcript_path': str(path)}, self.tmp.name, notices=notices)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], [])
        self.assertEqual(len(notices), 1)

    def test_calling_without_notices_still_works(self):
        self.assertEqual(stop_check.check({}, self.tmp.name), ([], []))

    def test_blocking_problem_is_not_a_notice(self):
        path = self.transcript(CLAIM_TEXT, UntestedEdit.EDIT)
        notices = []
        problems, _ = stop_check.check({'transcript_path': str(path)}, self.tmp.name, notices=notices)
        self.assertEqual(len(problems), 1)
        self.assertEqual(notices, [])

    def test_judge_exception_is_not_swallowed_and_main_reports_it(self):
        path = self.transcript(CLAIM_TEXT, UntestedEdit.EDIT)
        with mock.patch.object(stop_check, 'judge_evidence', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                stop_check.check({'transcript_path': str(path)}, self.tmp.name)
            with mock.patch('sys.stdin', io.StringIO(json.dumps({'transcript_path': str(path)}))), \
                    mock.patch.dict('os.environ', {'CLAUDE_PROJECT_DIR': self.tmp.name}), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                stop_check.main()
        data = json.loads(out.getvalue())
        self.assertEqual(data['decision'], 'block')
        self.assertIn('RuntimeError', data['reason'])
        self.assertIn('점검을 하지 못했다', data['reason'])


class TurnToolUses(unittest.TestCase):
    def uses(self, *entries):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 't.jsonl'
            path.write_text('\n'.join(json.dumps(e) for e in entries), encoding='utf-8')
            return stop_check.turn_tool_uses(str(path))

    @staticmethod
    def call(id_, command):
        return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': id_, 'name': 'Bash', 'input': {'command': command}}]}}

    @staticmethod
    def result(id_, content, is_error=False):
        return {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': id_, 'is_error': is_error, 'content': content}]}}

    PROMPT = {'type': 'user', 'message': {'content': '질문'}}

    def test_keeps_status_and_body_for_string_and_block_list_content(self):
        uses = self.uses(self.PROMPT,
                         self.call('a', 'x'), self.result('a', OK_BODY),
                         self.call('b', 'y'), self.result('b', [{'type': 'text', 'text': 'Ran 1 test in 0.1s'}, {'type': 'text', 'text': 'OK'}], True),
                         self.call('c', 'z'))
        self.assertEqual(uses[0], ('Bash', {'command': 'x'}, 'ok', OK_BODY))
        self.assertEqual(uses[1], ('Bash', {'command': 'y'}, 'error', 'Ran 1 test in 0.1s\nOK'))
        self.assertEqual(uses[2], ('Bash', {'command': 'z'}, None, ''))   # 결과 기록이 없으면 상태 없음·본문 없음

    # 실제 세션 기록(Claude Code 2.1.329)의 Stop 훅 피드백: type user, isMeta true, content 가 "Stop hook feedback:\n..." 문자열
    FEEDBACK = {'type': 'user', 'isMeta': True, 'message': {'role': 'user', 'content': 'Stop hook feedback:\n끝내기 전 점검에 걸렸다: x'}}

    def test_normal_user_message_resets_earlier_tool_uses(self):
        self.assertEqual(self.uses(self.PROMPT, self.call('a', 'x'), self.result('a', OK_BODY), {'type': 'user', 'message': {'content': '새 질문'}}), [])

    def test_stop_hook_feedback_keeps_earlier_tool_uses(self):
        uses = self.uses(self.PROMPT, self.call('a', 'x'), self.result('a', OK_BODY), self.FEEDBACK, self.call('b', 'y'))
        self.assertEqual([u[1]['command'] for u in uses], ['x', 'y'])
        self.assertEqual(uses[0][2], 'ok')

    def test_feedback_lookalikes_still_reset(self):
        # isMeta 가 아니거나 다른 글로 시작하면 일반 사용자 입력이다.
        for entry in ({'type': 'user', 'message': {'content': 'Stop hook feedback:\nx'}},
                      {'type': 'user', 'isMeta': True, 'message': {'content': '다른 메타'}}):
            self.assertEqual(self.uses(self.PROMPT, self.call('a', 'x'), entry), [])

    def test_edit_scopes_and_verdict_survive_stop_hook_feedback(self):
        edit_use = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'e', 'name': 'Edit', 'input': {'file_path': '/r/src/center/views.py'}}]}}
        uses = self.uses(self.PROMPT, edit_use, self.FEEDBACK)
        self.assertEqual(list(stop_check.edit_scopes(uses, '/r')), ['src'])
        problems, _ = stop_check.judge_evidence(uses, '/r', stop_check.pass_claims('테스트 3개 통과했습니다.'))
        self.assertEqual(len(problems), 1)
        self.assertIn('검증 실행 기록이 없다', problems[0])

    def test_result_without_explicit_is_error_keeps_body_but_no_status(self):
        entry = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'a', 'content': OK_BODY}]}}
        uses = self.uses(self.PROMPT, self.call('a', 'x'), entry)
        self.assertEqual((uses[0][2], uses[0][3]), (None, OK_BODY))

    def test_body_is_cut_to_the_tail(self):
        uses = self.uses(self.PROMPT, self.call('a', 'x'), self.result('a', 'A' * 9000 + 'END'))
        self.assertEqual(len(uses[0][3]), stop_check.TAIL + 1)   # 하나 더 보관해 parse_result 가 잘림을 안다
        self.assertTrue(uses[0][3].endswith('END'))

    def test_only_this_turn_and_unknown_content_shapes(self):
        uses = self.uses(self.call('old', 'x'), self.PROMPT, self.call('a', 'y'), self.result('a', {'weird': 1}))
        self.assertEqual(uses, [('Bash', {'command': 'y'}, 'ok', '')])


class ClassifyCommand(unittest.TestCase):
    def c(self, cmd):
        r = stop_check.classify_command(cmd)
        return r.kind, set(r.scopes), r.reliable

    def test_project_tests_are_src_scope(self):
        self.assertEqual(self.c('cd src && ../.venv/bin/python manage.py test center'), ('test', {'src'}, True))
        self.assertEqual(self.c('FOO=1 python manage.py test'), ('test', {'src'}, True))
        self.assertEqual(self.c('./manage.py test'), ('test', {'src'}, True))

    def test_harness_tests_are_harness_scope(self):
        self.assertEqual(self.c('python3 -m unittest discover -s harness_script'), ('test', {'harness'}, True))
        self.assertEqual(self.c('python3 -m unittest discover -sharness_script'), ('test', {'harness'}, True))
        self.assertEqual(self.c('python3 -m unittest harness_script.test_session_brief -v'), ('test', {'harness'}, True))
        self.assertEqual(self.c('pytest harness_script/test_x.py -k foo'), ('test', {'harness'}, True))
        self.assertEqual(self.c('pytest src/center'), ('test', {'src'}, True))

    def test_tests_without_a_known_target_have_no_scope(self):
        for cmd in ['python3 -m pytest -q', 'pytest', 'python3 -m unittest', 'python3 -m unittest discover', 'py.test -x']:
            self.assertEqual(self.c(cmd), ('test', set(), True), cmd)

    def test_one_line_with_two_test_commands_covers_both_scopes(self):
        self.assertEqual(self.c('python manage.py test && python3 -m unittest discover -s harness_script'),
                         ('test', {'src', 'harness'}, True))

    def test_verify_static_and_django_kinds(self):
        self.assertEqual(self.c('bash harness_script/verify.sh'), ('verify', {'src', 'harness'}, True))
        self.assertEqual(self.c('./harness_script/verify.sh'), ('verify', {'src', 'harness'}, True))
        self.assertEqual(self.c('./harness_script/check_leaks.sh --all'), ('static', set(), True))
        self.assertEqual(self.c('python3 harness_script/check_track.py tree'), ('static', set(), True))
        self.assertEqual(self.c('bash harness_script/check_leaks.sh --staged'), ('static', set(), True))
        self.assertEqual(self.c('cd src && ../.venv/bin/python manage.py check'), ('django', set(), True))
        self.assertEqual(self.c('python manage.py makemigrations --check --dry-run'), ('django', set(), True))

    def test_different_kinds_on_one_line_are_mixed(self):
        self.assertEqual(self.c('python manage.py check && python manage.py test'), ('mixed', {'src'}, True))

    def test_commands_that_only_mention_a_check_are_not_checks(self):
        for cmd in ['echo pytest', 'grep "manage.py test" README.md', 'cat harness_script/verify.sh', 'ls',
                    'git log --grep=unittest', 'python manage.py shell', "python3 - <<'EOF'\nprint('manage.py test')\nEOF"]:
            self.assertIsNone(self.c(cmd)[0], cmd)

    def test_stderr_redirect_ampersand_is_not_an_operator(self):
        for cmd in ['python manage.py test 2>&1', 'python manage.py test 2>/dev/null', 'python manage.py test &> /tmp/out',
                    'python manage.py test > /tmp/out 2>&1']:
            self.assertEqual(self.c(cmd), ('test', {'src'}, True), cmd)

    def test_and_chain_is_reliable_but_other_operators_are_not(self):
        self.assertTrue(self.c('cd src && python manage.py test')[2])
        self.assertTrue(self.c('(cd src && python manage.py test center)')[2])
        for cmd in ['python manage.py test | tail -5', 'python manage.py test 2>&1 | tail -5', 'python manage.py test; echo done',
                    'python manage.py test || true', 'python manage.py test &', 'python manage.py test & echo x']:
            self.assertEqual(self.c(cmd), ('test', {'src'}, False), cmd)

    def test_non_string_and_unparsable_input_is_not_a_check(self):
        self.assertIsNone(self.c(None)[0])
        self.assertIsNone(self.c('')[0])
        self.assertIsNone(self.c("echo 'unterminated")[0])


class ParseResult(unittest.TestCase):
    def p(self, body, status='ok', kind='test', reliable=True):
        return stop_check.parse_result(kind, body, status, reliable)

    def test_success_needs_a_positive_summary(self):
        self.assertEqual(self.p(OK_BODY), 'success')
        self.assertEqual(self.p('Ran 7 tests in 2.199s\n\nOK (skipped=2)'), 'success')

    def test_missing_or_empty_summary_is_unclear(self):
        for body in ['ok', '', None, ['x'], 'Ran 0 tests in 0.000s\n\nNO TESTS RAN', 'Ran 0 tests in 0.000s\n\nOK',
                     'Ran 3 tests in 0.010s\n']:
            self.assertEqual(self.p(body), 'unclear', repr(body))

    def test_is_error_alone_is_never_a_success(self):
        self.assertEqual(self.p('ok', 'ok'), 'unclear')
        self.assertEqual(self.p(OK_BODY, None), 'unclear')

    def test_unreliable_command_is_never_a_success(self):
        self.assertEqual(self.p(OK_BODY, 'ok', reliable=False), 'unclear')

    def test_failure_markers_win_over_success_markers(self):
        for body in [FAIL_BODY, 'FAIL: test_x (m.C.test_x)\nRan 3 tests in 1s\n\nOK', 'ERROR: test_x (m.C.test_x)\n' + OK_BODY,
                     'Traceback (most recent call last):\n  ...\n' + OK_BODY, 'Exit code 1\n' + OK_BODY]:
            self.assertEqual(self.p(body), 'failure', body)
        self.assertEqual(self.p(FAIL_BODY, 'ok', reliable=False), 'failure')   # 실패는 본문이 보이면 신뢰하지 못해도 실패다

    def test_error_status_is_a_failure_only_for_a_reliable_command(self):
        self.assertEqual(self.p('', 'error'), 'failure')
        self.assertEqual(self.p('', 'error', reliable=False), 'unclear')   # 파이프 뒤의 종료 코드는 다른 명령의 것일 수 있다

    def test_every_summary_must_succeed(self):
        two_ok = 'Ran 3 tests in 1s\n\nOK\nRan 2 tests in 1s\n\nOK'
        self.assertEqual(self.p(two_ok), 'success')
        self.assertEqual(self.p('Ran 3 tests in 1s\n\nOK\nRan 2 tests in 1s\n\nFAILED (errors=1)'), 'failure')
        self.assertEqual(self.p('Ran 3 tests in 1s\n\nOK\nRan 2 tests in 1s\n'), 'unclear')

    def test_only_the_tail_of_the_body_is_read(self):
        self.assertEqual(self.p(OK_BODY + '\n' + 'x' * 5000), 'unclear')     # 요약이 끝 4KB 밖이면 못 본다

    def test_truncated_body_is_never_a_success(self):
        T = stop_check.TAIL
        self.assertEqual(self.p('x' * (T - len(OK_BODY) - 1) + '\n' + OK_BODY), 'success')       # 정확히 TAIL 글자: 안 잘림
        self.assertEqual(self.p('x' * (T + 1 - len(OK_BODY) - 1) + '\n' + OK_BODY), 'unclear')   # TAIL+1: 잘림
        self.assertEqual(self.p('x' * 5000 + '\n' + OK_BODY), 'unclear')
        self.assertEqual(self.p('x' * 5000 + '\n' + FAIL_BODY), 'failure')                         # 보이는 끝의 실패 표지
        self.assertEqual(self.p('x' * 5000 + '\n' + OK_BODY, 'error'), 'failure')                  # 신뢰 가능한 명령의 오류 상태
        self.assertEqual(self.p('x' * 5000 + '\n' + OK_BODY, 'error', reliable=False), 'unclear')
        self.assertEqual(self.p('FAILED (failures=1)\n' + 'x' * 5000 + '\n' + OK_BODY), 'unclear')   # 잘려 나간 앞쪽 실패 표지는 못 본다(알려진 한계)

    def test_static_django_and_mixed_checks_have_no_success_criterion_yet(self):
        for kind in ['static', 'django', 'mixed']:
            self.assertEqual(self.p(OK_BODY, kind=kind), 'unclear', kind)
            self.assertEqual(self.p(FAIL_BODY, 'error', kind=kind), 'unclear', kind)

    def test_verify_script_is_never_a_success_but_failures_are_seen(self):
        self.assertEqual(self.p('통과  Django 테스트\n통과  하네스 스크립트 테스트\n---\n전부 통과.', kind='verify'), 'unclear')
        self.assertEqual(self.p('통과  Django 테스트\n실패  개인정보·금지 파일 검사\n---\n실패한 항목이 있다.', kind='verify'), 'failure')


class PassClaims(unittest.TestCase):
    def kinds(self, text):
        return [k for k, _ in stop_check.pass_claims(text)]

    def test_the_three_d2_patterns_are_detected(self):
        self.assertEqual(self.kinds('테스트 49개 통과'), ['test'])                       # 숫자 + 개/건 + 통과
        self.assertEqual(self.kinds('Django 시험 3건 통과했다.'), ['test'])
        self.assertEqual(self.kinds('테스트가 통과했습니다.'), ['test'])                    # 시험·검사 문맥 + 통과했다
        self.assertEqual(self.kinds('모두 통과했다.'), ['test'])                          # 모두 통과

    def test_claim_type_follows_the_context_word(self):
        self.assertEqual(self.kinds('검사 통과했습니다.'), ['check'])
        self.assertEqual(self.kinds('점검 12건 통과.'), ['check'])
        self.assertEqual(self.kinds('테스트와 검사가 통과했습니다.'), ['test'])
        self.assertEqual(self.kinds('12개 통과'), ['test'])                              # 유형이 없으면 테스트가 기본

    def test_returns_the_sentence_cut_to_60_chars(self):
        (kind, sentence), = stop_check.pass_claims('테스트 3개 통과 ' + '가' * 100)
        self.assertEqual(len(sentence), 60)

    def test_work_completion_is_not_a_verification_claim(self):
        self.assertEqual(stop_check.pass_claims('수정 완료. 파일 작성을 끝냈습니다. 반영했습니다.'), [])

    def test_code_quote_and_blockquote_contexts_are_not_claims(self):
        for text in ['```\n테스트 3개 통과\n```', '`테스트 49개 통과`라고 출력된다.', '"테스트 3개 통과"라는 문구를 확인했다.',
                     '> 테스트 3개 통과', '「테스트 3개 통과」 라고 적혀 있다.']:
            self.assertEqual(stop_check.pass_claims(text), [], text)

    def test_question_condition_plan_negation_and_hedge_are_not_claims(self):
        for text in ['테스트가 통과했는지 확인할까요?', '테스트를 실행하면 3개 통과할 것이다.', '테스트 5개 통과 여부는 확인 예정이다.',
                     '테스트 3개가 통과하지 않았다.', '테스트 3개 통과는 미확인이다.', '모두 통과할 때까지 반복하세요.']:
            self.assertEqual(stop_check.pass_claims(text), [], text)

    def test_relay_of_someone_elses_result_and_hook_wording_are_not_claims(self):
        for text in ['사용자가 테스트 3개 통과했다고 알려 주셨다.', '이 훅은 모두 통과 처리한다.']:
            self.assertEqual(stop_check.pass_claims(text), [], text)

    def test_failure_and_pass_in_the_same_sentence_is_an_honest_partial_report(self):
        self.assertEqual(stop_check.pass_claims('테스트 1개 실패, 4개 통과.'), [])

    def test_split_sentences_are_not_auto_exempted(self):
        self.assertEqual(self.kinds('3개 실패. 47개 통과.'), ['test'])
        self.assertEqual(self.kinds('실패 0건, 5개 통과.'), ['test'])     # 실패가 없다는 말은 부분 보고가 아니다

    def test_a_hedge_elsewhere_does_not_exempt_the_whole_answer(self):
        self.assertEqual(self.kinds('확인하지 못한 것: 브라우저. 테스트 12개 통과했다.'), ['test'])

    def test_table_rows_are_judged_like_sentences(self):
        self.assertEqual(self.kinds('| Django 테스트 | 49개 통과 |'), ['test'])

    def test_empty_and_non_string_input(self):
        for text in ['', None, 5]:
            self.assertEqual(stop_check.pass_claims(text), [])


ROOT = '/proj'


def edit(path, name='Edit'):
    return (name, {'file_path': f'{ROOT}/{path}'}, 'ok', '')


def bash(command, body=OK_BODY, status='ok'):
    return ('Bash', {'command': command}, status, body)


class EditScopes(unittest.TestCase):
    def scopes(self, *uses):
        return stop_check.edit_scopes(list(uses), ROOT)

    def test_paths_are_split_into_scopes_with_the_last_edit_position(self):
        got = self.scopes(edit('src/a.py'), edit('harness_script/x.py'), edit('src/b.py', 'Write'), edit('.claude/settings.json'))
        self.assertEqual(got, {'src': (2, 'src/b.py'), 'harness': (3, '.claude/settings.json')})

    def test_documents_and_other_claude_files_are_no_scope(self):
        self.assertEqual(self.scopes(edit('docs/a.md'), edit('README.md'), edit('.claude/settings.local.json'),
                                     edit('.claude/commands/verify.md'), edit('CLAUDE.md')), {})

    def test_notebook_path_and_odd_inputs(self):
        self.assertEqual(self.scopes(('NotebookEdit', {'notebook_path': f'{ROOT}/src/n.ipynb'}, 'ok', '')), {'src': (0, 'src/n.ipynb')})
        self.assertEqual(self.scopes(('Edit', {'file_path': 5}, 'ok', ''), ('Edit', {}, 'ok', ''), bash('ls')), {})

    def test_paths_outside_the_root_are_ignored(self):
        self.assertEqual(self.scopes(('Edit', {'file_path': '/elsewhere/src/a.py'}, 'ok', '')), {})


class JudgeEvidence(unittest.TestCase):
    """설계 보고서 D3 증거 판정표의 11행. (관련 편집, 해당 범위 검증, 결과, 성공 주장) → 처리."""
    CLAIM = [('test', '테스트 3개 통과')]
    TEST = bash('python manage.py test')

    def judge(self, uses, claims):
        return stop_check.judge_evidence(uses, ROOT, claims)

    def assert_blocked(self, uses, claims, text):
        problems, notices = self.judge(uses, claims)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(text, problems[0])
        self.assertEqual(notices, [])

    # 1~2. 편집 있음, 검증 없음
    def test_row1_edit_no_run_no_claim_is_not_blocked(self):
        self.assertEqual(self.judge([edit('src/a.py')], []), ([], []))

    def test_row2_edit_no_run_with_claim_is_blocked(self):
        self.assert_blocked([edit('src/a.py')], self.CLAIM, '검증 실행 기록이 없다')

    # 3~6. 편집 있음, 검증 있음
    def test_row3_edit_success_claim_passes(self):
        self.assertEqual(self.judge([edit('src/a.py'), self.TEST], self.CLAIM), ([], []))

    def test_row4_edit_failure_claim_is_blocked(self):
        self.assert_blocked([edit('src/a.py'), bash('python manage.py test', FAIL_BODY, 'error')], self.CLAIM, '마지막 검증이 실패했다')

    def test_row5_edit_unclear_claim_is_blocked(self):
        self.assert_blocked([edit('src/a.py'), bash('python manage.py test | tail -3')], self.CLAIM, '성공으로 확인하지 못했다')

    def test_row6_edit_unclear_no_claim_only_warns(self):
        problems, notices = self.judge([edit('src/a.py'), bash('python manage.py test | tail -3')], [])
        self.assertEqual(problems, [])
        self.assertEqual(len(notices), 1)

    # 7~10. 편집 없음
    def test_row7_no_edit_no_run_claim_is_a_known_miss(self):
        self.assertEqual(self.judge([], self.CLAIM), ([], []))
        self.assertEqual(self.judge([bash('ls')], self.CLAIM), ([], []))

    def test_row8_no_edit_success_claim_is_allowed_as_a_report(self):
        self.assertEqual(self.judge([self.TEST], self.CLAIM), ([], []))

    def test_row9_no_edit_failure_claim_is_blocked(self):
        problems, _ = self.judge([bash('python manage.py test', FAIL_BODY, 'error')], self.CLAIM)
        self.assertEqual(len(problems), 1)
        self.assertIn('실패', problems[0])

    def test_row10_no_edit_unclear_claim_only_notifies(self):
        problems, notices = self.judge([bash('python manage.py test | tail -3')], self.CLAIM)
        self.assertEqual(problems, [])
        self.assertEqual(len(notices), 1)

    # 11. 다른 범위
    def test_row11_other_scope_tests_are_not_evidence(self):
        self.assert_blocked([edit('src/a.py'), bash('python3 -m unittest discover -s harness_script')], self.CLAIM, '프로젝트(src/)')
        self.assert_blocked([edit('harness_script/x.py'), self.TEST], self.CLAIM, '하네스')

    # 범위 독립성
    def test_each_scope_is_judged_on_its_own(self):
        problems, _ = self.judge([edit('src/a.py'), edit('harness_script/x.py'), self.TEST], self.CLAIM)
        self.assertEqual(len(problems), 1)
        self.assertIn('harness_script/x.py', problems[0])

    def test_one_chained_command_can_cover_both_scopes(self):
        both = bash('python manage.py test && python3 -m unittest discover -s harness_script',
                    'Ran 3 tests in 1s\n\nOK\nRan 2 tests in 1s\n\nOK')
        self.assertEqual(self.judge([edit('src/a.py'), edit('harness_script/x.py'), both], self.CLAIM), ([], []))

    def test_settings_json_is_harness_scope(self):
        self.assert_blocked([edit('.claude/settings.json')], self.CLAIM, '하네스')
        harness = bash('python3 -m unittest discover -s harness_script')
        self.assertEqual(self.judge([edit('.claude/settings.json'), harness], self.CLAIM), ([], []))

    def test_documents_only_never_need_test_evidence(self):
        self.assertEqual(self.judge([edit('docs/a.md'), edit('CLAUDE.md')], self.CLAIM), ([], []))

    # 순서
    def test_edit_after_the_test_needs_a_new_test(self):
        self.assert_blocked([edit('src/a.py'), self.TEST, edit('src/b.py')], self.CLAIM, '검증 실행 기록이 없다')

    def test_last_relevant_run_decides(self):
        failing = bash('python manage.py test', FAIL_BODY, 'error')
        self.assertEqual(self.judge([edit('src/a.py'), failing, self.TEST], self.CLAIM), ([], []))
        self.assert_blocked([edit('src/a.py'), self.TEST, failing], self.CLAIM, '실패')

    # 범위 불명·성공 기준 없는 검증
    def test_unknown_scope_test_is_unclear_not_success(self):
        self.assert_blocked([edit('src/a.py'), bash('python3 -m pytest -q')], self.CLAIM, '성공으로 확인하지 못했다')
        problems, notices = self.judge([edit('src/a.py'), bash('python3 -m pytest -q')], [])
        self.assertEqual((problems, len(notices)), ([], 1))

    def test_verify_script_has_no_success_criterion_yet(self):
        verify = bash('bash harness_script/verify.sh', '통과  Django 테스트\n통과  하네스 스크립트 테스트\n---\n전부 통과.')
        self.assert_blocked([edit('src/a.py'), verify], self.CLAIM, '성공으로 확인하지 못했다')

    def test_check_claims_are_matched_with_checks_not_tests(self):
        check_claim = [('check', '검사 통과했습니다')]
        static = bash('./harness_script/check_leaks.sh --all', '')
        self.assert_blocked([edit('src/a.py'), self.TEST], check_claim, '검증 실행 기록이 없다')   # 테스트는 검사 주장의 증거가 아니다
        self.assert_blocked([edit('src/a.py'), static], check_claim, '성공으로 확인하지 못했다')   # 정적 검사는 성공 기준이 없어 불명
        self.assert_blocked([edit('src/a.py'), static], self.CLAIM, '검증 실행 기록이 없다')      # 검사는 테스트 주장의 증거가 아니다
        problems, notices = self.judge([static], check_claim)
        self.assertEqual((problems, len(notices)), ([], 1))


def project(tmp, check_exit=0):
    """src/ 가 바뀐 git 저장소. manage.py 는 실행되면 ran 표시 파일을 남기고 check 가 지정한 대로 끝나는 가짜다."""
    git_init(tmp)
    (Path(tmp) / 'src').mkdir()
    (Path(tmp) / 'src' / 'manage.py').write_text(
        "import sys, pathlib\npathlib.Path(__file__).with_name('ran').write_text('x')\n"
        f"sys.stderr.write('SystemCheckError: boom')\nsys.exit({check_exit})\n", encoding='utf-8')


class NoDirectDjangoRun(unittest.TestCase):
    """#19·결정 6 ③⑤: 훅은 manage.py check·makemigrations 같은 검사 명령을 직접 실행하지 않는다. 검사는 Claude 가 승인받아 돌린다."""

    def run_hook(self, stdin_text='{}'):
        with tempfile.TemporaryDirectory() as tmp:
            project(tmp, check_exit=1)   # 실행됐다면 check 실패로 막혔을 것이다
            out = hook(tmp, stdin_text)
            return out, (Path(tmp) / 'src' / 'ran').exists()

    def test_src_changed_with_failing_manage_py_is_not_run_and_not_blocked(self):
        out, ran = self.run_hook()
        self.assertEqual(out, '')
        self.assertFalse(ran)

    def test_same_in_the_recheck(self):
        out, ran = self.run_hook(json.dumps({'stop_hook_active': True}))
        self.assertEqual(out, '')
        self.assertFalse(ran)

    def test_the_hook_only_runs_read_only_git_status(self):
        calls = []

        def fake_run(*cmd, timeout=30, cwd=None):
            calls.append(cmd)
            return 0, ' M src/a.py'
        with mock.patch.object(stop_check, 'run', fake_run):
            stop_check.check({}, '/x')
        self.assertEqual(calls, [('git', 'status', '--porcelain')])

    def test_timeout_is_reported_by_run(self):
        code, out = stop_check.run(sys.executable, '-c', 'import time; time.sleep(5)', timeout=1)
        self.assertIsNone(code)

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


class StopRecheck(unittest.TestCase):
    """#24·D3-6: stop_hook_active 면 같은 점검을 다시 하고, 해결됐으면 통과, 남았거나 새 문제여도 두 번째로 막지 않고 두 메시지로 알린다."""
    EDIT, TEST = UntestedEdit.EDIT, UntestedEdit.TEST

    def run_hook(self, turn, text, active):
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            path = turn_transcript(tmp, turn, text)
            return hook(tmp, json.dumps({'transcript_path': str(path), 'stop_hook_active': active}))

    def only_json(self, out):
        """stdout 이 JSON 문서 하나뿐인지(디버그 글자가 섞이지 않았는지) 확인하고 풀어서 돌려준다."""
        data = json.loads(out)   # 앞뒤에 다른 글자가 있으면 여기서 실패한다
        self.assertEqual(out.strip().count('\n'), 0)
        return data

    def main_output(self, stdin_data, **patches):
        with mock.patch.object(stop_check, 'check', **patches), mock.patch('sys.stdin', io.StringIO(json.dumps(stdin_data))), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            stop_check.main()
        return out.getvalue()

    # 1~2. 처음(active 거짓)
    def test_first_stop_with_a_problem_blocks_once(self):
        data = self.only_json(self.run_hook([self.EDIT], CLAIM_TEXT, False))
        self.assertEqual(data['decision'], 'block')
        self.assertIn('검증 실행 기록이 없다', data['reason'])
        self.assertNotIn('systemMessage', data)
        self.assertNotIn('hookSpecificOutput', data)

    def test_first_stop_without_a_problem_passes_silently(self):
        self.assertEqual(self.run_hook([self.EDIT, self.TEST], CLAIM_TEXT, False), '')

    # 3. 재검사에서 해결됨
    def test_recheck_with_the_problem_resolved_passes_silently(self):
        self.assertEqual(self.run_hook([self.EDIT, self.TEST], CLAIM_TEXT, True), '')

    # 4~5. 재검사에서 문제가 남음 / 새 문제
    def test_recheck_with_the_same_problem_does_not_block_but_reports(self):
        data = self.only_json(self.run_hook([self.EDIT], CLAIM_TEXT, True))
        self.assertEqual(set(data), {'systemMessage'})   # decision·reason·additionalContext 가 없다

    def test_recheck_with_a_new_problem_does_not_block_but_reports(self):
        # 이전 차단 사유를 저장하지 않으므로 새 문제도 같은 방식으로 알린다(D3-6).
        data = self.only_json(self.run_hook([], '문제없습니다. 완벽합니다.', True))
        self.assertEqual(set(data), {'systemMessage'})
        self.assertIn('단정 표현', data['systemMessage'])

    # 6~8. 출력 내용
    def test_recheck_output_has_only_a_system_message_about_the_actual_problem(self):
        data = self.only_json(self.run_hook([self.EDIT], CLAIM_TEXT, True))
        self.assertEqual(set(data), {'systemMessage'})   # 모델을 다시 부르는 additionalContext 가 없다
        user = data['systemMessage']
        self.assertIn('다시 막지 않고', user)
        self.assertIn('확인되지 않은 것으로 보세요', user)
        self.assertNotIn('다음 응답에서', user)           # 모델에게 일을 시키는 말이 아니다
        for need in ('src/center/views.py', '검증 실행 기록이 없다', '테스트 3개 통과'):
            self.assertIn(need, user)

    # 9. 입력 JSON 을 못 읽음
    def test_unreadable_input_is_still_blocked_even_if_it_looks_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_init(tmp)
            data = self.only_json(hook(tmp, '{"stop_hook_active": true'))   # 잘린 JSON: active 를 믿을 수 없다
        self.assertEqual(data['decision'], 'block')
        self.assertIn('점검을 하지 못했다', data['reason'])

    # 10. check() 예외와 재검사
    def test_check_exception_blocks_on_the_first_stop(self):
        data = json.loads(self.main_output({}, side_effect=RuntimeError('boom')))
        self.assertEqual(data['decision'], 'block')
        self.assertIn('RuntimeError', data['reason'])

    def test_check_exception_in_the_recheck_is_reported_not_blocked_and_not_passed(self):
        data = json.loads(self.main_output({'stop_hook_active': True}, side_effect=RuntimeError('boom')))
        self.assertNotIn('decision', data)
        self.assertEqual(set(data), {'systemMessage'})
        text = data['systemMessage']
        self.assertIn('점검하지 못한 것', text)       # 고칠 문제가 아니라 점검을 못 한 것으로 구분
        self.assertIn('RuntimeError', text)
        self.assertIn('예기치 않은 오류', text)
        self.assertNotIn('해결되지 않은 문제', text)

    def test_recheck_really_runs_check_again(self):
        with mock.patch.object(stop_check, 'check', return_value=([], [])) as fake, \
                mock.patch('sys.stdin', io.StringIO(json.dumps({'stop_hook_active': True}))), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            stop_check.main()
        fake.assert_called_once()
        self.assertEqual(out.getvalue(), '')

    def test_recheck_separates_problems_from_unchecked_items(self):
        out = self.main_output({'stop_hook_active': True}, return_value=(['문제 하나'], ['점검 못 한 하나']))
        text = json.loads(out)['systemMessage']
        self.assertIn('해결되지 않은 문제: 문제 하나', text)
        self.assertIn('점검하지 못한 것: 점검 못 한 하나', text)

    # 12. notices(결과 불명 안내) 출력 경로(D3)
    @staticmethod
    def with_notices(problems, unverified, notices):
        def fake_check(data, root, notices_out=None):
            notices_out.extend(notices)
            return problems, unverified
        return fake_check

    def test_notices_only_on_the_first_stop_is_a_system_message_without_blocking(self):
        data = json.loads(self.main_output({}, side_effect=self.with_notices([], [], ['결과 불명 안내'])))
        self.assertEqual(set(data), {'systemMessage'})
        self.assertIn('결과 불명 안내', data['systemMessage'])

    def test_notices_only_in_the_recheck_is_also_a_system_message_only(self):
        data = json.loads(self.main_output({'stop_hook_active': True}, side_effect=self.with_notices([], [], ['결과 불명 안내'])))
        self.assertEqual(set(data), {'systemMessage'})

    def test_notices_ride_along_with_the_first_block(self):
        data = json.loads(self.main_output({}, side_effect=self.with_notices(['문제'], [], ['결과 불명 안내'])))
        self.assertEqual(data['decision'], 'block')
        self.assertIn('문제', data['reason'])
        self.assertIn('결과 불명 안내', data['reason'])

    def test_recheck_with_a_problem_and_notices_is_a_system_message_only(self):
        data = json.loads(self.main_output({'stop_hook_active': True}, side_effect=self.with_notices(['문제'], [], ['결과 불명 안내'])))
        self.assertEqual(set(data), {'systemMessage'})
        self.assertIn('문제', data['systemMessage'])
        self.assertIn('결과 불명 안내', data['systemMessage'])

    def test_no_problem_and_no_notice_stays_silent(self):
        self.assertEqual(self.main_output({}, side_effect=self.with_notices([], [], [])), '')

    def test_notices_never_make_a_pass_claim_pass_silently(self):
        # 불명확한 검증 결과는 통과로 취급하지 않는다: 주장 + 불명이면 notice 가 아니라 차단 사유다.
        data = self.only_json(self.run_hook([self.EDIT, tool('Bash', command='python manage.py test | tail -3')], CLAIM_TEXT, False))
        self.assertEqual(data['decision'], 'block')

    # 11. stdout 에는 JSON 만
    def test_stdout_is_one_json_document_and_stderr_is_empty(self):
        for active, turn, text in [(False, [self.EDIT], CLAIM_TEXT), (True, [self.EDIT], CLAIM_TEXT), (True, [], '완벽합니다.')]:
            with tempfile.TemporaryDirectory() as tmp:
                git_init(tmp)
                path = turn_transcript(tmp, turn, text)
                r = subprocess.run(['python3', str(SCRIPT)], input=json.dumps({'transcript_path': str(path), 'stop_hook_active': active}),
                                   capture_output=True, text=True, cwd=tmp, env={'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': tmp})
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stderr, '')
            self.only_json(r.stdout)


if __name__ == '__main__':
    unittest.main()
