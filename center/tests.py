import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Attendance, AttendanceLog, CenterInfo, Child, Notice, NotifyLog, Upload


class PageTests(TestCase):
    def test_public_pages_ok(self):
        for url in ['/', '/notices/', '/programs/', '/about/', '/attendance/']:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_board_requires_login(self):
        self.assertEqual(self.client.get('/attendance/board/').status_code, 302)


class NoticeFormatTests(TestCase):
    def render(self, body):
        n = Notice.objects.create(title='t', body=body)
        return self.client.get(f'/notices/{n.pk}/').content.decode()

    def test_supported_formatting(self):
        html = self.render('## 소제목\n\n**중요** 안내입니다\n둘째 줄\n\n- 가\n- 나')
        self.assertIn('<h3>소제목</h3>', html)
        self.assertIn('<p><strong>중요</strong> 안내입니다<br>둘째 줄</p>', html)
        self.assertIn('<ul><li>가</li><li>나</li></ul>', html)

    def test_html_in_the_body_is_not_escaped(self):
        # [실습 A05] 본문의 HTML 이 글자가 아니라 태그로 나간다. main 에서는 글자 그대로 보인다.
        html = self.render('<b id="practice-marker">굵게</b>')
        self.assertIn('<b id="practice-marker">굵게</b>', html)

    def test_links_are_not_turned_into_anchors(self):
        html = self.render('[클릭](javascript:alert(1)) https://example.com')
        self.assertNotIn('<a href="javascript', html)
        self.assertNotIn('<a href="https://example.com', html)

    def test_empty_body_does_not_break(self):
        self.assertEqual(self.render('').count('<h1>'), 1)


class NoticeSearchTests(TestCase):
    def setUp(self):
        Notice.objects.create(title='봄 소풍 안내', body='4월에 공원으로 갑니다')
        Notice.objects.create(title='급식 안내', body='이번 주 메뉴는 비빔밥')

    def get(self, q):
        return self.client.get('/notices/', {'q': q}).content.decode()

    def test_searches_title_and_body(self):
        self.assertIn('봄 소풍 안내', self.get('소풍'))
        self.assertNotIn('급식 안내', self.get('소풍'))
        self.assertIn('급식 안내', self.get('비빔밥'))

    def test_no_match_and_empty_query(self):
        self.assertIn('해당하는 공지가 없습니다', self.get('없는말'))
        body = self.get('')
        self.assertIn('봄 소풍 안내', body)
        self.assertIn('급식 안내', body)

    def test_search_term_is_part_of_the_sql_text(self):
        # [실습 A05] 검색어가 SQL 문장에 이어 붙으므로 조건이 바뀌어 없는 글자로도 전부 나온다.
        # main 에서는 이 글자를 그대로 찾기 때문에 아무것도 나오지 않는다.
        body = self.get("없는말%' OR 1=1 --")
        self.assertIn('봄 소풍 안내', body)
        self.assertIn('급식 안내', body)

    def test_nul_character_does_not_match_everything(self):
        # SQLite 의 LIKE 는 NUL 에서 패턴이 끊겨 전부 일치해 버린다. 뺀 뒤 나머지 글자로 찾는다.
        body = self.get('\x00소풍')
        self.assertIn('봄 소풍 안내', body)
        self.assertNotIn('급식 안내', body)

    def test_query_is_escaped_in_the_page(self):
        body = self.get('<script>alert(1)</script>')
        self.assertNotIn('<script>alert(1)</script>', body)
        self.assertIn('&lt;script&gt;', body)

    def test_pager_keeps_the_query(self):
        for i in range(11):
            Notice.objects.create(title=f'행사 {i}', body='x')
        body = self.client.get('/notices/', {'q': '행사'}).content.decode()
        self.assertIn('?q=%ED%96%89%EC%82%AC&amp;page=2', body)


