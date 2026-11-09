"""실습용 더미 데이터를 넣는다. 전부 가짜 값이다.

실제 아동 이름·연락처를 넣지 않는다. 여러 번 돌려도 같은 결과가 되게 만들었다.
DEBUG 가 꺼진 환경(운영 설정)에서는 돌지 않는다.
"""
from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from center.models import Attendance, Child, Notice, Program


class Command(BaseCommand):
    help = '실습용 더미 아동·공지·프로그램·출결을 넣는다 (여러 번 실행해도 안전)'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('DEBUG 가 꺼진 환경에서는 더미 데이터를 넣지 않습니다.')

        children = []
        for i in range(1, 7):
            child, _ = Child.objects.get_or_create(
                number=i, defaults={'name': f'모의아동{i:02d}', 'code': f'{1000 + i}',
                                    'guardian_tel': f'010-0000-{i:04d}'})
            children.append(child)

        for title, body, pinned in [
            ('실습용 안내', '이 사이트는 웹 보안 실습용 모의 사이트입니다.', True),
            ('봄 소풍 안내', '4월에 공원으로 갑니다.\n준비물: 도시락, 물통', False),
            ('급식 안내', '이번 주 메뉴는 비빔밥입니다.', False)]:
            Notice.objects.get_or_create(title=title, defaults={'body': body, 'pinned': pinned})

        for order, (name, schedule) in enumerate([
            ('독서 교실', '월·수 16:00'), ('미술 놀이', '화 15:30'),
            ('체육 활동', '목 16:00'), ('학습 도우미', '금 15:00')]):
            Program.objects.get_or_create(name=name, defaults={'schedule': schedule, 'order': order})

        # [실습 A02] 기본 관리자 계정 — 이름과 비밀번호가 문서화된 흔한 값이다. main 의 시드에는 없다.
        get_user_model().objects.filter(username='admin').exists() or \
            get_user_model().objects.create_superuser('admin', 'admin@example.com', 'admin1234')

        yesterday = timezone.localdate() - timedelta(days=1)
        tz = timezone.get_current_timezone()
        for child in children[:4]:
            Attendance.objects.get_or_create(
                child=child, date=yesterday,
                defaults={'check_in': timezone.datetime.combine(yesterday, time(13, 0), tzinfo=tz),
                          'check_out': timezone.datetime.combine(yesterday, time(18, 0), tzinfo=tz),
                          'source': Attendance.BY_STAFF})

        self.stdout.write(self.style.SUCCESS(
            f'더미 데이터: 아동 {Child.objects.count()}, 공지 {Notice.objects.count()}, '
            f'프로그램 {Program.objects.count()}, 출결 {Attendance.objects.count()}'))
