from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('notices/', views.notice_list, name='notices'),
    path('notices/<int:pk>/', views.notice_detail, name='notice_detail'),
    path('notices/files/<int:pk>/', views.notice_file, name='notice_file'),
    path('programs/', views.program_list, name='program_list'),
    path('about/', views.about, name='about'),
    path('attendance/', views.kiosk, name='kiosk'),
    path('attendance/board/', views.board, name='board'),
    path('attendance/export/', views.export, name='export'),
    path('attendance/import/', views.import_children, name='import_children'),
    path('my/', views.my, name='my'),
    path('signup/', views.signup, name='signup'),
]