class VulnSafetyTests(TestCase):
    def test_banner_is_shown_on_every_page(self):
        for url in ['/', '/notices/', '/login/']:
            self.assertIn('실습용 취약 버전', self.client.get(url).content.decode(), url)

    def test_non_local_hosts_stop_the_app_from_starting(self):
        code = "import config.settings"
        env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'DJANGO_ALLOWED_HOSTS': 'example.com'}
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                           cwd=settings.BASE_DIR, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('로컬 전용', r.stderr)

    def test_compose_publishes_ports_on_loopback_only(self):
        text = (Path(settings.BASE_DIR) / 'docker-compose.yml').read_text(encoding='utf-8')
        ports = re.findall(r'^\s*-\s*"?([0-9.:]+:\d+:\d+)"?\s*$', text, flags=re.M)
        self.assertTrue(ports, 'ports 항목을 찾지 못했다')
        for p in ports:
            self.assertTrue(p.startswith('127.0.0.1:'), p)

    def test_seed_refuses_to_run_when_debug_is_off(self):
        from django.core.management import CommandError, call_command
        with self.assertRaises(CommandError):
            call_command('seed_dummy', verbosity=0)    # 테스트 러너는 DEBUG=False 로 돈다
        self.assertEqual(Child.objects.count(), 0)

    @override_settings(DEBUG=True)
    def test_seed_is_dummy_only_and_repeatable(self):
        from django.core.management import call_command
        call_command('seed_dummy', verbosity=0)
        first = (Child.objects.count(), Notice.objects.count())
        call_command('seed_dummy', verbosity=0)
        self.assertEqual((Child.objects.count(), Notice.objects.count()), first)
        admin = User.objects.get(username='admin')   # [실습 A02] 흔한 기본 관리자 계정
        self.assertTrue(admin.is_superuser and admin.check_password('admin1234'))
        for c in Child.objects.all():
            self.assertTrue(c.guardian_tel.startswith('010-0000-'), c.guardian_tel)
            self.assertTrue(c.name.startswith('모의아동'), c.name)


class WeakHashTests(TestCase):
    """[실습] 비밀번호가 MD5 로 저장된다 (A04). main 에서는 PBKDF2 임을 확인하는 시험이다."""

    def test_passwords_are_stored_with_md5(self):
        user = User.objects.create_user('someone', password='pw-for-test')
        self.assertTrue(user.password.startswith('md5$'), user.password[:6])
        self.assertTrue(user.check_password('pw-for-test'))



@unittest.skipIf(Path(settings.BASE_DIR, 'docs', 'vuln-manifest.md').exists(), 'vuln 갈래는 일부러 취약하다')
class DeployCheckTests(TestCase):
    def test_django_deploy_check_has_no_issues_in_production_mode(self):
        env = {**os.environ, 'DJANGO_DEBUG': '0',
               'DJANGO_SECRET_KEY': 'test-only-key-test-only-key-test-only-key-0123456789'}
        r = subprocess.run([sys.executable, 'manage.py', 'check', '--deploy', '--fail-level', 'WARNING'],
                           cwd=settings.BASE_DIR, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class CenterInfoTests(TestCase):
    def test_seeded_from_settings_by_migration(self):
        self.assertEqual(CenterInfo.objects.count(), 1)
        self.assertIn('지역아동센터', self.client.get('/').content.decode())

    def test_edit_in_db_shows_on_pages(self):
        CenterInfo.objects.update(name='새이름센터', tel='031-111-2222')
        for url in ['/', '/about/']:
            body = self.client.get(url).content.decode()
            self.assertIn('새이름센터', body, url)
            self.assertIn('031-111-2222', body, url)

    def test_falls_back_to_settings_when_no_row(self):
        CenterInfo.objects.all().delete()
        self.assertIn('지역아동센터', self.client.get('/').content.decode())

    def test_admin_cannot_add_a_second_row_or_delete(self):
        User.objects.create_superuser('boss', 'a@b.c', 'pw')
        self.client.login(username='boss', password='pw')
        self.assertEqual(self.client.get('/admin/center/centerinfo/add/').status_code, 403)
        row = CenterInfo.objects.get()
        self.assertEqual(self.client.get(f'/admin/center/centerinfo/{row.pk}/delete/').status_code, 403)


class AttendanceLogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.child = Child.objects.create(name='홍길동', number=7)
        self.staff = User.objects.create_superuser('staff', 'a@b.c', 'pw')

    def test_kiosk_in_and_out_are_logged_without_a_user(self):
        self.client.post('/attendance/', {'number': '7'})
        self.client.post('/attendance/', {'number': '7'})
        logs = list(AttendanceLog.objects.order_by('id'))
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].before, '')
        self.assertIn('퇴실 -', logs[0].after)
        self.assertNotIn('퇴실 -', logs[1].after)
        self.assertTrue(all(l.via == 'kiosk' and l.by is None for l in logs))

    def test_board_edit_logs_before_after_and_who(self):
        self.client.login(username='staff', password='pw')
        data = {'child': self.child.pk, 'date': '2026-03-14', 'check_in': '14:30', 'status': '출석'}
        self.client.post('/attendance/board/', data)
        self.client.post('/attendance/board/', {**data, 'check_in': '15:00', 'status': '조퇴'})
        last = AttendanceLog.objects.first()
        self.assertIn('입실 14:30', last.before)
        self.assertIn('입실 15:00', last.after)
        self.assertIn('조퇴', last.after)
        self.assertEqual(last.by, self.staff)
        self.assertEqual(last.via, 'staff')

    def test_unchanged_save_leaves_no_log(self):
        self.client.login(username='staff', password='pw')
        data = {'child': self.child.pk, 'date': '2026-03-14', 'check_in': '14:30'}
        self.client.post('/attendance/board/', data)
        before = AttendanceLog.objects.count()
        self.client.post('/attendance/board/', data)
        self.assertEqual(AttendanceLog.objects.count(), before)

    def test_admin_edit_is_logged(self):
        rec = Attendance.objects.create(child=self.child, date='2026-03-14', status='출석')
        self.client.login(username='staff', password='pw')
        self.client.post(f'/admin/center/attendance/{rec.pk}/change/', {
            'child': self.child.pk, 'date': '2026-03-14', 'status': '결석',
            'source': 'staff', 'note': ''})
        log = AttendanceLog.objects.get()
        self.assertIn('출석', log.before)
        self.assertIn('결석', log.after)
        self.assertEqual((log.via, log.by), ('admin', self.staff))

    def test_log_is_read_only_and_survives_record_deletion(self):
        rec = Attendance.objects.create(child=self.child, date='2026-03-14')
        AttendanceLog.add(rec, '', 'admin', self.staff)
        self.client.login(username='staff', password='pw')
        log = AttendanceLog.objects.get()
        self.assertEqual(self.client.get('/admin/center/attendancelog/add/').status_code, 403)
        self.assertEqual(self.client.get(f'/admin/center/attendancelog/{log.pk}/delete/').status_code, 403)
        rec.delete()
        log.refresh_from_db()
        self.assertIsNone(log.attendance)
        self.assertIn('홍길동', log.label)


class KioskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.child = Child.objects.create(name='홍길동', number=7, guardian_tel='010-0000-0000')

    def post(self, number):
        return self.client.post('/attendance/', {'number': number}).context['message']

    def test_toggle_in_then_out_then_blocked(self):
        self.assertIn('입실', self.post(7))
        rec = Attendance.objects.get(child=self.child, date=timezone.localdate())
        self.assertIsNotNone(rec.check_in)
        self.assertIn('퇴실', self.post(7))
        rec.refresh_from_db()
        self.assertIsNotNone(rec.check_out)
        self.assertIn('이미 퇴실', self.post(7))
        self.assertEqual(Attendance.objects.count(), 1)

    def test_unknown_number(self):
        self.assertIn('없는', self.post(99))

    def test_malformed_input_is_not_a_server_error(self):
        # 윗첨자 숫자는 isdigit() 은 True 인데 int() 는 실패한다. 5000자리는 정수 변환 제한에 걸린다.
        for bad in ['²', '9' * 5000, 'abc']:
            self.assertIn('없는', self.post(bad))
        resp = self.client.post('/attendance/', {'child': 'abc'})
        self.assertIn('없는', resp.context['message'])


class NoLockoutTests(TestCase):
    """[실습] 시도 횟수 제한이 없다 — 틀려도 잠기지 않는다 (A07). main 에서는 이 시험이 반대로 쓰여 있다."""

    def setUp(self):
        User.objects.create_superuser('staff', 'a@b.c', 'pw')

    def test_login_never_locks_after_many_failures(self):
        for _ in range(40):
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'wrong'})
        resp = self.client.post('/admin/login/', {'username': 'staff', 'password': 'pw'})
        self.assertEqual(resp.status_code, 302)

    def test_kiosk_never_locks_after_many_misses(self):
        child = Child.objects.create(name='홍길동', number=7)
        for _ in range(30):
            self.client.post('/attendance/', {'number': '99'})
        msg = self.client.post('/attendance/', {'number': '7'}).context['message']
        self.assertIn('입실', msg)
        self.assertTrue(Attendance.objects.filter(child=child).exists())


