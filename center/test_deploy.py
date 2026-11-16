"""배포 설정 시험. 설정은 import 시점에 정해지므로 환경변수를 바꿔 새 프로세스로 읽는다."""
import importlib
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from django.urls import clear_url_caches, reverse

ROOT = Path(__file__).resolve().parent.parent


def _settings(**env):
    """주어진 환경변수로 config.settings 를 읽어 (종료코드, 출력) 을 돌려준다."""
    e = {**os.environ, 'DJANGO_DEBUG': '0', 'DJANGO_SECRET_KEY': 'x' * 60, **env}
    code = ("import config.settings as s;"
            "print(s.ADMIN_PATH, s.MIDDLEWARE[1], getattr(s,'SECURE_PROXY_SSL_HEADER',None))")
    r = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=e, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


class AdminPathTests(SimpleTestCase):
    def test_admin_path_follows_setting(self):
        import config.urls
        try:
            with override_settings(ADMIN_PATH='secret-x/'):
                importlib.reload(config.urls)
                clear_url_caches()
                self.assertEqual(reverse('admin:index'), '/secret-x/')
        finally:
            importlib.reload(config.urls)
            clear_url_caches()
        self.assertEqual(reverse('admin:index'), '/admin/')

    def test_bad_admin_path_refuses_to_start(self):
        for bad in ('/admin/', 'admin'):
            self.assertNotEqual(_settings(DJANGO_ADMIN_PATH=bad)[0], 0, bad)


class ProductionSettingsTests(SimpleTestCase):
    def test_production_serves_static_with_whitenoise_and_no_proxy_header_by_default(self):
        code, out = _settings()
        self.assertEqual(code, 0)
        self.assertEqual(out, 'admin/ whitenoise.middleware.WhiteNoiseMiddleware None')

    def test_proxy_header_only_when_opted_in(self):
        code, out = _settings(DJANGO_BEHIND_PROXY='1')
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("('HTTP_X_FORWARDED_PROTO', 'https')"), out)
