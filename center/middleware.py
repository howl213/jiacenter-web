# [실습 A07]
"""세션 고정(session fixation). main 에는 이 파일이 없다."""
from importlib import import_module

from django.conf import settings


class SessionFixationMiddleware:
    """주소의 ?sessionid= 를 그대로 세션으로 받아들이고, 로그인해도 그 키를 새로 만들지 않는다.

    공격자가 아는 세션 id 를 피해자에게 심어(피해자가 ?sessionid=... 로 로그인) 로그인 뒤에도
    그 id 가 그대로 인증되게 만든다 → 공격자가 같은 id 로 피해자 세션을 가로챈다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        sid = request.GET.get('sessionid')
        if sid:
            engine = import_module(settings.SESSION_ENGINE)
            store = engine.SessionStore(sid)
            store._session_key = sid
            # [실습 A07] 그 id 로 세션을 실제로 만들어 둔다 — 없으면 Django 가 새 키로 갈아탄다.
            if not store.exists(sid):
                store.save(must_create=True)
            # [실습 A07] 로그인해도 세션 키를 새로 만들지 않는다
            store.cycle_key = lambda: None
            request.session = store
        return self.get_response(request)
