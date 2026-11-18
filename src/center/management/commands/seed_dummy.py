"""로컬 화면 확인용 모의 활동앨범을 만든다. 모의 값만 쓴다 — 실제 정보를 넣지 않는다.

로컬 DB 와 media/ 를 바꾼다(둘 다 커밋되지 않는다). 이미 만들었으면 아무것도 하지 않는다.
"""
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from center.models import Album, Photo

TITLE = '모의 활동앨범'
PHOTOS = [('hamster.png', '햄스터'), ('dog.png', '강아지'), ('cat.png', '고양이')]
SRC = Path(__file__).resolve().parents[2] / 'seed_photos'


class Command(BaseCommand):
    help = '모의 활동앨범 1개와 사진 3장을 만든다 (이미 있으면 건너뜀)'

    def handle(self, *args, **options):
        if Album.objects.filter(title=TITLE).exists():
            self.stdout.write('이미 있습니다. 건너뜁니다.')
            return
        album = Album.objects.create(title=TITLE)
        for name, caption in PHOTOS:
            with open(SRC / name, 'rb') as fh:
                photo = Photo(album=album, caption=caption, file=File(fh, name=name))
                photo.full_clean()   # 관리자 화면과 같은 검사(형식·크기)를 거친다
                photo.save()
        self.stdout.write(f'앨범 1개, 사진 {len(PHOTOS)}장을 만들었습니다.')
