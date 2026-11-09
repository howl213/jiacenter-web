"""session_brief.py 시험: 세션 시작 때 목표와 상태가 나오는지, 어떤 일이 있어도 세션 시작을 막지 않는지.

실행: python -m unittest discover -s scripts
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('session_brief.py').resolve()


class SessionBrief(unittest.TestCase):
    def run_in(self, directory):
        env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(directory)}
        return subprocess.run(['python3', str(SCRIPT)], capture_output=True, text=True, env=env, cwd=directory)

    def test_shows_state_and_both_goals(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['git', 'init', '-q'], cwd=tmp, check=True)
            r = self.run_in(tmp)
        self.assertEqual(r.returncode, 0)
        text = json.loads(r.stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn('브랜치', text)
        self.assertIn('목표 ①', text)
        self.assertIn('②', text)

    def test_never_blocks_the_session_when_it_cannot_run(self):
        r = subprocess.run(['python3', str(SCRIPT)], capture_output=True, text=True,
                           env={**os.environ, 'CLAUDE_PROJECT_DIR': '/nonexistent-directory-for-test'})
        self.assertEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
