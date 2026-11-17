"""화면을 그리는 곳. 출결 파이프라인의 본체가 여기 있다.

읽는 순서
  1) _toggle()  ─ 입실/퇴실을 판정하는 유일한 함수. 여기만 이해하면 출결은 끝.
  2) kiosk()    ─ 아이가 직접 쓰는 현관 화면. _toggle 을 부른다.
  3) board()    ─ 직원이 대신 찍어주는 화면. 역시 같은 _toggle 을 부른다.
  나머지(home/notice/program/about)는 단순히 목록을 보여주는 페이지다.

출결 한 건의 흐름
  번호 입력 ─▶ 아동 조회 ─▶ 오늘 기록 확보 ─▶ 입/퇴실 판정 ─▶ 알림톡 기록 ─▶ 화면 갱신
  그림으로 보려면 99.result/attendance_flow.svg 를 열면 된다.

외부 의존
  .models  : Attendance 에 (아동, 날짜) 유일 제약이 걸려 있어 하루 1행이 보장된다.
  .notify  : send_alimtalk() — 경기도 API 승인 전이라 실제 전송은 하지 않는다.
"""

import csv
import hashlib
import logging
from datetime import datetime, timedelta

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import importer
from .models import Album, Attendance, AttendanceLog, Child, Notice, NoticeFile, Photo, Program, sniff
from .notify import send_alimtalk

# 보안 사건 기록(config/settings.py 의 LOGGING → logs/security.log). 비밀번호·입력한 번호·이름은 남기지 않는다.
security_log = logging.getLogger('center.security')


def home(request):
    # 홈에는 최근 공지 3건과 최근 사진 4장만. 공지 정렬(고정 먼저, 최신순)은 Notice.Meta.ordering 이 이미 해준다.
    photos = Photo.objects.select_related('album').order_by('-album__date', '-album_id', '-id')[:4]
    return render(request, 'center/home.html', {'notices': Notice.objects.all()[:3],
                                                'programs': Program.objects.all()[:3],
                                                'photos': photos})


def notice_list(request):
    # 검색어는 ORM 필터로만 쓴다. 값이 SQL 문장과 분리되어 전달되므로 문자열을 이어 붙이지 않는다.
    # NUL 문자는 SQLite 의 LIKE 가 거기서 패턴을 끊어 "전부 일치"가 되므로 미리 뺀다.
    q = request.GET.get('q', '').replace('\x00', '').strip()[:100]
    notices = Notice.objects.all()
    if q:
        notices = notices.filter(Q(title__icontains=q) | Q(body__icontains=q))
    # get_page 는 ?page 가 없거나 숫자가 아니어도 예외 없이 1페이지를 준다.
    page = Paginator(notices, 10).get_page(request.GET.get('page'))
    return render(request, 'center/notice_list.html', {'page': page, 'q': q})


def notice_detail(request, pk):
    return render(request, 'center/notice_detail.html',
                  {'notice': get_object_or_404(Notice, pk=pk)})


def notice_file(request, pk):
    """공지 첨부 내려받기. 형식은 파일 내용으로 다시 판정하고, 브라우저가 추측하지 못하게 막는다.

    PDF 는 항상 내려받기로 준다(브라우저 안에서 스크립트가 도는 것을 피한다). 그림만 화면에 바로 보인다.
    """
    return _send(get_object_or_404(NoticeFile, pk=pk).file)


def _send(field):
    fh = field.open('rb')
    mime = sniff(fh.read(16))[1]
    fh.seek(0)
    resp = FileResponse(fh, content_type=mime, as_attachment=mime == 'application/pdf',
                        filename=field.name.rsplit('/', 1)[-1])
    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return resp


def album_list(request):
    page = Paginator(Album.objects.prefetch_related('photos'), 12).get_page(request.GET.get('page'))
    return render(request, 'center/album_list.html', {'page': page})


def album_detail(request, pk):
    return render(request, 'center/album_detail.html', {'album': get_object_or_404(Album, pk=pk)})


