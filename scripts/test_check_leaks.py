"""check_leaks.sh 가 실제로 잡고, 정상 파일은 통과시키는지 임시 저장소에서 확인한다.

실행: python -m unittest discover -s scripts
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('check_leaks.sh').resolve()


class CheckLeaks(unittest.TestCase):
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

    def put(self, name, text, stage=True):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        if stage:
            self.git('add', name)

    def run_check(self, mode='--staged'):
        r = subprocess.run(['bash', str(SCRIPT), mode], cwd=self.dir, capture_output=True, text=True)
        return r.returncode, r.stderr

    def test_clean_file_passes(self):
        self.put('a.py', 'print("hello")\n')
        self.assertEqual(self.run_check()[0], 0)

    def test_personal_email_is_blocked(self):
        self.put('a.md', '문의: someone@gmail.com\n')
        code, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn('a.md:1', err)

    def test_korean_file_names_are_scanned_too(self):
        # git 은 한글 이름을 따옴표와 8진수로 바꿔 출력해서, 처리하지 않으면 이 파일들을 건너뛴다
        self.put('docs/확인사항.md', '문의: someone@gmail.com\n')
        code, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn('확인사항.md:1', err)

    def test_noreply_and_example_emails_are_allowed(self):
        self.put('a.md', '1+x@users.noreply.github.com noreply@anthropic.com a@example.com\n')
        self.assertEqual(self.run_check()[0], 0)

    def test_real_phone_blocked_dummy_allowed(self):
        self.put('a.md', '010-0000-0001\n')
        self.assertEqual(self.run_check()[0], 0)
        self.put('b.md', '연락처 010-1234-5678\n')
        self.assertEqual(self.run_check()[0], 1)

    def test_user_path_is_blocked(self):
        self.put('a.md', '폴더 /Users/somebody/Desktop\n')
        self.assertEqual(self.run_check()[0], 1)

    def test_secret_assignment_blocked_but_dev_only_allowed(self):
        self.put('a.py', "SECRET_KEY = 'abcdefghijklmnop'\n")
        self.assertEqual(self.run_check()[0], 1)
        self.git('rm', '-q', '--cached', 'a.py')
        self.put('b.py', "SECRET_KEY = 'dev-only-not-for-production'\n")
        self.assertEqual(self.run_check()[0], 0)

    def test_forbidden_file_names(self):
        for name in ['db.sqlite3', '.env', 'logs/error.log', 'k.pem']:
            self.put(name, 'x\n')
            code, err = self.run_check()
            self.assertEqual(code, 1, name)
            self.assertIn(name, err)
            self.git('rm', '-q', '--cached', name)

    def test_env_example_is_allowed(self):
        self.put('.env.example', 'DJANGO_SECRET_KEY=\n')
        self.assertEqual(self.run_check()[0], 0)

    def test_staged_mode_ignores_unstaged_files(self):
        self.put('a.md', 'someone@gmail.com\n', stage=False)
        self.assertEqual(self.run_check('--staged')[0], 0)

    def test_all_mode_checks_tracked_files(self):
        self.put('a.md', 'someone@gmail.com\n')
        self.git('-c', 'user.email=a@b.c', 'commit', '-q', '--no-verify', '-m', 'x')
        self.assertEqual(self.run_check('--all')[0], 1)

    def test_external_mode_blocks_answer_sheets_and_internal_docs(self):
        self.put('SECURITY_REVIEW.md', '# r\n')
        self.put('docs/notes.md', 'x\n')
        self.put('CLAUDE.md', 'x\n')
        self.put('b.md', '지적 [H-01] 참조\n')
        self.git('-c', 'user.email=a@b.c', 'commit', '-q', '--no-verify', '-m', 'x')
        code, err = self.run_check('--external')
        self.assertEqual(code, 1)
        for needle in ['SECURITY_REVIEW.md', 'docs/notes.md', 'CLAUDE.md', 'b.md:1']:
            self.assertIn(needle, err)
        # 같은 파일이어도 --all 에서는 내용만 본다 (내부 저장소에서는 있어도 되는 파일)
        self.assertEqual(self.run_check('--all')[0], 0)

    def test_personal_author_email_only_warns(self):
        self.git('config', 'user.email', 'me@kakao.com')
        self.put('a.py', 'x = 1\n')
        code, err = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn('경고', err)


if __name__ == '__main__':
    unittest.main()
