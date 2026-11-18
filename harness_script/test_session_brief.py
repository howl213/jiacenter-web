"""session_brief.py 시험: 정상이면 한 줄 상태, 경고는 자세히 나오는지, 어떤 일이 있어도 세션 시작을 막지 않는지.

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

    def brief(self, branch='main', hooks=True, email='t@users.noreply.github.com'):
        with tempfile.TemporaryDirectory() as tmp:
            git = lambda *a: subprocess.run(['git', *a], cwd=tmp, check=True, capture_output=True)
            git('init', '-q', '-b', branch)
            git('config', 'user.name', 't')   # 없으면 CI 러너에서 commit 이 128 로 실패한다(로컬은 계정 정보로 채워짐)
            git('config', 'user.email', email)
            if hooks:
                git('config', 'core.hooksPath', '.githooks')
            git('commit', '-q', '--allow-empty', '-m', 'first')   # 커밋이 없으면 git 이 브랜치 이름을 HEAD 로 준다
            r = self.run_in(tmp)
        self.assertEqual(r.returncode, 0)
        return json.loads(r.stdout)['hookSpecificOutput']['additionalContext']

    def test_normal_state_is_one_short_line_without_goal_text(self):
        # 정상이면 목표·규칙 안내를 되풀이하지 않는다(그건 CLAUDE.md 몫). 핵심 상태만 한 줄.
        text = self.brief()
        self.assertEqual(len(text.splitlines()), 1, text)
        for must in ['[상태]', 'main 계열', '깨끗함', '상위 브랜치 없음']:
            self.assertIn(must, text)
        for gone in ['목표 ①', 'OWASP', '규칙 네 줄', '마지막 커밋']:
            self.assertNotIn(gone, text)

    def test_vuln_branch_is_labelled(self):
        self.assertIn('(vuln)', self.brief(branch='vuln/x'))

    def test_warnings_stay_detailed(self):
        # 위험·주의는 정상 한 줄로 줄이지 않고 이유와 조치를 그대로 말한다.
        text = self.brief(hooks=False, email='me@example.com')
        self.assertIn('경고: git pre-commit 훅이 꺼져 있다', text)
        self.assertIn('git config core.hooksPath .githooks', text)
        self.assertIn('개인 주소', text)

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
