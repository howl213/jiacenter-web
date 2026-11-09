import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_BOLD = re.compile(r'\*\*(.+?)\*\*')


@register.filter
def notice_format(text):
    """공지 본문의 간단한 서식: **굵게**, ## 소제목, - 목록, 빈 줄은 문단, 줄바꿈은 <br>.

    먼저 전체를 escape 한 다음에 고정된 태그만 끼워 넣는다. 사용자가 쓴 HTML·속성·링크는
    들어갈 자리가 없다 — 그래서 mark_safe 를 써도 된다. 링크와 이미지는 일부러 지원하지 않는다
    (javascript: 주소 같은 우회가 생기므로).
    """
    out, items = [], []

    def inline(s):
        return _BOLD.sub(r'<strong>\1</strong>', escape(s))

    def flush():
        if items:
            out.append('<ul>' + ''.join(f'<li>{inline(i)}</li>' for i in items) + '</ul>')
            items.clear()

    paragraph = []

    def end_paragraph():
        if paragraph:
            out.append('<p>' + '<br>'.join(inline(l) for l in paragraph) + '</p>')
            paragraph.clear()

    for line in (text or '').replace('\r\n', '\n').split('\n'):
        if line.startswith('- '):
            end_paragraph()
            items.append(line[2:])
            continue
        flush()
        if line.startswith('## '):
            end_paragraph()
            out.append(f'<h3>{inline(line[3:])}</h3>')
        elif line.strip() == '':
            end_paragraph()
        else:
            paragraph.append(line)
    flush()
    end_paragraph()
    # 모든 사용자 글은 inline() 에서 escape 를 거친다. 이 줄을 고치면 test_html_* XSS 시험이 통과하는지 본다.
    return mark_safe(''.join(out))  # nosec B703 B308
