from django.conf import settings


def center(request):
    return {'center': settings.CENTER}
