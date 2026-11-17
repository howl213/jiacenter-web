"""CLAUDE.md 0절의 '사람이 정하는 것' 표와 claude_guard 훅이 어긋나지 않는지 본다.

표에서 방식이 '훅'인 줄의 예시 명령은 가장 불리한 환경(main 위, 남의 저장소)에서 훅이 막거나 물어야 한다.
표에 훅이라고 적고 훅을 지우거나, 예시를 잘못 적으면 이 시험이 실패한다.
방식이 '대화'인 줄은 기계가 확인할 수 없으므로 표에 '훅 없음'이라고 적혀 있는지만 본다.
"""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / 'harness_script' / 'claude_guard.py'
CLAUDE_MD = ROOT / 'CLAUDE.md'
COMMAND_START = ('python3', '.venv', 'git', 'gh', 'sqlite3')


def table_rows():
    text = CLAUDE_MD.read_text(encoding='utf-8')
    start = text.index('**사람이 정하는 것**')
    block = text[start:text.index('\n---', start)]
    rows = []
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if line.startswith('|') and len(cells) == 3 and cells[0] not in ('결정 지점', '---') and '---' not in cells[0]:
            rows.append(cells)
    return rows


@unittest.skipUnless(CLAUDE_MD.exists(), 'CLAUDE.md 가 없는 곳(내보낸 폴더 등)에서는 건너뛴다')
class DecisionTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name)
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=cls.repo, check=True)
        subprocess.run(['git', 'remote', 'add', 'origin', 'https://github.com/someone/else.git'], cwd=cls.repo, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def decision(self, cmd):
        payload = json.dumps({'tool_name': 'Bash', 'cwd': str(self.repo), 'tool_input': {'command': cmd}})
        r = subprocess.run(['python3', str(GUARD)], input=payload, capture_output=True, text=True)
        return 'BLOCK' if r.returncode == 2 else ('ASK' if '"ask"' in r.stdout else 'PASS')

    def test_table_has_both_kinds_of_rows(self):
        kinds = {cells[1].split()[0] for cells in table_rows()}
        self.assertTrue({'훅', '대화'} <= kinds, kinds)

    def test_every_hook_row_example_is_stopped_by_the_guard(self):
        checked = 0
        for point, how, detail in table_rows():
            if how != '훅':
                continue
            commands = [c for c in re.findall(r'`([^`]+)`', detail) if c.startswith(COMMAND_START)]
            self.assertTrue(commands, f'"{point}" 줄에 예시 명령이 없다')
            for cmd in commands:
                self.assertNotEqual(self.decision(cmd), 'PASS', f'"{point}": 표에는 훅이 묻는다고 적혔는데 통과한다: {cmd}')
                checked += 1
        self.assertGreaterEqual(checked, 10)

    def test_conversation_rows_say_there_is_no_hook(self):
        for point, how, detail in table_rows():
            if how.startswith('대화'):
                self.assertIn('훅', detail, f'"{point}" 줄은 훅이 없다는 것을 밝혀야 한다')


if __name__ == '__main__':
    unittest.main()
