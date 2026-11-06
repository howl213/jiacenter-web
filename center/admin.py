from django.contrib import admin

from .models import Attendance, CenterInfo, Child, NotifyLog, Notice, Program


@admin.register(CenterInfo)
class CenterInfoAdmin(admin.ModelAdmin):
    list_display = ['name', 'tel', 'address', 'hours']

    def has_add_permission(self, request):
        return not CenterInfo.objects.exists()   # 한 행만 쓴다 — 지우고 새로 만들 일도 없다

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ['title', 'pinned', 'created_at']
    list_editable = ['pinned']


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


@admin.register(NotifyLog)
class NotifyLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'template', 'tel', 'sent']
    readonly_fields = ['created_at']
