"""Bounded text-only Messages SSE accumulation. Never replay an interrupted stream."""
import json
import time
from .provider import ProviderResponseError, ProviderUnavailableError


def read_message(response, *, limit, deadline, cancelled, clock=time.monotonic):
    started = False
    block = False
    closed = False
    delta_seen = False
    parts = []
    usage = {}
    reason = None
    event = ''
    data = []
    received = 0
    count = 0
    while True:
        cancelled()
        if clock() > deadline:
            raise TimeoutError
        line = response.readline(min(262145, limit - received + 1))
        received += len(line)
        if received > limit or len(line) > 262144:
            raise ProviderResponseError('API 스트림 크기 제한을 초과했습니다.')
        if clock() > deadline:
            raise TimeoutError
        if not line:
            raise ProviderUnavailableError('완료되지 않은 API 스트림입니다. 자동 재요청하지 않습니다.')
        try:
            text = line.decode('utf8').rstrip('\r\n')
        except UnicodeError:
            raise ProviderResponseError('API 스트림 인코딩을 확인하지 못했습니다.') from None
        if text.startswith(':'):
            continue
        if text.startswith('event:'):
            event = text[6:].strip()
            continue
        if text.startswith('data:'):
            data.append(text[5:].lstrip())
            continue
        if text or not data:
            continue
        count += 1
        if count > 20000:
            raise ProviderResponseError('API 스트림 이벤트 제한을 초과했습니다.')
        try:
            item = json.loads('\n'.join(data))
            if not isinstance(item, dict) or item.get('type') != event:
                raise ValueError
            data = []
            if event == 'error':
                raise ProviderUnavailableError('API 스트림이 중단됐습니다. 자동 재요청하지 않습니다.')
            if event == 'message_start':
                if started or item['message'].get('content') != []:
                    raise ValueError
                started = True
                usage = dict(item['message'].get('usage', {}))
            elif event == 'content_block_start':
                value = item['content_block']
                if not started or block or closed or item['index'] != 0 or value['type'] != 'text':
                    raise ValueError
                block = True
                parts.append(value['text'])
            elif event == 'content_block_delta':
                value = item['delta']
                if not block or closed or item['index'] != 0 or value['type'] != 'text_delta':
                    raise ValueError
                parts.append(value['text'])
            elif event == 'content_block_stop':
                if not block or closed or item['index'] != 0:
                    raise ValueError
                closed = True
            elif event == 'message_delta':
                if not started or not closed:
                    raise ValueError
                reason = item['delta'].get('stop_reason', reason)
                usage.update(item.get('usage', {}))
                delta_seen = delta_seen or 'output_tokens' in item.get('usage', {})
            elif event == 'message_stop':
                if not started or not closed or not delta_seen or not isinstance(reason, str):
                    raise ValueError
                if not all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens','output_tokens')):
                    raise ValueError
                result = {'stop_reason': reason, 'content': [{'type':'text','text': ''.join(parts)}], 'usage':usage}
                raw = json.dumps(result, ensure_ascii=False).encode('utf8')
                if len(raw) > limit:
                    raise ValueError
                return raw
            # Ping and future unrelated event types cannot manufacture completion.
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise ProviderResponseError('완료된 API 스트림 형식을 확인하지 못했습니다.') from None
