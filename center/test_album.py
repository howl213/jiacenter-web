import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import Album, Photo, validate_photo

PDF = b'%PDF-1.4\n%x\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20
JPG = b'\xff\xd8\xff\xe0' + b'0' * 20
TMP = tempfile.mkdtemp()


def up(data, name='a.jpg'):
    return SimpleUploadedFile(name, data)


@override_settings(MEDIA_ROOT=TMP)
class AlbumTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.a = Album.objects.create(title='<b>소풍')
        self.p = Photo.objects.create(album=self.a, file=up(PNG, '../../evil.php.png'), caption='"><i>x')

    def test_only_png_jpg(self):
        for ok in (PNG, JPG):
            validate_photo(up(ok))
        for bad in (PDF, b'GIF89a', b'<svg onload=alert(1)>', b''):
            with self.assertRaises(ValidationError):
                validate_photo(up(bad))

    def test_stored_name_is_generated(self):
        self.assertRegex(self.p.file.name, r'^album/[0-9a-f]{32}\.png$')

    def test_pages_are_public_and_escaped(self):
        for url in ('/albums/', f'/albums/{self.a.pk}/'):
            html = self.client.get(url).content.decode()
            self.assertIn('&lt;b&gt;소풍', html)
            self.assertNotIn('<b>소풍', html)
            self.assertIn(f'/albums/photos/{self.p.pk}/', html)
        self.assertNotIn('"><i>x', html)
        self.assertEqual(self.client.get('/albums/9999/').status_code, 404)

    def test_photo_headers_and_no_direct_url(self):
        r = self.client.get(f'/albums/photos/{self.p.pk}/')
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertNotIn('attachment', r.get('Content-Disposition', ''))
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', r['Content-Security-Policy'])
        self.assertEqual(self.client.get('/media/' + self.p.file.name).status_code, 404)
        self.assertEqual(self.client.get('/albums/photos/9999/').status_code, 404)

    def test_admin_page_loads_with_location_notice(self):
        User.objects.create_superuser('boss', 'a@b.c', 'pw')
        self.client.login(username='boss', password='pw')
        r = self.client.get(f'/admin/center/album/{self.a.pk}/change/')
        self.assertContains(r, '위치 정보')

    def test_admin_upload_accepts_photo_rejects_pdf(self):
        User.objects.create_superuser('boss', 'a@b.c', 'pw')
        self.client.login(username='boss', password='pw')

        def post(data):
            return self.client.post('/admin/center/album/add/', {
                'title': '새 앨범', 'date': '2026-11-16', 'photos-TOTAL_FORMS': 1, 'photos-INITIAL_FORMS': 0,
                'photos-MIN_NUM_FORMS': 0, 'photos-MAX_NUM_FORMS': 20,
                'photos-0-file': up(data), 'photos-0-caption': ''})
        self.assertEqual(post(PDF).status_code, 200)            # 폼이 오류와 함께 다시 뜬다
        self.assertFalse(Album.objects.filter(title='새 앨범').exists())
        self.assertEqual(post(JPG).status_code, 302)
        self.assertRegex(Album.objects.get(title='새 앨범').photos.get().file.name, r'^album/[0-9a-f]{32}\.jpg$')