def album_photo(request, pk):
    return _send(get_object_or_404(Photo, pk=pk).file)


def program_list(request):
    return render(request, 'center/program_list.html', {'programs': Program.objects.all()})


def about(request):
    # 보여줄 내용이 전부 센터 정보(DB, 없으면 settings.CENTER)에서 오므로 넘겨줄 값이 없다(context processor 담당).
    return render(request, 'center/about.html')


# 시도 횟수 제한. 키오스크는 번호를 못 찾은 횟수, 로그인은 실패한 횟수를 센다.
KIOSK_MAX_MISSES, KIOSK_WINDOW = 10, 60            # 1분에 10번 틀리면 1분간 잠금
LOGIN_MAX_FAILS, LOGIN_WINDOW = 5, 5 * 60          # 같은 IP 에서 같은 아이디로 5분에 5번
LOGIN_IP_MAX_FAILS, LOGIN_IP_WINDOW = 30, 15 * 60  # 아이디를 바꿔가며 찍어도 IP 하나당 15분에 30번


def _blocked(key, limit):
    return cache.get(key, 0) >= limit


def _count_failure(key, window):
    # shortcut: 프로세스 메모리 캐시 + REMOTE_ADDR 라서 서버 여러 대/워커면 한도가 그 수만큼 늘고,
    # 프록시 뒤에서는 모두 같은 IP 로 보인다. 배포 시 공유 캐시와 실제 클라이언트 IP 로 바꾼다.
    cache.add(key, 0, window)
    cache.incr(key)


def limited_login(login_view):
    """로그인 화면을 그대로 쓰되, 틀린 시도가 쌓이면 맞는 비밀번호도 잠시 막는다.

    IP 만 보면 공유기 뒤에서 한 명의 오타가 모두를 막는다. 그렇다고 아이디만 보면 남이
    일부러 틀려서 관리자를 잠글 수 있다. 그래서 (IP, 아이디) 쌍을 잠그고, 아이디를 바꿔가며
    찍는 경우는 IP 전체 한도로 막는다. 직원(admin) 로그인과 보호자 로그인이 함께 쓴다.
    """
    def wrapped(request):
        ip = request.META.get('REMOTE_ADDR')
        name = hashlib.sha1(request.POST.get('username', '').strip().lower().encode(), usedforsecurity=False).hexdigest()
        user_key, ip_key = f'login:{ip}:{name}', f'login-ip:{ip}'
        if request.method == 'POST' and (_blocked(user_key, LOGIN_MAX_FAILS)
                                         or _blocked(ip_key, LOGIN_IP_MAX_FAILS)):
            security_log.warning('login_locked ip=%s who=%s', ip, name[:8])
            return HttpResponse('로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.', status=429)
        response = login_view(request)
        if request.method == 'POST':
            if response.status_code == 200:      # 실패하면 폼이 다시 그려져 200
                security_log.warning('login_failed ip=%s who=%s', ip, name[:8])   # who: 아이디의 해시 앞 8자
                _count_failure(user_key, LOGIN_WINDOW)
                _count_failure(ip_key, LOGIN_IP_WINDOW)
            else:                                # 성공하면 302 — 이 아이디의 실패 기록을 지운다
                cache.delete(user_key)
                security_log.info('login_ok ip=%s user_id=%s', ip, getattr(request.user, 'pk', None))
        return response
    return wrapped


def _pk(value):
    """숫자 문자열이면 정수로, 아니면 None. 외부 입력을 int() 에 바로 넣으면 500 이 난다.

    str.isdigit() 만으로는 '²' 같은 문자가 통과해 int() 에서 터지고,
    자릿수 제한이 없으면 수천 자리 숫자도 터진다. 그래서 ASCII 와 길이를 함께 본다.
    """
    value = value or ''
    return int(value) if value.isascii() and value.isdigit() and len(value) < 10 else None


