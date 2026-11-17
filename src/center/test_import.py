from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .models import Child

HEAD = '출석번호,이름,인식번호,보호자연락처\n'


def up(body, name='a.csv', enc='utf-8-sig'):
    return SimpleUploadedFile(name, body.encode(enc), content_type='text/csv')


class ImportChildrenTests(TestCase):
    url = '/attendance/import/'

    def setUp(self):
        User.objects.create_superuser('staff', 'a@b.c', 'pw')
        self.client.login(username='staff', password='pw')

    def post(self, body, save=True, **kw):
        data = {'file': up(body, **kw)}
        if save:
            data['save'] = '1'
        return self.client.post(self.url, data)

    def test_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.url, {'file': up(HEAD + '1,가나,,')}).status_code, 302)
        self.assertFalse(Child.objects.exists())

    def test_saves_valid_rows(self):
        self.post(HEAD + '1,가나,2742,010-0000-0000\n2,다라,,\n')
        self.assertEqual(list(Child.objects.values_list('number', 'name', 'code')),
                         [(1, '가나', '2742'), (2, '다라', None)])

    def test_dry_run_does_not_save(self):
        r = self.post(HEAD + '1,가나,,\n', save=False)
        self.assertFalse(Child.objects.exists())
        self.assertEqual(len(r.context['rows']), 1)

    def test_existing_number_is_skipped_not_overwritten(self):
        Child.objects.create(number=1, name='기존')
        r = self.post(HEAD + '1,새이름,,\n2,다라,,\n')
        self.assertEqual(Child.objects.get(number=1).name, '기존')
        self.assertEqual(r.context['skipped'], [1])
        self.assertTrue(Child.objects.filter(number=2).exists())

    def test_one_bad_row_saves_nothing(self):
        r = self.post(HEAD + '1,가나,,\n2,=HYPERLINK("x"),,\n')
        self.assertFalse(Child.objects.exists())
        self.assertEqual(len(r.context['errors']), 1)

    def test_rejects_bad_values(self):
        for row in ['0,가나,,', 'x,가나,,', '1,,,', '1,' + '가' * 21 + ',,', '1,가나,12a,', '1,가나,,abc',
                    '1,@가나,,', '1,가나\x07,,', '1,가나', '1,가나,,,,']:
            self.post(HEAD + row + '\n')
            self.assertFalse(Child.objects.exists(), row)

    def test_duplicates_inside_file_and_with_db_are_rejected(self):
        self.post(HEAD + '1,가나,,\n1,다라,,\n')
        self.post(HEAD + '1,가나,55,\n2,다라,55,\n')
        self.assertFalse(Child.objects.exists())
        Child.objects.create(number=9, name='기존', code='77')
        self.post(HEAD + '1,가나,77,\n')
        self.assertEqual(Child.objects.count(), 1)

    def test_header_extension_size_and_encoding(self):
        self.post('번호,이름,인식번호,연락처\n1,가나,,\n')
        self.post(HEAD + '1,가나,,\n', name='a.txt')
        self.post(HEAD + '1,가나,,\n', name='a.csv.exe')
        self.post(HEAD + ('1,가나,,\n' * 70000))
        self.post(HEAD + '1,가나,,\n', enc='utf-16')
        self.assertFalse(Child.objects.exists())

    def test_cp949_file_is_read(self):
        self.post(HEAD + '1,가나,,\n', enc='cp949')
        self.assertEqual(Child.objects.get().name, '가나')

    def test_row_limit(self):
        body = HEAD + ''.join(f'{i},가나,,\n' for i in range(1, 502))
        self.post(body)
        self.assertFalse(Child.objects.exists())

    def test_name_is_escaped_in_page(self):
        r = self.post(HEAD + '1,<b>가,,\n', save=False)
        self.assertNotIn('<b>가', r.content.decode())
