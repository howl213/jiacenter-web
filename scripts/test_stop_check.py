"""stop_check.py 의 단정 표현 점검 시험. 실제 세션 기록 모양(assistant → message.content[] 의 text)을 흉내 낸다.

실행: python -m unittest discover -s scripts
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('stop_check.py').resolve()


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
            payload = json.dumps({'transcript_path': str(transcript(tmp, *texts))})
            r = subprocess.run(['python3', str(SCRIPT)], input=payload, capture_output=True, text=True, cwd=tmp,
                               env={'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': tmp})
        return r.stdout

    def test_flags_unhedged_absolute_claims(self):
        self.assertIn('단정 표현', self.run_hook('테스트가 통과했고 문제없습니다. 안전합니다.'))

    def test_hedged_report_passes(self):
        self.assertEqual(self.run_hook('테스트 49개 통과. 확인하지 못한 것: 브라우저 화면. 문제없다고는 말할 수 없다.'), '')

    def test_negated_sentences_are_not_claims(self):
        self.assertEqual(self.run_hook('통과가 곧 안전하다는 뜻은 아니다. 안전하다고 말하지 않는다.'), '')

    def test_only_the_last_assistant_message_counts(self):
        self.assertEqual(self.run_hook('완벽합니다.', '테스트 3개 통과. 미확인: HTTPS.'), '')

    def test_unreadable_or_missing_transcript_is_silent(self):
        r = subprocess.run(['python3', str(SCRIPT)], input=json.dumps({'transcript_path': '/nonexistent'}),
                           capture_output=True, text=True)
        self.assertEqual((r.stdout, r.returncode), ('', 0))

    def test_blocks_with_a_reason_for_claude(self):
        out = json.loads(self.run_hook('테스트가 통과했고 문제없습니다. 안전합니다.'))
        self.assertEqual(out['decision'], 'block')
        self.assertIn('막힌 이유', out['reason'])


def tool(name, **inp):
    return {'type': 'tool_use', 'name': name, 'input': inp}


class UntestedEdit(unittest.TestCase):
    """코드를 고쳤는데 그 뒤로 테스트 기록이 없으면 막는다. 세션 기록의 도구 호출로 판정한다."""

    def run_hook(self, *turn, extra=None):
        """turn: 한 턴에서 assistant 가 부른 도구 블록들(차례대로). 마지막 글은 확인 못 한 것을 적은 보고."""
        with tempfile.TemporaryDirectory() as tmp:
            lines = [json.dumps({'type': 'user', 'message': {'role': 'user', 'content': '고쳐 줘'}})]
            for block in turn:
                block = json.loads(json.dumps(block).replace('ROOT', tmp))
                lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [block]}}))
                lines.append(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [
                    {'type': 'tool_result', 'content': 'ok'}]}}))
            lines.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
                {'type': 'text', 'text': '완료. 확인하지 못한 것: 없음.'}]}}))
            path = Path(tmp) / 't.jsonl'
            path.write_text('\n'.join(lines), encoding='utf-8')
            payload = json.dumps({'transcript_path': str(path), **(extra or {})})
            r = subprocess.run(['python3', str(SCRIPT)], input=payload, capture_output=True, text=True, cwd=tmp,
                               env={'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': tmp})
        return r.stdout

    EDIT = tool('Edit', file_path='ROOT/center/views.py')
    TEST = tool('Bash', command='.venv/bin/python manage.py test')

    def test_edit_without_test_is_blocked(self):
        out = json.loads(self.run_hook(self.EDIT))
        self.assertEqual(out['decision'], 'block')
        self.assertIn('center/views.py', out['reason'])
        self.assertIn('테스트를 돌린 기록이 없다', out['reason'])

    def test_edit_then_test_passes(self):
        self.assertEqual(self.run_hook(self.EDIT, self.TEST), '')

    def test_test_before_the_last_edit_does_not_count(self):
        self.assertIn('block', self.run_hook(self.TEST, self.EDIT))

    def test_verify_script_counts_as_a_test(self):
        self.assertEqual(self.run_hook(self.EDIT, tool('Bash', command='bash scripts/verify.sh')), '')

    def test_edit_outside_code_dirs_is_ignored(self):
        self.assertEqual(self.run_hook(tool('Edit', file_path='ROOT/docs/확인사항.md')), '')

    def test_only_this_turn_counts(self):
        # 앞 턴에서 고친 것은 새 사용자 입력이 오면 지난 일이다.
        with tempfile.TemporaryDirectory() as tmp:
            old = {'type': 'assistant', 'message': {'content': [tool('Edit', file_path=f'{tmp}/center/views.py')]}}
            new_prompt = {'type': 'user', 'message': {'content': '다음 질문'}}
            reply = {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '설명만 했다.'}]}}
            path = Path(tmp) / 't.jsonl'
            path.write_text('\n'.join(json.dumps(e) for e in [old, new_prompt, reply]), encoding='utf-8')
            r = subprocess.run(['python3', str(SCRIPT)], input=json.dumps({'transcript_path': str(path)}),
                               capture_output=True, text=True, cwd=tmp,
                               env={'PATH': '/usr/bin:/bin', 'CLAUDE_PROJECT_DIR': tmp})
        self.assertEqual(r.stdout, '')

    def test_already_continuing_because_of_this_hook_passes(self):
        self.assertEqual(self.run_hook(self.EDIT, extra={'stop_hook_active': True}), '')

    def test_uses_last_assistant_message_from_the_hook_input(self):
        out = self.run_hook(self.EDIT, self.TEST, extra={'last_assistant_message': '문제없습니다. 완벽합니다.'})
        self.assertIn('단정 표현', out)


if __name__ == '__main__':
    unittest.main()