class GuardianTests(TestCase):
    def setUp(self):
        cache.clear()
        self.mom = User.objects.create_user('mom', password='pw1')
        self.dad = User.objects.create_user('dad', password='pw2')
        self.mine = Child.objects.create(name='내아이', number=1, guardian=self.mom)
        self.other = Child.objects.create(name='남의아이', number=2, guardian=self.dad)
        today = timezone.localdate()
        Attendance.objects.create(child=self.mine, date=today, status='출석', note='병원비밀메모')
        Attendance.objects.create(child=self.other, date=today, status='결석')

    def test_my_requires_login(self):
        resp = self.client.get('/my/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/login/'))

    def test_guardian_login_goes_to_my(self):
        resp = self.client.post('/login/', {'username': 'mom', 'password': 'pw1'})
        self.assertRedirects(resp, '/my/', fetch_redirect_response=False)

    def test_sees_only_own_child_and_no_staff_note(self):
        self.client.login(username='mom', password='pw1')
        body = self.client.get('/my/').content.decode()
        self.assertIn('내아이', body)
        self.assertNotIn('남의아이', body)
        self.assertNotIn('병원비밀메모', body)

    def test_guardian_without_child_sees_empty_message(self):
        User.objects.create_user('nobody', password='pw3')
        self.client.login(username='nobody', password='pw3')
        self.assertIn('연결된 아이가 없습니다', self.client.get('/my/').content.decode())

    def test_guardian_cannot_open_the_board(self):
        self.client.login(username='mom', password='pw1')
        resp = self.client.get('/attendance/board/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/login/', resp.url)

    def test_csv_export_is_open_to_anyone(self):
        # [실습 A01] 로그인하지 않아도 월별 출결 CSV 를 받는다. main 에서는 직원 로그인 화면으로 보낸다.
        resp = self.client.get('/attendance/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('내아이', resp.content.decode('utf-8-sig'))

    def test_guardian_can_read_another_childs_records_by_id(self):
        # [실습 A01] 남의 아이 번호를 주소에 넣어도 보인다. main 에는 이 주소 자체가 없다.
        self.client.login(username='mom', password='pw1')
        body = self.client.get(f'/my/{self.other.pk}/').content.decode()
        self.assertIn('남의아이', body)

    def test_guardian_login_has_no_lockout(self):
        for _ in range(10):
            self.client.post('/login/', {'username': 'mom', 'password': 'wrong'})
        resp = self.client.post('/login/', {'username': 'mom', 'password': 'pw1'})
        self.assertEqual(resp.status_code, 302)


class BoardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.child = Child.objects.create(name='홍길동', number=7, code='27421',
                                          guardian_tel='010-0000-0000')
        User.objects.create_superuser('staff', 'a@b.c', 'pw')
        self.client.login(username='staff', password='pw')

    def test_code_and_number_both_work(self):
        # 인식번호(보호자 뒷자리+남매 순번)로 찾기
        self.assertIn('입실', self.client.post('/attendance/', {'number': '27421'}).context['message'])
        # 출석번호로 찾기 — 같은 아이이므로 이번엔 퇴실이 된다
        self.assertIn('퇴실', self.client.post('/attendance/', {'number': '7'}).context['message'])

    def test_status_outside_choices_is_rejected(self):
        self.client.post('/attendance/board/', {
            'child': self.child.pk, 'date': '2026-03-14', 'check_in': '09:00', 'status': '아무거나'})
        self.assertFalse(Attendance.objects.exists())
        self.client.post('/attendance/board/', {
            'child': self.child.pk, 'date': '2026-03-14', 'check_in': '09:00', 'status': '병가'})
        self.assertEqual(Attendance.objects.get().status, '병가')

    @override_settings(DEBUG=True)
    def test_board_post_without_child_crashes_and_shows_internals(self):
        # [실습 A10] 항목이 없으면 404 가 아니라 500 이고, DEBUG 화면에 예외 이름과 코드가 보인다.
        client = Client(raise_request_exception=False)
        client.login(username='staff', password='pw')
        resp = client.post('/attendance/board/', {})
        self.assertEqual(resp.status_code, 500)
        self.assertIn('MultiValueDictKeyError', resp.content.decode())
        self.assertEqual(self.client.post('/attendance/board/', {'child': '999'}).status_code, 404)

    def test_tile_click(self):
        msg = self.client.post('/attendance/', {'child': self.child.pk}).context['message']
        self.assertIn('입실', msg)

    def test_manual_edit_on_past_date(self):
        self.client.post('/attendance/board/', {
            'child': self.child.pk, 'date': '2026-03-14',
            'check_in': '14:30', 'check_out': '18:00', 'status': '조퇴', 'note': '병원'})
        rec = Attendance.objects.get(child=self.child, date='2026-03-14')
        self.assertEqual(timezone.localtime(rec.check_in).strftime('%H:%M'), '14:30')
        self.assertEqual(rec.status, '조퇴')
        self.assertEqual(rec.note, '병원')
        # 지난 날짜 보정은 "지금 도착했습니다" 알림을 보내면 안 된다
        self.assertEqual(NotifyLog.objects.count(), 0)

    def test_board_shows_requested_date(self):
        res = self.client.get('/attendance/board/?date=2026-03-14')
        self.assertEqual(res.context['date'].isoformat(), '2026-03-14')

    def test_bad_date_falls_back_to_today(self):
        res = self.client.get('/attendance/board/?date=notadate')
        self.assertEqual(res.context['date'], timezone.localdate())

    def test_csv_export(self):
        self.client.post('/attendance/board/', {
            'child': self.child.pk, 'date': '2026-03-14',
            'check_in': '14:30', 'check_out': '18:00', 'status': '출석', 'note': ''})
        res = self.client.get('/attendance/export/?month=2026-03')
        body = res.content.decode('utf-8')
        self.assertTrue(body.startswith('﻿'))   # 엑셀 한글 깨짐 방지
        self.assertIn('홍길동', body)
        self.assertIn('14:30', body)
        self.assertNotIn('2026-04', body)


class CsvSafetyTests(TestCase):
    def test_formula_is_neutralised(self):
        from .views import _csv_safe
        # 엑셀이 수식으로 실행하는 네 가지 시작 문자
        for bad in ['=1+1', '+1', '-1', '@SUM(A1)']:
            self.assertTrue(_csv_safe(bad).startswith("'"), bad)
        # 평범한 값은 건드리지 않는다
        self.assertEqual(_csv_safe('병원 진료'), '병원 진료')
        self.assertEqual(_csv_safe(''), '')


class VulnSignupTests(TestCase):
    """[실습 A06] 전화 인증 가입이 취약하게 심겼는지 확인한다. main 에는 이 화면이 없다."""

    def test_code_is_shown_in_the_response_and_is_three_digits(self):
        # [실습 A06] 보낸 인증번호가 화면에 그대로 보이고, 3자리라 쉽게 맞힌다.
        resp = self.client.post('/signup/', {'phone': '010-0000-0001'})
        m = re.search(r'인증번호 (\d+) 를', resp.content.decode())
        self.assertIsNotNone(m, '인증번호가 화면에 보이지 않는다')
        self.assertEqual(len(m.group(1)), 3)

    def test_no_attempt_limit_and_signup_completes(self):
        # [실습 A06] 틀린 번호를 수십 번 보내도 잠기지 않고, 맞히면 그대로 가입된다.
        first = self.client.post('/signup/', {'phone': '010-0000-0002'})
        code = re.search(r'인증번호 (\d+) 를', first.content.decode()).group(1)
        wrong = '000' if code != '000' else '111'
        for _ in range(50):
            resp = self.client.post('/signup/', {'phone': '010-0000-0002', 'code': wrong})
        self.assertIn('틀렸습니다', resp.content.decode())
        done = self.client.post('/signup/', {'phone': '010-0000-0002', 'code': code})
        self.assertIn('가입이 완료', done.content.decode())
        self.assertTrue(User.objects.filter(username='010-0000-0002').exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VulnA08Tests(TestCase):
    """[실습 A08] role 쿠키 권한 상승과 검사 없는 서류 업로드. main 에는 둘 다 없다."""

    def setUp(self):
        cache.clear()
        self.mom = User.objects.create_user('mom', password='pw1')
        Child.objects.create(name='내아이', number=1, guardian=self.mom)
        self.client.login(username='mom', password='pw1')

    def test_role_cookie_lets_a_guardian_into_the_staff_board(self):
        # 쿠키가 없으면 보호자는 직원 현황판에서 막힌다
        self.assertEqual(self.client.get('/attendance/board/').status_code, 302)
        # [실습 A08] 서명 없는 role=staff 쿠키만 심으면 직원 화면에 들어온다
        self.client.cookies['role'] = 'staff'
        self.assertEqual(self.client.get('/attendance/board/').status_code, 200)

    def test_upload_accepts_a_dangerous_file_without_validation(self):
        evil = SimpleUploadedFile('shell.html', b'<script>alert(1)</script>', content_type='text/html')
        self.client.post('/my/', {'doc': evil})
        up = Upload.objects.get()
        # [실습 A08] 형식 검사가 없어 .html 도 그대로 저장되고 원래 이름을 유지한다
        self.assertTrue(up.file.name.endswith('shell.html'), up.file.name)
