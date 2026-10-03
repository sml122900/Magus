"""운영자 알림. ERROR 로그(logsafe가 내용을 거른 뒤의 종류·위치)를 메신저로 보낸다.

환경변수(하나만 쓴다. 둘 다 있으면 텔레그램)
- ALERT_TELEGRAM_BOT_TOKEN + ALERT_TELEGRAM_CHAT_ID: 텔레그램 봇
- ALERT_WEBHOOK_URL: JSON 웹훅. {"text": …, "content": …}를 보내므로 Slack(text)·Discord(content) 둘 다 받는다

보내기는 백그라운드 스레드에서 한다(요청을 막지 않는다). 실패해도 로그를 남기지 않는다(알림 실패가 다시 알림을 부르지 않게).
"""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Callable, Mapping


def _post(url: str, body: dict[str, object]) -> None:
    request = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=5):  # noqa: S310 - 운영자가 설정한 주소만
        pass


def sender(env: Mapping[str, str]) -> Callable[[str], None] | None:
    """설정이 없으면 None(알림 끔). 있으면 send(text) — 즉시 돌아오고 보내기는 뒤에서 한다."""
    token, chat = env.get("ALERT_TELEGRAM_BOT_TOKEN"), env.get("ALERT_TELEGRAM_CHAT_ID")
    webhook = env.get("ALERT_WEBHOOK_URL")
    if token and chat:
        url, make = f"https://api.telegram.org/bot{token}/sendMessage", lambda text: {"chat_id": chat, "text": text}
    elif webhook:
        url, make = webhook, lambda text: {"text": text, "content": text}
    else:
        return None

    def deliver(text: str) -> None:
        try:
            _post(url, make(text[:3500]))
        except Exception:  # noqa: BLE001 - 알림 실패는 조용히 버린다
            pass

    def send(text: str) -> None:
        threading.Thread(target=deliver, args=(text,), daemon=True).start()

    send.deliver = deliver  # type: ignore[attr-defined]  # 테스트·alert-test는 기다려서 보낸다
    return send
