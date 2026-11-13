"""로컬 실습용 모의 데이터를 넣는다. 전부 가짜 값이고, 다시 돌려도 중복되지 않는다.

보호자 계정은 로그인 못 하게 둔다(비밀번호 없음) — IDOR 실습의 "남의 아이" 표적일 뿐,
실습하는 사람은 /signup/ 으로 자기 계정을 직접 만들어 쓴다. 그래서 평문 비밀번호를
코드에 적지 않는다.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from center.models import (Attendance, Child, CenterInfo, Comment, Notice, Post, Program)

GUARDIANS = ['김보호', '이보호', '박보호']
CHILDREN = [
    # (이름, 출석번호, 인식번호, 보호자연락처, 보호자 index)
    # 보호자 연락처는 더미 형식(010-0000-####)으로 둔다 — check_leaks 가 가짜로 인식한다.
    ('김하늘', 1, '2742', '010-0000-2742', 0),
    ('김바다', 2, '27421', '010-0000-2742', 0),
    ('이가을', 3, '5531', '010-0000-5531', 1),
    ('이겨울', 4, '55312', '010-0000-5531', 1),
    ('박소망', 5, '8820', '010-0000-8820', 2),
    ('최나눔', 6, '9103', '010-0000-9103', None),  # 보호자 계정 미연결
]
PROGRAMS = [
    ('방과후 학습', '초등 전학년', '월~금 15:00', '숙제 지도와 보충 학습.'),
    ('토요 문화교실', '전체', '토 10:00', '미술·음악 체험.'),
    ('급식 지원', '전체', '매일', '저녁 급식 제공.'),
]
NOTICES = [
    ('겨울방학 운영 안내', '12월 23일부터 방학 일정으로 운영합니다. 자세한 내용은 센터로 문의해 주세요.', True),
    ('독감 예방 안내', '손 씻기와 마스크 착용을 부탁드립니다.', False),
    ('후원 감사 인사', '## 고맙습니다\n여러분의 후원으로 급식을 이어 갑니다.', False),
    ('학부모 상담 주간', '- 기간: 11월 넷째 주\n- 신청: 담당 선생님께', False),
    ('방과후 프로그램 추가 모집', '토요 문화교실 자리가 남아 추가로 모집합니다.', False),
]
POSTS = [
    ('급식 메뉴 건의합니다', '아이가 김치를 잘 안 먹어서요, 반찬 하나만 더 있으면 좋겠어요.', 0),
    ('졸업생도 토요교실 올 수 있나요?', '작년에 졸업한 형이 동생 따라 오고 싶어 합니다.', 1),
]


class Command(BaseCommand):
    help = '로컬 실습용 모의 데이터를 넣는다(idempotent). 실제 정보가 아님.'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('DEBUG 가 꺼진 환경에서는 더미 데이터를 넣지 않습니다.')
        User = get_user_model()

        # [실습 A02] 기본 관리자 계정 — 이름과 비밀번호가 문서화된 흔한 값이다. main 의 시드에는 없다.
        User.objects.filter(username='admin').exists() or \
            User.objects.create_superuser('admin', 'admin@example.com', 'admin1234')

        CenterInfo.objects.get_or_create(
            name='햇살지역아동센터',
            defaults=dict(tel='031-000-0000', address='경기도 성남시 어딘가 123',
                          hours='평일 13:00~19:00'))

        for i, (name, target, schedule, body) in enumerate(PROGRAMS):
            Program.objects.get_or_create(name=name, defaults=dict(
                target=target, schedule=schedule, body=body, order=i))

        guardians = []
        for username in GUARDIANS:
            u, created = User.objects.get_or_create(username=username)
            if created:
                u.set_unusable_password()   # 로그인용 아님 — IDOR 표적 데이터
                u.save(update_fields=['password'])
            guardians.append(u)

        children = []
        for name, number, code, tel, gi in CHILDREN:
            child, _ = Child.objects.get_or_create(number=number, defaults=dict(
                name=name, code=code, guardian_tel=tel,
                guardian=guardians[gi] if gi is not None else None, active=True))
            children.append(child)

        # 최근 14일 출석 기록. 비고(직원 메모)는 보호자 화면에 안 나와 IDOR 로만 보인다.
        today = timezone.localdate()
        for child in children:
            for d in range(14):
                day = today - timedelta(days=d)
                if day.weekday() >= 5:   # 주말 제외
                    continue
                cin = timezone.make_aware(timezone.datetime.combine(
                    day, timezone.datetime.min.time())) + timedelta(hours=15, minutes=10)
                note = '병원 진료로 늦음' if (d == 2 and child.number == 1) else ''
                Attendance.objects.get_or_create(child=child, date=day, defaults=dict(
                    check_in=cin, check_out=cin + timedelta(hours=3),
                    status='출석', source=Attendance.BY_KIOSK, note=note))

        for title, body, pinned in NOTICES:
            Notice.objects.get_or_create(title=title, defaults=dict(body=body, pinned=pinned))

        for title, body, gi in POSTS:
            post, created = Post.objects.get_or_create(
                title=title, defaults=dict(body=body, author=guardians[gi]))
            if created:
                Comment.objects.create(post=post, body='저도 같은 생각이에요.', author=guardians[(gi + 1) % 3])

        self.stdout.write(self.style.SUCCESS(
            '모의 데이터 완료 — 보호자 %d · 아동 %d · 공지 %d · 게시글 %d. '
            '실습자는 /signup/ 으로 계정을 직접 만든다.'
            % (User.objects.count(), Child.objects.count(),
               Notice.objects.count(), Post.objects.count())))
