from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase


class SecurityLogTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser('staff', 'a@b.c', 'pw')

    def test_failed_login_is_not_logged(self):
        # [실습 A09] 로그인 실패가 기록되지 않는다 — 무차별 대입 시도가 로그에 안 남는다.
        with self.assertNoLogs('center.security', 'WARNING'):
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'SecretWrong1'})

    def test_successful_login_logs_user_id_only(self):
        with self.assertLogs('center.security', 'INFO') as cm:
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'pw'})
        self.assertRegex(cm.output[0], r'login_ok ip=\S+ user_id=\d+$')

    def test_csv_export_is_not_logged(self):
        # [실습 A09] CSV 내보내기가 기록되지 않는다 — 누가 받아 갔는지 로그에 안 남는다.
        self.client.login(username='staff', password='pw')
        with self.assertNoLogs('center.security', 'INFO'):
            self.client.get('/attendance/export/?month=2026-03')

    def test_board_view_is_not_logged_but_my_view_still_is(self):
        # [실습 A09] 현황판 열람은 기록되지 않지만, 보호자의 /my/ 열람은 그대로 남는다.
        from .models import Child
        Child.objects.create(number=1, name='홍길동')
        self.client.login(username='staff', password='pw')
        with self.assertNoLogs('center.security', 'INFO'):
            self.client.get('/attendance/board/?date=2026-03-14')
        with self.assertLogs('center.security', 'INFO') as cm:
            self.client.get('/my/')
        self.assertIn('my_view', cm.output[0])

    def test_csv_import_is_not_logged(self):
        # [실습 A09] 명단 가져오기가 기록되지 않는다 — 누가 바꿨는지 로그에 안 남는다.
        self.client.login(username='staff', password='pw')
        f = SimpleUploadedFile('a.csv', '출석번호,이름,인식번호,보호자연락처\n1,홍길동,,\n'.encode())
        with self.assertNoLogs('center.security', 'INFO'):
            self.client.post('/attendance/import/', {'file': f, 'save': '1'})
