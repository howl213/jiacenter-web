"""아동 명단 CSV 가져오기. 올린 파일은 믿지 않고 한 줄씩 검사한다.

원칙: 오류가 한 줄이라도 있으면 아무것도 저장하지 않는다(일부만 들어간 명단은 찾아내기 어렵다).
이미 있는 출석번호는 덮어쓰지 않고 건너뛴다 — 출결 기록이 그 아동에 매달려 있다.
"""
import csv
import io
import re

from .models import Child

MAX_BYTES = 1_000_000       # 아동 수백 명 명단은 수십 KB. 이보다 크면 잘못 고른 파일이다.
MAX_ROWS = 500
HEADER = ['출석번호', '이름', '인식번호', '보호자연락처']
FORMULA_START = ('=', '+', '-', '@', '\t', '\r')   # 엑셀이 수식으로 실행하는 시작 글자
_TEL = re.compile(r'^[0-9+\- ]{0,20}$')
_CTRL = re.compile(r'[\x00-\x1f\x7f]')


def _decode(raw):
    # 엑셀의 "CSV UTF-8"은 BOM 이 붙고, 예전 "CSV"는 cp949 다. 둘 다 받는다.
    for enc in ('utf-8-sig', 'cp949'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return None


def parse(upload):
    """(정상 행 목록, 건너뛴 번호 목록, 오류 문장 목록). 오류가 있으면 정상 행은 쓰지 않는다."""
    if not upload.name.lower().endswith('.csv'):
        return [], [], ['CSV 파일(.csv)만 올릴 수 있습니다.']
    if upload.size > MAX_BYTES:
        return [], [], [f'파일이 너무 큽니다(최대 {MAX_BYTES // 1000} KB).']
    text = _decode(upload.read(MAX_BYTES + 1))
    if text is None:
        return [], [], ['글자 인코딩을 읽지 못했습니다. 엑셀에서 "CSV UTF-8"로 저장해 올려 주세요.']

    reader = csv.reader(io.StringIO(text))
    try:
        head = [h.strip() for h in next(reader)]
    except StopIteration:
        return [], [], ['빈 파일입니다.']
    if head != HEADER:
        return [], [], [f'첫 줄이 "{",".join(HEADER)}" 이어야 합니다.']

    existing = set(Child.objects.values_list('number', flat=True))
    codes = set(Child.objects.exclude(code=None).values_list('code', flat=True))
    rows, skipped, errors, seen = [], [], [], set()
    for line, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) + len(skipped) >= MAX_ROWS:
            errors.append(f'{MAX_ROWS}명을 넘습니다. 나눠서 올려 주세요.')
            break
        if len(cells) != 4:
            errors.append(f'{line}줄: 칸이 4개여야 합니다.')
            continue
        number, name, code, tel = (c.strip() for c in cells)
        if not (number.isascii() and number.isdigit() and 0 < int(number) < 10_000):
            errors.append(f'{line}줄: 출석번호는 1~9999 의 숫자여야 합니다.')
            continue
        number = int(number)
        if number in seen:
            errors.append(f'{line}줄: 출석번호 {number} 가 파일 안에서 겹칩니다.')
            continue
        seen.add(number)
        if number in existing:
            skipped.append(number)
            continue
        if not name or len(name) > 20 or _CTRL.search(name) or name.startswith(FORMULA_START):
            errors.append(f'{line}줄: 이름은 20자 이하이고 제어 문자·수식 기호(=+-@)로 시작할 수 없습니다.')
            continue
        if code and not (code.isascii() and code.isdigit() and len(code) <= 10):
            errors.append(f'{line}줄: 인식번호는 10자리 이하 숫자여야 합니다.')
            continue
        if code and code in codes:
            errors.append(f'{line}줄: 인식번호가 이미 쓰이고 있습니다(파일 안 겹침 포함).')
            continue
        if not _TEL.match(tel):
            errors.append(f'{line}줄: 연락처는 숫자·+·-·공백 20자 이하여야 합니다.')
            continue
        if code:
            codes.add(code)
        rows.append(Child(number=number, name=name, code=code or None, guardian_tel=tel))
    if not rows and not skipped and not errors:
        errors.append('가져올 행이 없습니다.')
    return rows, skipped, errors
