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
    path('my/<int:child_id>/', views.my_child, name='my_child'),
    path('signup/', views.signup, name='signup'),
    # [실습 A06]
    path('signup/phone/', views.signup_phone, name='signup_phone'),
    path('board/posts/', views.post_list, name='post_list'),
    path('board/posts/new/', views.post_create, name='post_create'),
    path('board/posts/<int:pk>/', views.post_detail, name='post_detail'),
    path('embed/', views.embed, name='embed'),
]
