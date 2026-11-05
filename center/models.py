from django.db import models
from django.utils import timezone


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
