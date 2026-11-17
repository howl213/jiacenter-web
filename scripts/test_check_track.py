"""check_track.py / check_manifest.py 시험. 임시 저장소를 만들어 확인한다.

실행: python -m unittest discover -s scripts
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

TRACK = Path(__file__).with_name('check_track.py').resolve()
MANIFEST = Path(__file__).with_name('check_manifest.py').resolve()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', '1+x@users.noreply.github.com')
        self.git('config', 'user.name', 'x')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(['git', *args], cwd=self.dir, check=True, capture_output=True)

    def put(self, name, text):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        self.git('add', name)

    def commit(self, msg):
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-q', '--allow-empty', '-m', msg)

    def run_script(self, script, *args, branch=None):
        env = {**os.environ}
        if branch:
            env['TRACK_BRANCH'] = branch
        r = subprocess.run(['python3', str(script), *args], cwd=self.dir, env=env, capture_output=True, text=True)
        return r.returncode, r.stderr


class Track(Base):
    def test_clean_main_passes(self):
        self.put('a.py', 'x = 1\n')
        self.assertEqual(self.run_script(TRACK, 'tree', branch='feat/x')[0], 0)

    def test_main_rejects_planted_marker_banner_and_manifest(self):
        self.put('a.py', 'x = 1  # [실습 A05] 일부러 취약\n')
        self.put('t.html', '<div>실습용 취약 버전</div>\n')
        self.put('docs/vuln-manifest.md', '# 목록\n')
        code, err = self.run_script(TRACK, 'tree', branch='main')
        self.assertEqual(code, 1)
        for needle in ['a.py:1', 't.html:1', 'vuln-manifest']:
            self.assertIn(needle, err)

    def test_tools_in_scripts_may_mention_the_marker(self):
        # 표시를 다루는 도구와 그 시험은 표시 문자열을 담고 있어도 된다
        self.put('scripts/export_tool.py', 'MARKER = "[실습 A05]"\n')
        self.assertEqual(self.run_script(TRACK, 'tree', branch='feat/x')[0], 0)

    def test_binary_files_do_not_crash_the_check(self):
        # 글꼴 파일이 들어왔을 때 UnicodeDecodeError 로 검사가 죽던 문제(PR #30). 바이너리 옆의 일반 파일은 그대로 걸러야 한다.
        (self.dir / 'f.woff2').write_bytes(b'wOF2\xfe\xff\x00\x80' * 50)
        self.git('add', 'f.woff2')
        self.put('a.py', 'x = 1  # [실습 A05] 일부러 취약\n')
        code, err = self.run_script(TRACK, 'tree', branch='feat/x')
        self.assertEqual(code, 1)
        self.assertIn('a.py:1', err)
        self.assertNotIn('Traceback', err)

    def test_main_rejects_vuln_commits_in_history(self):
        self.put('a.py', 'x = 1\n')
        self.commit('base')
        self.git('branch', 'origin/main')   # 비교 기준 (원격 대신 같은 이름의 로컬 브랜치)
        self.commit('vuln(A07): 심음')
        code, err = self.run_script(TRACK, 'tree', branch='feat/x')
        self.assertEqual(code, 1)
        self.assertIn('vuln(A07)', err)

    def test_vuln_requires_manifest_and_forbids_answer_sheet(self):
        self.put('SECURITY_REVIEW.md', '# 답안지\n')
        code, err = self.run_script(TRACK, 'tree', branch='vuln/practice')
        self.assertEqual(code, 1)
        self.assertIn('SECURITY_REVIEW.md', err)
        self.assertIn('vuln-manifest', err)

    def test_proper_vuln_tree_passes_even_with_markers(self):
        self.put('a.py', 'x = 1  # [실습 A05] 일부러 취약\n')
        self.put('docs/vuln-manifest.md', '# 목록\n')
        self.assertEqual(self.run_script(TRACK, 'tree', branch='vuln/practice')[0], 0)

    def test_pr_direction(self):
        self.assertEqual(self.run_script(TRACK, 'pr', 'main', 'vuln/practice')[0], 1)
        self.assertEqual(self.run_script(TRACK, 'pr', 'vuln/practice', 'main')[0], 0)
        self.assertEqual(self.run_script(TRACK, 'pr', 'main', 'feat/x')[0], 0)


class Manifest(Base):
    def test_no_manifest_means_nothing_to_check(self):
        self.assertEqual(self.run_script(MANIFEST)[0], 0)

    def test_listed_and_committed_match(self):
        self.put('docs/vuln-manifest.md', '| A07 | x | `vuln(A07)` | 심음 |\n')
        self.commit('vuln(A07): 심음')
        self.assertEqual(self.run_script(MANIFEST)[0], 0)

    def test_listed_without_commit_and_commit_without_listing_both_fail(self):
        self.put('docs/vuln-manifest.md', '| A07 | x | `vuln(A07)` | 심음 |\n')
        self.commit('목록만')
        code, err = self.run_script(MANIFEST)
        self.assertEqual(code, 1)
        self.assertIn('vuln(A07) 가 목록에 있으나', err)
        self.commit('vuln(A04): 목록에 없는 커밋')
        self.assertIn('vuln(A04) 커밋이 있으나 목록에 없다', self.run_script(MANIFEST)[1])


if __name__ == '__main__':
    unittest.main()