def _find_child(pk, typed):
    """타일을 눌렀으면 pk로, 숫자를 쳤으면 인식번호 또는 출석번호로 아동을 찾는다.

    인식번호는 4~5자리, 출석번호는 1~2자리라 서로 겹치지 않는다.
    퇴소한 아동(active=False)은 어느 쪽으로도 찾히지 않는다.
    """
    children = Child.objects.filter(active=True)
    if pk:
        return children.filter(pk=_pk(pk)).first()
    typed = (typed or '').strip()
    if not typed:
        return None
    # 출석번호는 정수 칸이라 숫자일 때만 비교 대상에 넣는다.
    cond = Q(code=typed)
    if _pk(typed) is not None:
        cond |= Q(number=_pk(typed))
    return children.filter(cond).first()


def _toggle(child, source, date=None, by=None):
    """입실 기록이 없으면 입실, 있으면 퇴실. 이미 퇴실했으면 아무것도 안 바꾼다.

    키오스크(아이가 직접)와 현황판(직원이 대신) 두 입구가 모두 이 함수를 부른다.
    판정 규칙을 한 곳에만 두기 위해서다 — 두 곳에 복사하면 반드시 어긋난다.

    source 는 '누가 찍었나'(kiosk/staff)를 기록으로 남기기 위한 값이고,
    판정 자체에는 영향을 주지 않는다.

    돌려주는 값은 화면에 그대로 띄울 한국어 안내 문구다.
    """
    # localtime(): settings.TIME_ZONE(Asia/Seoul) 기준. DB에는 UTC로 저장되므로
    # 표시할 때마다 변환이 필요하다. 아래 check_out 출력에서도 다시 localtime 을 쓴다.
    now = timezone.localtime()
    # 현황판에서 지난 날짜를 보정할 때는 그 날짜에 기록한다. 기본은 오늘.
    date = date or now.date()
    # 지난 날짜를 뒤늦게 보정하면서 "지금 도착했습니다" 알림을 보내면 안 된다.
    notify = date == now.date()

    # 그날 이 아이의 행을 "가져오거나, 없으면 만든다". 만들 때만 defaults 가 쓰이므로
    # 이미 행이 있으면 check_in/source 는 건드려지지 않는다 = 첫 입실 시각이 보존된다.
    # (아동, 날짜) 유일 제약 덕분에 연타해도 행이 늘어나지 않는다.
    rec, created = Attendance.objects.get_or_create(
        child=child, date=date, defaults={'check_in': now, 'source': source})

    # 갈래 1: 방금 만들었다 = 오늘 첫 접촉 = 입실.
    if created:
        AttendanceLog.add(rec, '', source, by)
        if notify:
            send_alimtalk(child.guardian_tel, 'check_in', name=child.name, time=f'{now:%H:%M}')
        return f'{child.name} 입실 {now:%H:%M}'

    # 갈래 2: 이미 퇴실까지 끝난 상태. 세 번째부터는 기록을 바꾸지 않고 안내만 한다.
    # 출결은 보조금 정산 근거라, 잘못 누른 재입력이 실제 시각을 덮어쓰면 안 된다.
    # 시각을 정말 고쳐야 하면 관리자(/admin/)에서 직접 수정한다.
    if rec.check_out:
        return f'{child.name} 이미 퇴실했습니다 ({timezone.localtime(rec.check_out):%H:%M})'

    # 갈래 3: 입실만 되어 있다 = 퇴실 처리.
    # update_fields 로 퇴실칸만 저장한다 — 입실 시각이나 source 를 실수로 건드리지 않는다.
    before = rec.snapshot()
    rec.check_out = now
    rec.save(update_fields=['check_out'])
    AttendanceLog.add(rec, before, source, by)
    if notify:
        send_alimtalk(child.guardian_tel, 'check_out', name=child.name, time=f'{now:%H:%M}')
    return f'{child.name} 퇴실 {now:%H:%M}'


