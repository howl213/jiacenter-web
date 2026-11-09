"""export_for_team.py 시험. 임시 저장소에서 내보내기를 돌려 본다.

실행: python -m unittest discover -s scripts
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('export_for_team.py').resolve()


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        self.out = Path(self.tmp.name) / 'out'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', '1+x@users.noreply.github.com')
        self.git('config', 'user.name', 'x')
        # 내보내기가 같은 폴더의 check_leaks.sh 를 쓰므로 저장소 안에 두지 않아도 된다(스크립트 위치 기준)

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *a):
        subprocess.run(['git', *a], cwd=self.repo, check=True, capture_output=True)

    def put(self, name, text):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        self.git('add', name)

    def export(self):
        env = {**os.environ, 'EXPORT_SKIP_CHECK': '1'}
        return subprocess.run(['python3', str(SCRIPT), str(self.out)], cwd=self.repo, env=env,
                              capture_output=True, text=True)

    def base_files(self):
        self.put('manage.py', 'print("x")\n')
        self.put('center/views.py', 'a = 1\n')

    def test_marker_comment_blocks_are_removed_but_code_stays(self):
        self.base_files()
        self.put('center/views.py',
                 'a = 1\n# [실습 A05] 이스케이프를 하지 않는다\n# 두 번째 설명 줄도 같이 사라진다\nb = 2\n')
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.out / 'center/views.py').read_text(encoding='utf-8')
        self.assertEqual(text, 'a = 1\nb = 2\n')

    def test_internal_files_are_not_exported_and_readme_is_replaced(self):
        self.base_files()
        for name in ['docs/vuln-manifest.md', 'CLAUDE.md', 'SECURITY_REVIEW.md', 'scripts/x.py',
                     '.github/workflows/t.yml', '.claude/settings.json', 'center/tests.py', 'flow.svg']:
            self.put(name, 'x\n')
        self.put('README.md', '# 내부 설명\n취약점 목록\n')
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stderr)
        exported = {str(p.relative_to(self.out)) for p in self.out.rglob('*') if p.is_file()}
        self.assertEqual(exported, {'manage.py', 'center/views.py', 'README.md'})
        self.assertIn('docker compose up', (self.out / 'README.md').read_text(encoding='utf-8'))
        self.assertNotIn('내부 설명', (self.out / 'README.md').read_text(encoding='utf-8'))

    def test_marker_outside_a_comment_line_fails_and_leaves_nothing(self):
        self.base_files()
        self.put('center/views.py', 'def f():\n    """[실습 A01] 설명"""\n')
        r = self.export()
        self.assertEqual(r.returncode, 1)
        self.assertIn('주석 줄이 아닙니다', r.stderr)
        self.assertFalse(self.out.exists())

    def test_forbidden_words_left_in_other_places_fail(self):
        self.base_files()
        self.put('center/views.py', 'x = "SECURITY_REVIEW 참고"\n')
        r = self.export()
        self.assertEqual(r.returncode, 1)
        self.assertFalse(self.out.exists())

    def test_personal_data_in_exported_files_fails(self):
        self.base_files()
        self.put('center/views.py', '# 문의 someone' + '@gmail.com\n')   # 이 파일 자체가 검사에 걸리지 않게 이어 붙인다
        r = self.export()
        self.assertEqual(r.returncode, 1)
        self.assertIn('개인정보', r.stderr)
        self.assertFalse(self.out.exists())

    def test_existing_non_empty_target_is_refused(self):
        self.base_files()
        self.out.mkdir()
        (self.out / 'keep.txt').write_text('x')
        r = self.export()
        self.assertEqual(r.returncode, 64)
        self.assertTrue((self.out / 'keep.txt').exists())


if __name__ == '__main__':
    unittest.main()
