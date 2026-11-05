"""보호자에게 보내는 알림톡. 지금은 '보낸 척'만 한다.

경기도 알림톡 API 승인 전이라 실제 전송 코드가 없다. 대신 보냈어야 할 내용을
NotifyLog 테이블에 sent=False 로 쌓아두므로, 승인 전에도 "언제 누구에게 무엇이
나갔을 것인가"를 그대로 확인할 수 있다.

승인이 나면 고칠 곳은 아래 send_alimtalk() 하나뿐이다. 부르는 쪽(views._toggle)은
전혀 건드리지 않아도 된다 — 그러려고 함수 한 개로 감싸 두었다.
"""

from .models import NotifyLog

# 알림톡은 문구를 미리 등록·심사받아야 하므로, 본문을 코드 여기저기 흩지 않고 한곳에 모아둔다.
# 승인받은 템플릿 문구와 글자 하나까지 같아야 발송이 통과된다.
TEMPLATES = {
    'check_in': '{name} 어린이가 {time}에 센터에 도착했습니다.',
    'check_out': '{name} 어린이가 {time}에 하원했습니다.',
    # absent 는 아직 부르는 곳이 없다. 미입실 아동 보호자에게 보낼 문구로,
    # 발송 시각 정책이 정해지면 그때 연결한다.
    'absent': '{name} 어린이가 아직 센터에 오지 않았습니다. 확인 부탁드립니다.',
}


def send_alimtalk(tel, template, **values):
    """경기도 알림톡 전송. API 승인 전이라 전송하지 않고 기록만 남긴다.

    shortcut: 실제 전송 안 함, 경기도 알림톡 API 승인되면 이 함수 안에서만 호출 추가.
    """
    # 문구를 먼저 만든다. 없는 template 키나 모자란 값은 여기서 바로 에러가 나므로
    # 잘못된 호출이 조용히 묻히지 않는다.
    body = TEMPLATES[template].format(**values)
    # 보호자 연락처가 비어 있는 아동도 있다. 이 경우 기록조차 남기지 않고 조용히 넘어간다
    # — 출결 자체는 이미 저장된 뒤라, 알림 때문에 입/퇴실이 실패하면 안 된다.
    if not tel:
        return None
    # sent=False = 아직 실제로는 안 나갔다는 표시. 승인 후 실제 발송에 성공하면 True 로 바꾼다.
    return NotifyLog.objects.create(tel=tel, template=template, body=body, sent=False)
