"""session_brief.py 시험: 세션 시작 때 목표와 상태가 나오는지, 어떤 일이 있어도 세션 시작을 막지 않는지.

실행: python -m unittest discover -s harness_script
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

    def test_warns_when_checkout_lacks_origin_main_commits(self):
        git = lambda cwd, *a: subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', *a],
                                             cwd=cwd, check=True, capture_output=True)
        with tempfile.TemporaryDirectory() as tmp:
            origin, one, two = (Path(tmp) / n for n in ('origin', 'one', 'two'))
            git(tmp, 'init', '-q', '--bare', '-b', 'main', str(origin))
            git(tmp, 'clone', '-q', str(origin), str(one))
            (one / 'a').write_text('1')
            git(one, 'add', 'a'); git(one, 'commit', '-q', '-m', 'first'); git(one, 'push', '-q', 'origin', 'HEAD:main')
            git(tmp, 'clone', '-q', str(origin), str(two))
            quiet = json.loads(self.run_in(two).stdout)['hookSpecificOutput']['additionalContext']
            (one / 'a').write_text('2')
            git(one, 'commit', '-qam', 'second'); git(one, 'push', '-q', 'origin', 'HEAD:main')
            text = json.loads(self.run_in(two).stdout)['hookSpecificOutput']['additionalContext']
        self.assertNotIn('커밋이 없다', quiet)
        self.assertIn('1개 커밋이 없다', text)
        self.assertIn('git pull', text)

    def test_never_blocks_the_session_when_it_cannot_run(self):
        r = subprocess.run(['python3', str(SCRIPT)], capture_output=True, text=True,
                           env={**os.environ, 'CLAUDE_PROJECT_DIR': '/nonexistent-directory-for-test'})
        self.assertEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
