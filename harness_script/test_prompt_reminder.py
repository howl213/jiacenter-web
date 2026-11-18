"""prompt_reminder.py 시험: 규칙 네 줄이 나오는지, 입력이 이상해도 질문을 막지 않는지, 설정에 걸려 있는지.

실행: python -m unittest discover -s harness_script
"""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'harness_script' / 'prompt_reminder.py'


class PromptReminder(unittest.TestCase):
    def run_with(self, stdin):
        return subprocess.run(['python3', str(SCRIPT)], input=stdin, capture_output=True, text=True)

    def test_injects_the_four_rules(self):
        r = self.run_with('{"prompt": "맞아?"}')
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'UserPromptSubmit')
        for must in ['목표 ①', '설명만 하고 멈춘다', '확인하지 못한 것', '시킬 때만', '먼저 묻는다']:
            self.assertIn(must, out['additionalContext'])

    def test_rules_are_identical_to_claude_md(self):
        # CLAUDE.md 2절의 네 줄이 원본이고 훅은 그대로 복사본이다. 한쪽만 고치면 여기서 실패한다.
        md = (ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
        section = md[md.index('## 2. 작업 규칙'):md.index('### 테스트에 대해')]
        original = [l for l in section.splitlines() if l[:3] in ('1. ', '2. ', '3. ', '4. ')]
        out = json.loads(self.run_with('{}').stdout)['hookSpecificOutput']['additionalContext']
        injected = [l for l in out.splitlines() if l[:3] in ('1. ', '2. ', '3. ', '4. ')]
        self.assertEqual(len(original), 4)
        self.assertEqual(original, injected)

    def test_does_not_block_on_broken_input(self):
        for stdin in ['', 'not json', '\x00']:
            self.assertEqual(self.run_with(stdin).returncode, 0, stdin)

    def test_is_registered_in_settings(self):
        hooks = json.loads((ROOT / '.claude' / 'settings.json').read_text(encoding='utf-8'))['hooks']
        commands = [h['command'] for g in hooks['UserPromptSubmit'] for h in g['hooks']]
        self.assertTrue(any('prompt_reminder.py' in c for c in commands))


if __name__ == '__main__':
    unittest.main()
