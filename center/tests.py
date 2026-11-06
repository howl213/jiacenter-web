from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .models import Attendance, CenterInfo, Child, NotifyLog


class PageTests(TestCase):
    def test_public_pages_ok(self):
        for url in ['/', '/notices/', '/programs/', '/about/', '/attendance/']:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_board_requires_login(self):
        self.assertEqual(self.client.get('/attendance/board/').status_code, 302)


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


class ThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser('staff', 'a@b.c', 'pw')

    def test_kiosk_locks_after_repeated_misses(self):
        child = Child.objects.create(name='홍길동', number=7)
        for _ in range(10):
            self.client.post('/attendance/', {'number': '99'})
        msg = self.client.post('/attendance/', {'number': '7'}).context['message']
        self.assertIn('잠시 후', msg)
        self.assertFalse(Attendance.objects.filter(child=child).exists())

    def test_login_locks_even_correct_password_after_failures(self):
        for _ in range(5):
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'wrong'})
        resp = self.client.post('/admin/login/', {'username': 'staff', 'password': 'pw'})
        self.assertEqual(resp.status_code, 429)

    def test_other_account_on_same_ip_is_not_locked(self):
        User.objects.create_user('other', password='pw2', is_staff=True)
        for _ in range(5):
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'wrong'})
        resp = self.client.post('/admin/login/', {'username': 'other', 'password': 'pw2'})
        self.assertEqual(resp.status_code, 302)

    def test_success_resets_the_count(self):
        for _ in range(4):
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'wrong'})
        self.client.post('/admin/login/', {'username': 'staff', 'password': 'pw'})
        self.client.logout()
        for _ in range(4):
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'wrong'})
        resp = self.client.post('/admin/login/', {'username': 'staff', 'password': 'pw'})
        self.assertEqual(resp.status_code, 302)

    def test_changing_usernames_hits_the_ip_limit(self):
        for i in range(30):
            self.client.post('/admin/login/', {'username': f'guess{i}', 'password': 'x'})
        resp = self.client.post('/admin/login/', {'username': 'staff', 'password': 'pw'})
        self.assertEqual(resp.status_code, 429)

    def test_login_still_works_before_limit(self):
        for _ in range(4):
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'wrong'})
        resp = self.client.post('/admin/login/', {'username': 'staff', 'password': 'pw'})
        self.assertEqual(resp.status_code, 302)


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

    def test_guardian_cannot_open_staff_pages(self):
        self.client.login(username='mom', password='pw1')
        for url in ['/attendance/board/', '/attendance/export/']:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn('/admin/login/', resp.url, url)

    def test_guardian_login_is_throttled_too(self):
        for _ in range(5):
            self.client.post('/login/', {'username': 'mom', 'password': 'wrong'})
        resp = self.client.post('/login/', {'username': 'mom', 'password': 'pw1'})
        self.assertEqual(resp.status_code, 429)


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

    def test_board_post_without_valid_child_is_404(self):
        for data in [{}, {'child': 'abc'}, {'child': '999'}]:
            self.assertEqual(self.client.post('/attendance/board/', data).status_code, 404, data)

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
