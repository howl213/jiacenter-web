from django.db import migrations


class Migration(migrations.Migration):
    """0006_noticefile(공지 첨부·게시판 쪽)과 0006_upload(서류 업로드 쪽)를 한 줄로 잇는다."""

    dependencies = [
        ('center', '0006_upload'),
        ('center', '0007_post_comment'),
    ]

    operations = []
