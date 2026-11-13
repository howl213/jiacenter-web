from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase


class SecurityLogTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser('staff', 'a@b.c', 'pw')

    def test_failed_login_is_logged_without_username_or_password(self):
        with self.assertLogs('center.security', 'WARNING') as cm:
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'SecretWrong1'})
        line = cm.output[0]
        self.assertIn('login_failed', line)
        self.assertNotIn('staff', line)
        self.assertNotIn('SecretWrong1', line)

    def test_successful_login_logs_user_id_only(self):
        with self.assertLogs('center.security', 'INFO') as cm:
            self.client.post('/admin/login/', {'username': 'staff', 'password': 'pw'})
        self.assertRegex(cm.output[0], r'login_ok ip=\S+ user_id=\d+$')

    def test_csv_export_is_logged(self):
        self.client.login(username='staff', password='pw')
        with self.assertLogs('center.security', 'INFO') as cm:
            self.client.get('/attendance/export/?month=2026-03')
        self.assertIn('csv_export', cm.output[0])
        self.assertIn('month=2026-03', cm.output[0])

    def test_board_and_my_views_are_logged_without_names(self):
        from .models import Child
        Child.objects.create(number=1, name='홍길동')
        self.client.login(username='staff', password='pw')
        with self.assertLogs('center.security', 'INFO') as cm:
            self.client.get('/attendance/board/?date=2026-03-14')
            self.client.get('/my/')
        self.assertIn('board_view', cm.output[0])
        self.assertIn('date=2026-03-14', cm.output[0])
        self.assertIn('my_view', cm.output[1])
        self.assertNotIn('홍길동', ''.join(cm.output))

    def test_csv_import_is_logged_with_counts_only(self):
        self.client.login(username='staff', password='pw')
        f = SimpleUploadedFile('a.csv', '출석번호,이름,인식번호,보호자연락처\n1,홍길동,,\n'.encode())
        with self.assertLogs('center.security', 'INFO') as cm:
            self.client.post('/attendance/import/', {'file': f, 'save': '1'})
        self.assertIn('csv_import', cm.output[0])
        self.assertIn('saved=True rows=1', cm.output[0])
        self.assertNotIn('홍길동', cm.output[0])