def kiosk(request):
    """현관 노트북에 띄워두는 화면. 아이가 출석번호를 누르고 엔터를 친다.

    로그인이 없는 페이지다. 센터 안에서만 쓰기로 해서 이름은 그대로 보여준다 —
    외부에 공개하게 되면 이름 표시 범위를 먼저 다시 정해야 한다.
    """
    message = None
    if request.method == 'POST':
        kiosk_key = f'kiosk:{request.META.get("REMOTE_ADDR")}'
        if _blocked(kiosk_key, KIOSK_MAX_MISSES):
            message = '잠시 후 다시 눌러 주세요'
            security_log.warning('kiosk_locked ip=%s', request.META.get('REMOTE_ADDR'))
        else:
            child = _find_child(request.POST.get('child'), request.POST.get('number'))
            # 못 찾으면 DB를 전혀 건드리지 않고 안내만 한다.
            message = _toggle(child, Attendance.BY_KIOSK) if child else '없는 번호입니다'
            if not child:
                _count_failure(kiosk_key, KIOSK_WINDOW)

    # 여기부터는 GET/POST 공통 — 처리 후의 최신 상태로 명단을 다시 그린다.
    today = timezone.localdate()
    # 아동별로 오늘 기록을 미리 묶어둔다. 이렇게 안 하면 아동 수만큼 쿼리가 나간다(N+1).
    records = {a.child_id: a for a in Attendance.objects.filter(date=today)}
    # 기록이 없는 아이는 None 이 짝이 된다 → 템플릿에서 회색 '미입실' 타일.
    children = [(c, records.get(c.id)) for c in Child.objects.filter(active=True)]
    return render(request, 'center/kiosk.html', {'children': children, 'message': message})


def _parse_date(value, default):
    """'2026-03-14' 를 날짜로. 형식이 틀리면 조용히 기본값(오늘)으로 돌아간다."""
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return default


def _parse_time(value, date):
    """'14:30' + 날짜 → 저장 가능한 일시. 빈 칸이면 None(= 기록 없음)."""
    if not value:
        return None
    naive = datetime.combine(date, datetime.strptime(value, '%H:%M').time())
    return timezone.make_aware(naive)


@staff_member_required
def board(request):
    """직원용 현황판. 날짜를 옮겨 다니며 수기로 고칠 수 있다.

    staff_member_required 는 admin 로그인을 그대로 재사용한다(별도 로그인 화면 불필요).
    아동 실명과 보호자 정보가 보이는 화면이라 공개하지 않는다.
    """
    date = _parse_date(request.GET.get('date'), timezone.localdate())

    if request.method == 'POST':
        child = get_object_or_404(Child, pk=_pk(request.POST.get('child')))
        # 날짜는 폼에서 받는다 — 과거 날짜를 보던 중에 저장해도 그 날짜에 기록된다.
        date = _parse_date(request.POST.get('date'), date)
        if 'toggle' in request.POST:
            _toggle(child, Attendance.BY_STAFF, date, request.user)
        else:
            status = request.POST.get('status') or '출석'
            if status not in dict(Attendance.STATUS):
                # 선택지 밖의 값은 정산 사유가 될 수 없다. 기록을 만들기 전에 거른다.
                return redirect(f"{request.path}?date={date}")
            rec, _ = Attendance.objects.get_or_create(
                child=child, date=date, defaults={'source': Attendance.BY_STAFF})
            before = rec.snapshot()
            try:
                rec.check_in = _parse_time(request.POST.get('check_in'), date)
                rec.check_out = _parse_time(request.POST.get('check_out'), date)
            except ValueError:
                # 시간 형식이 깨졌으면 아무것도 바꾸지 않는다 — 기존 기록이 더 믿을 만하다.
                return redirect(f"{request.path}?date={date}")
            rec.status = status
            rec.note = request.POST.get('note', '')[:200]
            rec.source = Attendance.BY_STAFF
            rec.save()
            AttendanceLog.add(rec, before, Attendance.BY_STAFF, request.user)
        return redirect(f"{request.path}?date={date}")

    security_log.info('board_view user_id=%s date=%s', request.user.pk, date)   # 아동 실명이 보이는 화면의 열람 기록
    records = {a.child_id: a for a in Attendance.objects.filter(date=date)}
    children = [(c, records.get(c.id)) for c in Child.objects.filter(active=True)]
    # 그날 이전인데 퇴실이 비어 있는 기록 = 찍고 그냥 간 경우.
    # 추정 시간을 자동으로 채우지 않고 경고로만 띄운다. 정산 근거를 지어내면 안 되기 때문이다.
    unclosed = Attendance.objects.filter(
        check_in__isnull=False, check_out__isnull=True, date__lt=date)[:20]
    return render(request, 'center/board.html', {
        'children': children, 'unclosed': unclosed, 'date': date,
        'prev': date - timedelta(days=1), 'next': date + timedelta(days=1),
        'statuses': Attendance.STATUS, 'month': f'{date:%Y-%m}',
    })


