import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class CenterInfo(models.Model):
    """센터 이름·전화·주소·운영시간. 직원이 admin 에서 고치면 모든 화면에 반영된다.

    행은 하나만 쓴다(admin 에서 두 번째 행은 못 만들게 막았다).
    값을 바꾸려고 코드를 고치지 않아도 되게 하는 것이 목적이다.
    """
    name = models.CharField('센터 이름', max_length=50)
    tel = models.CharField('대표 전화', max_length=30)
    address = models.CharField('주소', max_length=200)
    hours = models.CharField('운영시간', max_length=100)

    class Meta:
        verbose_name = verbose_name_plural = '센터 정보'

    def __str__(self):
        return self.name


class Notice(models.Model):
    title = models.CharField('제목', max_length=200)
    body = models.TextField('내용')
    pinned = models.BooleanField('상단 고정', default=False)
    created_at = models.DateTimeField('작성일', auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = '공지사항'
        ordering = ['-pinned', '-created_at']

    def __str__(self):
        return self.title


# 허용 형식: 파일 앞부분 바이트로 판정한다. 사용자가 붙인 확장자·Content-Type 은 믿지 않는다.
ATTACH_TYPES = [(b'%PDF-', 'pdf', 'application/pdf'),
                (b'\x89PNG\r\n\x1a\n', 'png', 'image/png'),
                (b'\xff\xd8\xff', 'jpg', 'image/jpeg')]
ATTACH_MAX_BYTES = 5 * 1024 * 1024
ALBUM_PHOTO_MAX_BYTES = 10 * 1024 * 1024   # 폰 사진은 공지 첨부보다 크다(사용자 결정, 2026-11-17)
ATTACH_MAX_COUNT = 3


def sniff(head):
    """앞부분 바이트로 (확장자, MIME) 를 돌려준다. 허용 형식이 아니면 None."""
    return next(((ext, mime) for magic, ext, mime in ATTACH_TYPES if head.startswith(magic)), None)


def validate_attachment(f, max_bytes=ATTACH_MAX_BYTES):
    if f.size > max_bytes:
        raise ValidationError(f'파일은 {max_bytes // 1024 // 1024}MB 까지 올릴 수 있습니다.')
    f.seek(0)
    kind = sniff(f.read(16))
    f.seek(0)
    if kind is None:
        raise ValidationError('PDF, PNG, JPG 파일만 올릴 수 있습니다.')


def _stored_name(folder, instance):
    # 저장 이름은 새로 만든다 — 사용자가 준 이름(경로 조작·이중 확장자)을 디스크에 쓰지 않는다.
    f = instance.file.file
    f.seek(0)
    ext = sniff(f.read(16))[0]
    f.seek(0)
    return f'{folder}/{uuid.uuid4().hex}.{ext}'


def attachment_path(instance, filename):
    return _stored_name('notice', instance)


def photo_path(instance, filename):
    return _stored_name('album', instance)


def validate_photo(f):
    validate_attachment(f, ALBUM_PHOTO_MAX_BYTES)
    kind = sniff(f.read(16))
    f.seek(0)
    if kind[0] == 'pdf':
        raise ValidationError('PNG, JPG 사진만 올릴 수 있습니다.')


class NoticeFile(models.Model):
    """공지 첨부. 직접 주소로 열리지 않고 notice_file 화면을 거쳐서만 내려간다."""
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name='files')
    file = models.FileField('파일', upload_to=attachment_path, validators=[validate_attachment])
    label = models.CharField('표시 이름', max_length=100, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '공지 첨부'
        ordering = ['id']

    def save(self, *args, **kwargs):
        if not self.label and self._state.adding:
            self.label = self.file.name.rsplit('/', 1)[-1][:100]   # 올린 원래 이름(저장 전 값)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.label


ALBUM_MAX_COUNT = 20


class Album(models.Model):
    """활동앨범 한 묶음. 누구나 본다."""
    title = models.CharField('제목', max_length=100)
    date = models.DateField('활동일', default=timezone.localdate)

    class Meta:
        verbose_name = verbose_name_plural = '활동앨범'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.title


class Photo(models.Model):
    """앨범 사진. 공지 첨부처럼 album_photo 화면을 거쳐서만 내려간다.

    올라온 파일을 그대로 내보낸다 — 위치 정보(EXIF)는 올리는 사람이 미리 지운다(사용자 결정, 2026-11-16).
    """
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name='photos')
    file = models.FileField('사진', upload_to=photo_path, validators=[validate_photo])
    caption = models.CharField('설명', max_length=100, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '앨범 사진'
        ordering = ['id']

    def __str__(self):
        return self.caption or f'사진 {self.pk}'


class Program(models.Model):
    name = models.CharField('프로그램명', max_length=100)
    target = models.CharField('대상', max_length=100, blank=True)
    schedule = models.CharField('요일/시간', max_length=100, blank=True)
    body = models.TextField('설명', blank=True)
    order = models.IntegerField('노출 순서', default=0)

    class Meta:
        verbose_name = verbose_name_plural = '프로그램'
        ordering = ['order', 'id']

    def __str__(self):
        return self.name


class Child(models.Model):
    name = models.CharField('이름', max_length=20)
    number = models.PositiveIntegerField('출석번호', unique=True)
    # 키오스크에서 아이가 실제로 누르는 숫자. 보호자 번호 뒷 4자리,
    # 남매는 뒤에 순번 한 자리를 붙인다(2742 / 27421 / 27422).
    code = models.CharField('인식번호', max_length=10, unique=True, null=True, blank=True)
    guardian_tel = models.CharField('보호자 연락처', max_length=20, blank=True)
    # 보호자 로그인 계정. /my/ 가 이 연결로 "내 아이"만 보여준다.
    guardian = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name='children',
                                 verbose_name='보호자 계정')
    active = models.BooleanField('재원', default=True)

    class Meta:
        verbose_name = verbose_name_plural = '아동'
        ordering = ['number']

    def __str__(self):
        return f'{self.number}. {self.name}'


