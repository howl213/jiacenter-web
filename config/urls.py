"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from django.contrib.auth.views import LoginView

from center.views import limited_login

urlpatterns = [
    path('', include('center.urls')),
    path('login/', limited_login(LoginView.as_view(template_name='center/login.html',
                                                   redirect_authenticated_user=True)), name='login'),
    path(settings.ADMIN_PATH + 'login/', limited_login(admin.site.login)),  # admin.site.urls 보다 먼저 와야 가로챈다
    path(settings.ADMIN_PATH, admin.site.urls),
]
