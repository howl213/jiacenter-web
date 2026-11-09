"""claude_guard.py 가 막을 것은 막고 묻을 것은 묻고 나머지는 통과시키는지 확인한다.

실행: python -m unittest discover -s scripts
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).with_name('claude_guard.py').resolve()


def run(cmd, cwd):
    payload = json.dumps({'tool_name': 'Bash', 'cwd': str(cwd), 'tool_input': {'command': cmd}})
    r = subprocess.run(['python3', str(GUARD)], input=payload, capture_output=True, text=True)
    if r.returncode == 2:
        return 'BLOCK'
    return 'ASK' if '"permissionDecision": "ask"' in r.stdout else 'PASS'


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ours = Path(cls.tmp.name) / 'ours'
        cls.other = Path(cls.tmp.name) / 'other'
        for d, url in [(cls.ours, 'https://github.com/howl213/jiacenter-web.git'),
                       (cls.other, 'https://github.com/someone/else.git')]:
            d.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=d, check=True)
            subprocess.run(['git', 'remote', 'add', 'origin', url], cwd=d, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, expected, cmd, cwd=None):
        self.assertEqual(run(cmd, cwd or self.ours), expected, cmd)

    def test_no_verify_is_blocked(self):
        self.check('BLOCK', 'git commit --no-verify -m x')
        self.check('PASS', 'git commit -m "정상"')

    def test_words_inside_text_are_not_commands(self):
        # 실제로 있었던 오탐: 문서를 쓰는 heredoc 안에 --no-verify 라는 글이 있다고 막혔다
        self.check('PASS', "python3 - <<'EOF'\nprint('git commit --no-verify 는 막힌다')\nEOF")
        self.check('PASS', 'git commit -m "--no-verify 는 쓰지 않는다"')
        self.check('PASS', "cat > a.md <<'EOF'\ngh pr create --repo SJH910/Web-Hacking\nEOF")
        # 그래도 heredoc 뒤에 오는 진짜 명령은 본다
        self.check('BLOCK', "cat > a.md <<'EOF'\nx\nEOF\ngit commit --no-verify -m y")

    def test_push_to_foreign_remote_asks(self):
        self.check('PASS', 'git push -u origin HEAD')
        self.check('ASK', 'git push -u origin HEAD', self.other)
        self.check('ASK', 'git push --force origin main')

    def test_gh_commands_on_foreign_repos_ask(self):
        self.check('ASK', 'gh pr create --repo SJH910/Web-Hacking --base main')
        self.check('PASS', 'gh pr create --repo howl213/jiacenter-web-portfolio')
        self.check('PASS', 'gh pr create --base main')
        self.check('ASK', 'gh api -X POST repos/SJH910/Web-Hacking/issues')
        self.check('PASS', 'gh api repos/SJH910/Web-Hacking/contents/PLAN.md')   # 읽기는 통과
        self.check('ASK', 'gh repo create howl213/x --private')

    def test_migrate_asks_but_tests_and_checks_pass(self):
        self.check('ASK', '.venv/bin/python manage.py migrate')
        self.check('PASS', '.venv/bin/python manage.py test')
        self.check('PASS', '.venv/bin/python manage.py makemigrations --check --dry-run')

    def test_ordinary_commands_pass(self):
        self.check('PASS', 'ls -la')


if __name__ == '__main__':
    unittest.main()
