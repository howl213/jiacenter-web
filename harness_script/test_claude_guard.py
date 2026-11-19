"""claude_guard.py 가 막을 것은 막고 묻을 것은 묻고 나머지는 통과시키는지 확인한다.

실행: python -m unittest discover -s harness_script
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


def run_raw(stdin):
    """훅 입력 자체가 깨진 경우를 흉내 낸다."""
    r = subprocess.run(['python3', str(GUARD)], input=stdin, capture_output=True, text=True)
    if r.returncode == 2:
        return 'BLOCK'
    return 'ASK' if '"permissionDecision": "ask"' in r.stdout else 'PASS'


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ours = Path(cls.tmp.name) / 'ours'
        cls.other = Path(cls.tmp.name) / 'other'
        cls.main_repo = Path(cls.tmp.name) / 'mainrepo'
        for d, url, branch in [(cls.ours, 'https://github.com/howl213/jiacenter-web.git', 'work'),
                               (cls.other, 'https://github.com/someone/else.git', 'work'),
                               (cls.main_repo, 'https://github.com/howl213/jiacenter-web.git', 'main')]:
            d.mkdir()
            subprocess.run(['git', 'init', '-q', '-b', branch], cwd=d, check=True)
            subprocess.run(['git', 'remote', 'add', 'origin', url], cwd=d, check=True)
        (Path(cls.tmp.name) / 'notrepo').mkdir()   # git 저장소가 아닌 폴더

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

    def test_commands_that_change_the_local_db_ask(self):
        for cmd in ['.venv/bin/python manage.py seed_dummy', 'python manage.py flush --noinput',
                    'python manage.py loaddata x.json', 'python manage.py createsuperuser',
                    'sqlite3 db.sqlite3 "select * from center_child"']:
            self.check('ASK', cmd)
        # 컨테이너 안에서 도는 것은 로컬 DB 가 아니다
        self.check('PASS', 'docker compose exec -T web python manage.py seed_dummy')
        self.check('PASS', '.venv/bin/python manage.py check')

    def test_hard_to_undo_git_commands_ask(self):
        for cmd in ['git reset --hard HEAD~1', 'git clean -fd', 'git branch -D old', 'git rebase main',
                    'git filter-repo --path x', 'git push origin --delete old']:
            self.check('ASK', cmd)
        self.check('PASS', 'git branch -d merged')       # 병합된 것만 지우는 소문자 -d 는 통과
        self.check('PASS', 'git status')

    def test_merge_export_and_main_edits_ask(self):
        self.check('ASK', 'gh pr merge 5 --squash')
        self.check('ASK', 'python3 harness_script/export_for_team.py ~/Desktop/x')
        self.check('ASK', 'git commit -m x', self.main_repo)        # main 위에서
        self.check('ASK', 'git merge feat/x', self.main_repo)
        self.check('ASK', 'git push origin HEAD:main')               # 어느 브랜치에서든 main 으로 가는 푸시
        self.check('PASS', 'git commit -m x')                        # 작업 브랜치에서는 통과

    def test_ordinary_commands_pass(self):
        self.check('PASS', 'ls -la')

    # ---- 아래는 2026-11-18 격리 시험에서 나온 우회 시도. 입력 문자열만 분석하고 실제로 실행하지 않는다. ----

    def test_git_global_options_do_not_hide_the_subcommand(self):
        self.check('ASK', 'git -C /x push --force origin work')
        self.check('ASK', 'git -C /x push -f origin work')
        self.check('ASK', 'git -C /x reset --hard HEAD~1')
        self.check('ASK', 'git -C /x clean -fd')
        self.check('ASK', 'git -C /x branch -D old')
        self.check('ASK', 'git -c user.name=x reset --hard')
        self.check('ASK', 'git push origin +HEAD')                 # +refspec 도 강제 푸시
        self.check('PASS', 'git -C /x status')

    def test_main_protection_follows_the_target_repo(self):
        m = self.main_repo
        self.check('ASK', f'git -C {m} commit -m x')               # cwd 는 work, 대상은 main
        self.check('ASK', f'cd {m} && git commit -m x')
        self.check('ASK', f'git -C {m} merge feat/x')
        self.check('ASK', f'git -C {m} push')
        self.check('PASS', f'git -C {self.ours} commit -m x', cwd=m)     # cwd 가 main 이어도 대상은 work
        self.check('PASS', f'cd {self.ours} && git commit -m x', cwd=m)
        # 읽을 수 없는 경로는 main 인지 알 수 없다 → 묻는다
        self.check('ASK', f'git -C {self.tmp.name}/notrepo commit -m x')
        self.check('ASK', 'git -C /nonexistent commit -m x')
        self.check('ASK', 'git -C "$X" commit -m x')

    def test_remote_is_read_from_the_target_repo(self):
        self.check('ASK', f'git -C {self.other} push -u origin HEAD')    # cwd 는 ours
        self.check('PASS', f'git -C {self.ours} push -u origin HEAD', cwd=self.other)
        self.check('ASK', 'git push origin main')
        self.check('ASK', 'git push origin HEAD:refs/heads/main')
        self.check('PASS', 'git push origin main:feat/x')

    def test_hook_skipping_is_blocked_however_it_is_written(self):
        for cmd in ['git commit -n -m x', 'git commit -nm x', "git commit '--no-verify' -m x",
                    "'git' commit --no-verify -m x", 'git commit "--no-verify" -m x',
                    'git -C /x commit --no-verify -m x', 'git commit -m x --no-verify',
                    'git commit --no-verif -m x',
                    'git -c core.hooksPath=/dev/null commit -m x', 'git -c core.hookspath=/dev/null commit -m x',
                    'git --config-env=core.hooksPath=HP commit -m x',
                    'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x',
                    'git config core.hooksPath /dev/null', 'git config --unset core.hooksPath']:
            self.check('BLOCK', cmd)

    def test_option_letters_inside_values_are_not_options(self):
        for cmd in ['git commit -m "-n 옵션 설명"', 'git commit -m -n', 'git commit -mn', 'git commit -am x',
                    'git commit --amend --no-edit', 'git commit -m x -- -n',
                    'git config core.hooksPath', 'git config core.hooksPath .githooks',
                    'git -c color.ui=always diff']:
            self.check('PASS', cmd)

    def test_inner_commands_of_shell_wrappers_are_checked(self):
        self.check('BLOCK', "bash -c 'git commit --no-verify -m x'")
        self.check('BLOCK', 'sh -c "git commit -n -m x"')
        self.check('BLOCK', "bash <<< 'git commit --no-verify -m x'")
        self.check('ASK', "bash -lc 'git reset --hard'")
        self.check('ASK', "sh -c \"bash -c 'git reset --hard'\"")
        self.check('ASK', "bash -c 'python manage.py migrate'")
        self.check('BLOCK', 'echo hi; git commit --no-verify -m x')
        self.check('BLOCK', 'cd /tmp && env FOO=1 git commit --no-verify -m x')
        self.check('BLOCK', '$(git commit --no-verify -m x)')
        self.check('BLOCK', 'ls || { git commit -n -m x; }')
        # 막을 것과 물을 것이 한 줄에 섞이면 막는 쪽이 이긴다
        self.check('BLOCK', 'git reset --hard && git commit --no-verify -m x')
        # 분석할 수 없는 구조는 보수적으로 묻는다
        self.check('ASK', 'echo "git commit --no-verify" | bash')
        self.check('ASK', "git commit -m 'x")                      # 따옴표가 안 닫힘
        for cmd in ['bash harness_script/verify.sh', 'bash -c "ls -la"', 'sh -c "echo hi"']:
            self.check('PASS', cmd)

    def test_heredoc_into_a_shell_is_executed_but_into_a_file_is_text(self):
        self.check('BLOCK', "bash <<'EOF'\ngit commit --no-verify -m y\nEOF")
        self.check('ASK', "sh <<EOF\ngit reset --hard\nEOF")
        self.check('ASK', "sudo bash -s <<'EOF'\ngit clean -fd\nEOF")
        # heredoc 를 시작한 줄에서 뒤에 이어지는 명령도 본다
        self.check('BLOCK', "cat <<'EOF' && git commit --no-verify -m y\ntext\nEOF")
        # 문서를 쓰는 것은 실행이 아니다. 커밋 메시지를 heredoc 로 넘기는 흔한 모양도 통과
        self.check('PASS', "cat > a.md <<'EOF'\ngit reset --hard\nEOF")
        self.check('PASS', "python3 - <<'EOF'\nprint('git reset --hard')\nEOF")
        self.check('PASS', 'git commit -m "$(cat <<\'EOF\'\n제목\n\n본문 git reset --hard\nEOF\n)"')

    def test_gh_api_write_forms_on_foreign_repos_ask(self):
        foreign = 'repos/SJH910/Web-Hacking/issues'
        for opts in ['-X POST', '-XPOST', '--method POST', '--method=POST', '-X PATCH', '-X delete',
                     '-f title=x', '-F title=x', '-ftitle=x', '--field title=x', '--raw-field title=x',
                     '--input a.json', '-H "Accept: x" -X POST']:
            self.check('ASK', f'gh api {opts} {foreign}')
            self.check('ASK', f'gh api {foreign} {opts}')          # 옵션이 경로 뒤에 와도
        self.check('ASK', 'gh api -X POST /repos/SJH910/Web-Hacking/issues')
        self.check('ASK', 'gh api -X PUT https://api.github.com/repos/SJH910/Web-Hacking/contents/x')
        self.check('ASK', 'gh pr create -RSJH910/Web-Hacking')
        self.check('ASK', 'gh issue list --repo=SJH910/Web-Hacking')
        # 읽기는 통과: 기본 GET, 명시한 GET(필드는 쿼리 문자열이 된다), 우리 저장소, 헤더 값은 경로가 아니다
        for cmd in [f'gh api {foreign}', f'gh api -X GET {foreign} -f state=open',
                    f'gh api --method=GET {foreign} -F per_page=5', 'gh api -X POST repos/howl213/jiacenter-web/issues',
                    f'gh api -H "Accept: application/json" {foreign}', 'gh pr view 5', 'gh issue list']:
            self.check('PASS', cmd)

    def test_unreadable_hook_input_blocks(self):
        for raw in ['', '{not json', '[]', '"git status"', 'null', '{}', '{"tool_input": {}}',
                    '{"tool_input": {"command": 5}}', '{"tool_input": "ls"}']:
            self.assertEqual(run_raw(raw), 'BLOCK', repr(raw))
        # cwd 가 없어도 정상 명령은 통과한다
        self.assertEqual(run_raw(json.dumps({'tool_input': {'command': 'ls'}})), 'PASS')

    def test_normal_work_commands_are_not_flagged(self):
        for cmd in ['git status', 'git log --oneline -5', 'git diff HEAD~1', 'git add src/x.py', 'git checkout -b feat/x',
                    'git push origin HEAD', 'git -C /x log', 'echo "git push --force"', "grep -rn 'reset --hard' docs",
                    'cd src && ../.venv/bin/python manage.py test', 'python3 -m unittest discover -s harness_script',
                    'gh pr create --base main', 'git commit -m "fix: 설명"']:
            self.check('PASS', cmd)


if __name__ == '__main__':
    unittest.main()
