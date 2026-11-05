from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Attendance, Child, NotifyLog


class PageTests(TestCase):
    def test_public_pages_ok(self):
        for url in ['/', '/notices/', '/programs/', '/about/', '/attendance/']:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_board_requires_login(self):
        self.assertEqual(self.client.get('/attendance/board/').status_code, 302)


class KioskTests(TestCase):
    def setUp(self):
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


class BoardTests(TestCase):
    def setUp(self):
        self.child = Child.objects.create(name='홍길동', number=7, code='27421',
                                          guardian_tel='010-0000-0000')
        User.objects.create_superuser('staff', 'a@b.c', 'pw')
        self.client.login(username='staff', password='pw')

    def test_code_and_number_both_work(self):
        # 인식번호(보호자 뒷자리+남매 순번)로 찾기
        self.assertIn('입실', self.client.post('/attendance/', {'number': '27421'}).context['message'])
        # 출석번호로 찾기 — 같은 아이이므로 이번엔 퇴실이 된다
        self.assertIn('퇴실', self.client.post('/attendance/', {'number': '7'}).context['message'])

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