class Attendance(models.Model):
    BY_KIOSK = 'kiosk'
    BY_STAFF = 'staff'
    # 정산 보고에 사유 구분이 필요해서 둔다. 항목은 센터 양식에 맞춰 바꾸면 된다.
    STATUS = [('출석', '출석'), ('결석', '결석'), ('조퇴', '조퇴'), ('병가', '병가'), ('기타', '기타')]
    child = models.ForeignKey(Child, on_delete=models.CASCADE, verbose_name='아동')
    date = models.DateField('날짜')
    check_in = models.DateTimeField('입실', null=True, blank=True)
    check_out = models.DateTimeField('퇴실', null=True, blank=True)
    status = models.CharField('사유', max_length=4, default='출석', choices=STATUS)
    source = models.CharField('입력방법', max_length=10, default=BY_KIOSK,
                              choices=[(BY_KIOSK, '키오스크'), (BY_STAFF, '관리자')])
    note = models.CharField('비고', max_length=200, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = '출결'
        ordering = ['-date', 'child__number']
        constraints = [models.UniqueConstraint(fields=['child', 'date'], name='uniq_child_date')]

    def __str__(self):
        return f'{self.date} {self.child}'

    def snapshot(self):
        """변경 이력에 남길 한 줄 요약. 시각은 서울 시간 기준 HH:MM."""
        def t(v):
            return f'{timezone.localtime(v):%H:%M}' if v else '-'
        return f'입실 {t(self.check_in)} / 퇴실 {t(self.check_out)} / {self.status} / {self.note or "-"}'


class AttendanceLog(models.Model):
    """출결 기록이 바뀔 때마다 이전 값과 새 값을 남긴다. 정산 근거를 나중에 확인하기 위한 것이다.

    출결 행이 지워져도 이력은 남도록 label 에 아동·날짜를 따로 적는다.
    """
    attendance = models.ForeignKey(Attendance, null=True, on_delete=models.SET_NULL,
                                   related_name='logs', verbose_name='출결')
    label = models.CharField('대상', max_length=60)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                           on_delete=models.SET_NULL, verbose_name='바꾼 직원')
    via = models.CharField('경로', max_length=10)   # kiosk / staff(현황판) / admin
    at = models.DateTimeField('바꾼 시각', auto_now_add=True)
    before = models.TextField('이전')
    after = models.TextField('이후')

    class Meta:
        verbose_name = verbose_name_plural = '출결 변경 이력'
        ordering = ['-at', '-id']

    @classmethod
    def add(cls, rec, before, via, by=None):
        """값이 실제로 달라졌을 때만 남긴다."""
        after = rec.snapshot()
        if before != after:
            cls.objects.create(attendance=rec, label=f'{rec.date} {rec.child}', by=by,
                               via=via, before=before, after=after)


class NotifyLog(models.Model):
    """알림톡 API 승인 전에는 전송 대신 여기에만 기록한다."""
    tel = models.CharField('수신번호', max_length=20)
    template = models.CharField('템플릿', max_length=40)
    body = models.TextField('내용')
    sent = models.BooleanField('실제 전송됨', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = '알림톡 기록'
        ordering = ['-created_at']

    def __str__(self):
        return f'{timezone.localtime(self.created_at):%m-%d %H:%M} {self.template} → {self.tel}'
