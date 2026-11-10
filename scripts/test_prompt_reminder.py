"""prompt_reminder.py 시험: 규칙 네 줄이 나오는지, 입력이 이상해도 질문을 막지 않는지, 설정에 걸려 있는지.

실행: python -m unittest discover -s scripts
"""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'prompt_reminder.py'


class PromptReminder(unittest.TestCase):
    def run_with(self, stdin):
        return subprocess.run(['python3', str(SCRIPT)], input=stdin, capture_output=True, text=True)

    def test_injects_the_four_rules(self):
        r = self.run_with('{"prompt": "맞아?"}')
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'UserPromptSubmit')
        for must in ['목표 ①', '설명만 하고 멈춘다', '확인하지 못한 것', '시킬 때만']:
            self.assertIn(must, out['additionalContext'])

    def test_does_not_block_on_broken_input(self):
        for stdin in ['', 'not json', '\x00']:
            self.assertEqual(self.run_with(stdin).returncode, 0, stdin)

    def test_is_registered_in_settings(self):
        hooks = json.loads((ROOT / '.claude' / 'settings.json').read_text(encoding='utf-8'))['hooks']
        commands = [h['command'] for g in hooks['UserPromptSubmit'] for h in g['hooks']]
        self.assertTrue(any('prompt_reminder.py' in c for c in commands))


if __name__ == '__main__':
    unittest.main()
