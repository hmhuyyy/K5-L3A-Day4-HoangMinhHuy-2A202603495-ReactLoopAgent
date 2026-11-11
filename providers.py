"""Bốn provider cùng một interface. Không chứa agent loop."""
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit

CONFIG = {
    'openai': ('OPENAI_API_KEY', 'https://api.openai.com/v1/chat/completions'),
    'gemini': ('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'),
    'openrouter': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1/chat/completions'),
    'anthropic': ('ANTHROPIC_API_KEY', 'https://api.anthropic.com/v1/messages'),
}


def post_json(url, headers, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = ''
        response_body = ''
        try:
            response_body = exc.read(4096).decode('utf-8', errors='replace')
            body = json.loads(response_body)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        error = body.get('error') if isinstance(body, dict) else None
        if isinstance(error, dict):
            status = error.get('status')
            message = error.get('message')
            parts = [value for value in (status, message) if isinstance(value, str) and value]
            detail = ': ' + ' — '.join(parts) if parts else ''
            for name, value in headers.items():
                if name.casefold() in ('authorization', 'x-api-key', 'api-key') and isinstance(value, str):
                    credential = value.removeprefix('Bearer ').strip()
                    if credential:
                        detail = detail.replace(credential, '[REDACTED]')
        if not detail and response_body:
            detail = ': ' + response_body
        detail = re.sub(r'AIza[0-9A-Za-z_-]{20,}', '[REDACTED]', detail)
        for name, value in headers.items():
            if name.casefold() in ('authorization', 'x-api-key', 'api-key') and isinstance(value, str):
                credential = value.removeprefix('Bearer ').strip()
                if credential:
                    detail = detail.replace(credential, '[REDACTED]')
        detail = detail[:600]
        raise RuntimeError(
            f'Provider trả HTTP {exc.code}{detail}; kiểm tra model, key và quota.'
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Không kết nối được provider: {exc.reason}') from exc


class Provider:
    """complete(messages, schemas) -> {message, calls, finish, usage}.

    messages: system/user/assistant/tool theo format Chat Completions. message trả về
    cần được append nguyên vẹn; tool result có role, tool_call_id, content (JSON string).
    """
    def __init__(self, name, model):
        if name not in CONFIG:
            raise ValueError(f'Provider không hợp lệ: {name}')
        if not model:
            raise ValueError('Cần đặt MODEL là model có hỗ trợ tool calling.')
        self.name, self.model = name, model
        key_name, self.url = CONFIG[name]
        if name == 'openai':
            base_url = os.getenv('OPENAI_BASE_URL')
            if base_url:
                parsed_url = urlsplit(base_url)
                if (
                    parsed_url.scheme != 'https'
                    or not parsed_url.netloc
                    or parsed_url.username is not None
                    or parsed_url.password is not None
                    or parsed_url.query
                    or parsed_url.fragment
                ):
                    raise ValueError(
                        'OPENAI_BASE_URL phải là HTTPS URL hợp lệ, không chứa credentials, query hoặc fragment.'
                    )
                self.url = f'{base_url.rstrip("/")}/chat/completions'
        if name == 'anthropic':
            base_url = os.getenv('ANTHROPIC_BASE_URL')
            if base_url:
                parsed_url = urlsplit(base_url)
                if (
                    parsed_url.scheme != 'https'
                    or not parsed_url.netloc
                    or parsed_url.username is not None
                    or parsed_url.password is not None
                    or parsed_url.query
                    or parsed_url.fragment
                ):
                    raise ValueError(
                        'ANTHROPIC_BASE_URL phải là HTTPS URL hợp lệ, không chứa credentials, query hoặc fragment.'
                    )
                self.url = f'{base_url.rstrip("/")}/v1/messages'
        self.key = os.getenv(key_name)
        if not self.key:
            raise ValueError(f'Thiếu {key_name}; xem README.md.')

    def complete(self, messages, schemas):
        if self.name == 'anthropic':
            return self._anthropic(messages, schemas)
        if self.name == 'gemini' and os.getenv('GOOGLE_GEMINI_BASE_URL'):
            return self._gemini_native(messages, schemas)
        payload = {'model': self.model, 'messages': messages}
        if schemas:
            payload['tools'] = schemas
        data = post_json(self.url, {'Authorization': f'Bearer {self.key}'}, payload)
        choice = data['choices'][0]
        message = choice['message']
        calls = [{'id': c['id'], 'name': c['function']['name'], 'arguments': c['function']['arguments']} for c in message.get('tool_calls', [])]
        return {'message': message, 'calls': calls, 'finish': choice.get('finish_reason'), 'usage': data.get('usage', {})}

    def _gemini_native(self, messages, schemas):
        base_url = os.getenv('GOOGLE_GEMINI_BASE_URL', '').rstrip('/')
        parsed_url = urlsplit(base_url)
        if (
            parsed_url.scheme != 'https'
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(
                'GOOGLE_GEMINI_BASE_URL phải là HTTPS URL hợp lệ, không chứa credentials, query hoặc fragment.'
            )

        system_parts = []
        contents = []
        function_names = {
            call.get('id'): call.get('function', {}).get('name')
            for item in messages
            if item.get('role') == 'assistant'
            for call in item.get('tool_calls', [])
        }
        for item in messages:
            role = item.get('role')
            if role == 'system':
                system_parts.append({'text': item.get('content') or ''})
            elif role == 'user':
                contents.append({'role': 'user', 'parts': [{'text': item.get('content') or ''}]})
            elif role == 'assistant':
                parts = []
                if item.get('content'):
                    parts.append({'text': item['content']})
                for tool_call in item.get('tool_calls', []):
                    function = tool_call.get('function', {})
                    parts.append({
                        'functionCall': {
                            'name': function['name'],
                            'args': json.loads(function.get('arguments', '{}')),
                        },
                    })
                contents.append({'role': 'model', 'parts': parts})
            elif role == 'tool':
                response = json.loads(item.get('content') or '{}')
                function_name = function_names.get(item.get('tool_call_id'))
                if not function_name:
                    raise ValueError('Không xác định được tên function cho kết quả Gemini tool.')
                function_response = {
                    'functionResponse': {
                        'name': function_name,
                        'response': response,
                    },
                }
                if contents and contents[-1]['role'] == 'user':
                    contents[-1]['parts'].append(function_response)
                else:
                    contents.append({'role': 'user', 'parts': [function_response]})

        function_declarations = [
            {
                'name': tool['function']['name'],
                'description': tool['function']['description'],
                'parameters': tool['function']['parameters'],
            }
            for tool in schemas
        ]
        payload = {'contents': contents}
        if system_parts:
            payload['systemInstruction'] = {'parts': system_parts}
        if function_declarations:
            payload['tools'] = [{'functionDeclarations': function_declarations}]

        url = f'{base_url}/v1beta/models/{self.model}:generateContent'
        data = post_json(url, {'x-goog-api-key': self.key}, payload)
        candidates = data.get('candidates', [])
        if not candidates or not isinstance(candidates[0], dict):
            raise ValueError('Gemini không trả candidate hợp lệ.')
        candidate = candidates[0]
        content = candidate.get('content', {})
        parts = content.get('parts', []) if isinstance(content, dict) else []
        text = '\n'.join(
            part['text']
            for part in parts
            if isinstance(part, dict) and isinstance(part.get('text'), str)
        )
        calls = [
            {
                'id': f'gemini-{uuid.uuid4().hex}',
                'name': part['functionCall']['name'],
                'arguments': json.dumps(part['functionCall'].get('args', {}), ensure_ascii=False),
            }
            for part in parts
            if isinstance(part, dict) and isinstance(part.get('functionCall'), dict)
        ]
        message = {'role': 'assistant', 'content': text or None}
        if calls:
            message['tool_calls'] = [
                {
                    'id': call['id'],
                    'type': 'function',
                    'function': {
                        'name': call['name'],
                        'arguments': call['arguments'],
                    },
                }
                for call in calls
            ]
        finish_reason = candidate.get('finishReason')
        finish = 'tool_calls' if calls else (
            'stop' if finish_reason == 'STOP' else
            'length' if finish_reason == 'MAX_TOKENS' else
            finish_reason
        )
        return {
            'message': message,
            'calls': calls,
            'finish': finish,
            'usage': data.get('usageMetadata', {}),
        }

    def _anthropic(self, messages, schemas):
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        native = []
        for m in messages:
            if m['role'] == 'system':
                continue
            if m['role'] == 'assistant':
                blocks = []
                if m.get('content'):
                    blocks.append({'type': 'text', 'text': m['content']})
                for call in m.get('tool_calls', []):
                    blocks.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'], 'input': json.loads(call['function']['arguments'])})
                native.append({'role': 'assistant', 'content': blocks})
            elif m['role'] == 'tool':
                block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}
                if native and native[-1]['role'] == 'user' and isinstance(native[-1]['content'], list):
                    native[-1]['content'].append(block)
                else:
                    native.append({'role': 'user', 'content': [block]})
            else:
                native.append({'role': 'user', 'content': m['content']})
        tools = [{'name': x['function']['name'], 'description': x['function']['description'], 'input_schema': x['function']['parameters']} for x in schemas]
        payload = {'model': self.model, 'max_tokens': 2048, 'system': system, 'messages': native}
        if tools:
            payload['tools'] = tools
        data = post_json(self.url, {'x-api-key': self.key, 'anthropic-version': '2023-06-01'}, payload)
        blocks = data['content']
        calls = [{'id': b['id'], 'name': b['name'], 'arguments': json.dumps(b['input'], ensure_ascii=False)} for b in blocks if b['type'] == 'tool_use']
        text = '\n'.join(b['text'] for b in blocks if b['type'] == 'text')
        message = {'role': 'assistant', 'content': text or None}
        if calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]
        reason = {'end_turn': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length'}.get(data.get('stop_reason'), data.get('stop_reason'))
        return {'message': message, 'calls': calls, 'finish': reason, 'usage': data.get('usage', {})}
