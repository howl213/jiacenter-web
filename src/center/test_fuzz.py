"""모든 화면에 이상한 입력을 자동으로 보내 500 이 나는지 본다.

화면 목록은 URL 설정에서 **자동으로** 찾는다. 새 화면을 만들면 이 시험이 따로 손대지 않아도 같이 점검한다.
이 시험이 보는 것은 "서버 오류(5xx)가 나는가"뿐이다. 보안이 안전하다는 증거가 아니다.
vuln 갈래는 일부러 오류를 내는 곳이 있어 건너뛴다.
"""
import re
import unittest
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import URLPattern, URLResolver, get_resolver

from .models import Attendance, Child, Notice

ODD = ['', ' ', 'abc', '²', '٣', '１', '-1', '0', '9' * 30, '9' * 5000, '1e5', "' OR 1=1 --", '%', '_',
       '\\', '\x00', '😀', '<script>alert(1)</script>', '../../etc/passwd', '2026-02-30', '99:99', '가' * 3000]
KEYS = ['q', 'page', 'date', 'month', 'number', 'child', 'status', 'check_in', 'check_out', 'note',
        'username', 'password', 'next', 'toggle']
INT_VALUES = ['1', '0', '999999999999999999999', '2']


def our_routes():
    """admin 을 뺀 우리 화면의 경로 문자열을 모두 모은다 (<int:x> 같은 자리는 시험값으로 바꾼다)."""
    found = []

    def walk(patterns, prefix):
        for p in patterns:
            route = prefix + str(p.pattern)
            if isinstance(p, URLResolver):
                walk(p.url_patterns, route)
            elif isinstance(p, URLPattern):
                found.append(route)

    walk(get_resolver().url_patterns, '')
    routes = []
    for r in found:
        if r.startswith('admin'):
            continue
        if re.search(r'<(?!int:)', r):
            continue                       # int 외의 변환기는 아직 쓰지 않는다 — 생기면 여기서 걸러져 눈에 띈다
        if '<int:' in r:
            routes += ['/' + re.sub(r'<int:\w+>', v, r) for v in INT_VALUES]
        else:
            routes.append('/' + r)
    return sorted(set(routes))


@unittest.skipIf(Path(settings.BASE_DIR, 'docs', 'vuln-manifest.md').exists(), 'vuln 갈래는 일부러 오류를 낸다')
class RouteFuzzTests(TestCase):
    def setUp(self):
        cache.clear()
        child = Child.objects.create(name='홍길동', number=1, code='2742')
        Notice.objects.create(title='공지', body='본문')
        Attendance.objects.create(child=child, date='2026-03-14')
        self.staff = User.objects.create_user('staff', password='pw', is_staff=True)
        self.guardian = User.objects.create_user('mom', password='pw')
        child.guardian = self.guardian
        child.save()

    def test_discovers_a_reasonable_number_of_routes(self):
        routes = our_routes()
        self.assertGreaterEqual(len(routes), 10, routes)
        for must in ['/', '/notices/', '/attendance/', '/my/']:
            self.assertIn(must, routes)

    def test_no_route_returns_a_server_error_for_odd_input(self):
        failures = []
        for who in [None, 'mom', 'staff']:
            client = Client(raise_request_exception=False)
            if who:
                client.login(username=who, password='pw')
            for url in our_routes():
                for value in ODD:
                    data = {k: value for k in KEYS}
                    for method in ('get', 'post'):
                        resp = getattr(client, method)(url, data)
                        if resp.status_code >= 500:
                            failures.append((who, method.upper(), url, repr(value[:12]), resp.status_code))
                            break
        self.assertEqual(failures[:5], [], f'서버 오류 {len(failures)}건')
