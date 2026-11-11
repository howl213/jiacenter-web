import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import ATTACH_MAX_BYTES, Notice, NoticeFile, validate_attachment

PDF = b'%PDF-1.4\n%x\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20
JPG = b'\xff\xd8\xff\xe0' + b'0' * 20
TMP = tempfile.mkdtemp()


def up(data, name='a.pdf'):
    return SimpleUploadedFile(name, data)


@override_settings(MEDIA_ROOT=TMP)
class AttachmentTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.n = Notice.objects.create(title='t', body='b')

    def make(self, data, name):
        return NoticeFile.objects.create(notice=self.n, file=up(data, name))

    def test_validator_accepts_only_real_pdf_png_jpg(self):
        for ok in (PDF, PNG, JPG):
            validate_attachment(up(ok))
        for bad in (b'<html><script>alert(1)</script>', b'MZ\x90\x00', b'GIF89a', b'', b'PK\x03\x04'):
            with self.assertRaises(ValidationError):
                validate_attachment(up(bad, 'a.pdf'))

    def test_extension_is_not_trusted(self):
        with self.assertRaises(ValidationError):
            validate_attachment(up(b'<script>alert(1)</script>', 'evil.png'))

    def test_size_limit(self):
        with self.assertRaises(ValidationError):
            validate_attachment(up(PDF + b'0' * ATTACH_MAX_BYTES, 'big.pdf'))

    def test_stored_name_is_generated_not_user_supplied(self):
        f = self.make(PNG, '../../evil.php.png')
        self.assertRegex(f.file.name, r'^notice/[0-9a-f]{32}\.png$')
        self.assertEqual(f.label, 'evil.php.png')

    def test_extension_follows_content_not_name(self):
        self.assertTrue(self.make(PDF, 'photo.jpg').file.name.endswith('.pdf'))

    def test_download_headers(self):
        pdf, png = self.make(PDF, 'a.pdf'), self.make(PNG, 'b.png')
        r = self.client.get(f'/notices/files/{pdf.pk}/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', r['Content-Security-Policy'])
        r = self.client.get(f'/notices/files/{png.pk}/')
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertNotIn('attachment', r.get('Content-Disposition', ''))
        self.assertEqual(self.client.get('/notices/files/9999/').status_code, 404)

    def test_files_not_reachable_by_direct_url(self):
        f = self.make(PDF, 'a.pdf')
        self.assertEqual(self.client.get('/media/' + f.file.name).status_code, 404)

    def test_detail_page_lists_label_escaped(self):
        self.make(PDF, '<b>x.pdf')
        html = self.client.get(f'/notices/{self.n.pk}/').content.decode()
        self.assertIn('&lt;b&gt;x.pdf', html)
        self.assertNotIn('<b>x.pdf', html)

    def test_admin_inline_limits_to_three(self):
        from .admin import NoticeFileInline
        self.assertEqual(NoticeFileInline.max_num, 3)

    def test_admin_page_loads(self):
        User.objects.create_superuser('boss', 'a@b.c', 'pw')
        self.client.login(username='boss', password='pw')
        self.assertEqual(self.client.get(f'/admin/center/notice/{self.n.pk}/change/').status_code, 200)
