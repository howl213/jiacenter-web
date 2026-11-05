from django.contrib import admin

from .models import Attendance, Child, NotifyLog, Notice, Program


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
    list_display = ['number', 'name', 'code', 'guardian_tel', 'active']
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
