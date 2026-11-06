from django.conf import settings

from .models import CenterInfo


def center(request):
    # shortcut: 요청마다 쿼리 1번. 트래픽이 늘면 캐시한다.
    # DB 에 행이 없으면(마이그레이션 직후 등) settings.CENTER 값을 그대로 쓴다.
    return {'center': CenterInfo.objects.first() or settings.CENTER}
