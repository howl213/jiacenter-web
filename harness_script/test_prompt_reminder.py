"""prompt_reminder.py 시험: 규칙 네 줄(2번은 전문, 나머지는 압축)이 나오는지, 입력이 이상해도 질문을 막지 않는지, 설정에 걸려 있는지.

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

    def injected(self):
        out = json.loads(self.run_with('{}').stdout)['hookSpecificOutput']['additionalContext']
        return out, {l[:2]: l for l in out.splitlines() if l[:3] in ('1. ', '2. ', '3. ', '4. ')}

    def md_rules(self):
        md = (ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
        section = md[md.index('## 2. 작업 규칙'):md.index('### 테스트에 대해')]
        return section, {l[:2]: l for l in section.splitlines() if l[:3] in ('1. ', '2. ', '3. ', '4. ')}

    def test_injects_event_and_four_rules(self):
        r = self.run_with('{"prompt": "맞아?"}')
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'UserPromptSubmit')
        self.assertEqual(sorted(self.injected()[1]), ['1.', '2.', '3.', '4.'])

    def test_rule_2_is_identical_to_claude_md(self):
        # 2번(질문엔 설명만)은 과거 사고가 잦아 줄이지 않는다. CLAUDE.md 2절이 원본이다.
        self.assertEqual(self.md_rules()[1]['2.'], self.injected()[1]['2.'])

    def test_condensed_rules_keep_their_key_meaning(self):
        # 줄인 1·3·4번에서 의미를 가르는 말이 남았는지. 각 말은 CLAUDE.md 원문에도 있어야 한다(훅이 새 규칙을 지어내지 않게).
        keys = {
            '1.': ['목표 ①', '②', '먼저 말한다'],
            '3.': ['직접 연', '추측', '시킨 일의 결과', '확인하지 못한 것', '"완료"', '안전하다/문제없다', '개발용 기본값'],
            '4.': ['끝났을 때만', '커밋할까요', '푸시', 'PR', '병합', '승인', '켜짐/안 켜짐'],
        }
        section, _ = self.md_rules()
        _, rules = self.injected()
        for n, words in keys.items():
            for w in words:
                self.assertIn(w, rules[n], f'{n} 줄에서 "{w}" 가 빠졌다')
                self.assertIn(w, section, f'"{w}" 가 CLAUDE.md 2절에 없다')

    def test_is_shorter_than_the_full_rules(self):
        # 매 질문마다 들어가는 글이라 전문(약 1,000자)으로 되돌아가면 알린다.
        self.assertLess(len(self.injected()[0]), 800)

    def test_does_not_block_on_broken_input(self):
        for stdin in ['', 'not json', '\x00']:
            self.assertEqual(self.run_with(stdin).returncode, 0, stdin)

    def test_is_registered_in_settings(self):
        hooks = json.loads((ROOT / '.claude' / 'settings.json').read_text(encoding='utf-8'))['hooks']
        commands = [h['command'] for g in hooks['UserPromptSubmit'] for h in g['hooks']]
        self.assertTrue(any('prompt_reminder.py' in c for c in commands))


if __name__ == '__main__':
    unittest.main()