def _csv_safe(value):
    """엑셀이 =+-@ 로 시작하는 값을 수식으로 실행하는 것을 막는다(CSV 수식 인젝션)."""
    text = str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


@staff_member_required
def export(request):
    """그 달 출결을 CSV로. 정산 보고서를 만들 때 엑셀에서 연다."""
    month = request.GET.get('month') or f'{timezone.localdate():%Y-%m}'
    rows = (Attendance.objects.filter(date__startswith=month)
            .select_related('child').order_by('date', 'child__number'))

    security_log.info('csv_export user_id=%s month=%s rows=%s', request.user.pk, month[:7], len(rows))
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="attendance_{month}.csv"'
    # BOM 을 붙여야 윈도우 엑셀이 더블클릭으로 열 때 한글이 깨지지 않는다.
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow(['날짜', '출석번호', '이름', '입실', '퇴실', '사유', '입력방법', '비고'])
    for a in rows:
        writer.writerow([
            a.date, a.child.number, _csv_safe(a.child.name),
            timezone.localtime(a.check_in).strftime('%H:%M') if a.check_in else '',
            timezone.localtime(a.check_out).strftime('%H:%M') if a.check_out else '',
            a.status, a.get_source_display(), _csv_safe(a.note),
        ])
    return response


@staff_member_required
def import_children(request):
    """CSV 로 아동 명단 등록. '검사만' 이 기본이라 한 번 미리 본 뒤에 저장한다."""
    ctx = {'columns': importer.HEADER}
    if request.method == 'POST' and request.FILES.get('file'):
        rows, skipped, errors = importer.parse(request.FILES['file'])
        save = request.POST.get('save') == '1' and not errors and rows
        if save:
            Child.objects.bulk_create(rows)
        security_log.info('csv_import user_id=%s saved=%s rows=%s skipped=%s errors=%s', request.user.pk,
                          bool(save), len(rows), len(skipped), len(errors))
        ctx.update(rows=rows, skipped=skipped, errors=errors, saved=bool(save))
    return render(request, 'center/import_children.html', ctx)


@login_required
def my(request):
    """보호자가 보는 \"내 아이\" 출결. 최근 30일.

    URL 에 아동 id 를 받지 않고 로그인한 사용자에게 연결된 아동만 조회한다.
    남의 아이가 보이지 않게 하는 것은 아래 filter(guardian=...) 한 줄이다.
    비고(note)는 직원 메모(병원 등)라 보호자 화면에 내지 않는다.
    """
    security_log.info('my_view user_id=%s', request.user.pk)
    children = Child.objects.filter(active=True, guardian=request.user)
    since = timezone.localdate() - timedelta(days=30)
    records = Attendance.objects.filter(child__in=children, date__gte=since)
    by_child = {c.id: [] for c in children}
    for r in records:
        by_child[r.child_id].append(r)
    return render(request, 'center/my.html', {'rows': [(c, by_child[c.id]) for c in children]})
