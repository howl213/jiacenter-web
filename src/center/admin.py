from django.contrib import admin

from .models import (ALBUM_MAX_COUNT, ATTACH_MAX_COUNT, Album, Attendance, AttendanceLog, CenterInfo,
                     Child, NoticeFile, NotifyLog, Notice, Photo, Program)


@admin.register(CenterInfo)
class CenterInfoAdmin(admin.ModelAdmin):
    list_display = ['name', 'tel', 'address', 'hours']

    def has_add_permission(self, request):
        return not CenterInfo.objects.exists()   # 한 행만 쓴다 — 지우고 새로 만들 일도 없다

    def has_delete_permission(self, request, obj=None):
        return False


class NoticeFileInline(admin.TabularInline):
    model = NoticeFile
    extra = 1
    max_num = ATTACH_MAX_COUNT   # 공지당 3개까지(PDF·PNG·JPG, 5MB)


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    inlines = [NoticeFileInline]
    list_display = ['title', 'pinned', 'created_at']
    list_editable = ['pinned']
    fieldsets = [(None, {
        'fields': ['title', 'body', 'pinned'],
        'description': '본문 서식: **굵게** · 줄 맨 앞에 "## " 은 소제목 · "- " 는 목록 · 빈 줄은 문단 구분. '
                       'HTML 과 링크는 쓸 수 없고 글자 그대로 보입니다.'})]


class PhotoInline(admin.TabularInline):
    model = Photo
    extra = 3
    max_num = ALBUM_MAX_COUNT


@admin.register(Album)
class AlbumAdmin(admin.ModelAdmin):
    inlines = [PhotoInline]
    list_display = ['title', 'date']
    fieldsets = [(None, {
        'fields': ['title', 'date'],
        'description': '사진은 PNG·JPG, 한 장 10MB, 앨범당 20장까지. 누구나 볼 수 있습니다. '
                       '사이트는 사진의 위치 정보를 지우지 않으니, 올리기 전에 위치 정보를 지워 주세요.'})]


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ['name', 'target', 'schedule', 'order']
    list_editable = ['order']


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = ['number', 'name', 'code', 'guardian_tel', 'guardian', 'active']
    list_editable = ['code']
    list_filter = ['active']
    search_fields = ['name', 'code']


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ['date', 'child', 'check_in', 'check_out', 'status', 'source', 'note']
    list_filter = ['date', 'status', 'source']

    def save_model(self, request, obj, form, change):
        before = Attendance.objects.get(pk=obj.pk).snapshot() if change else ''
        super().save_model(request, obj, form, change)
        AttendanceLog.add(obj, before, 'admin', request.user)


@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ['at', 'label', 'via', 'by', 'before', 'after']
    list_filter = ['via']

    # 이력은 읽기 전용이다. 고치거나 지울 수 있으면 근거가 되지 못한다.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NotifyLog)
class NotifyLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'template', 'tel', 'sent']
    readonly_fields = ['created_at']
