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


if __name__ == '__main__':
    unittest.main()
