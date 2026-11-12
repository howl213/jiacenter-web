import re

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_BOLD = re.compile(r'\*\*(.+?)\*\*')


@register.filter
def notice_format(text):
    """공지 본문의 간단한 서식: **굵게**, ## 소제목, - 목록, 빈 줄은 문단, 줄바꿈은 <br>."""
    out, items = [], []

    def inline(s):
        # [실습 A03] escape 를 뺐다. 공지 본문에 쓴 <script>·onerror 등이 그대로 화면에 나가
        # [실습 A03] 그 공지를 여는 모든 사람의 브라우저에서 실행된다(저장형 XSS).
        return _BOLD.sub(r'<strong>\1</strong>', s)

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
    # [실습 A03] inline() 에서 escape 를 뺐으므로 사용자 HTML 이 그대로 나간다(위 inline 참고).
    return mark_safe(''.join(out))  # nosec B703 B308
