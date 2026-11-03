"""AI Box drafting adapter with bounded requests and safe, actionable errors.

AI output is a draft, never independent evidence or an editorial approval.
Connection checks are explicit user actions, not automatic page-render probes.
"""

from __future__ import annotations

import os
import re

from settings import (
    AIBOX_BASE_URL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_MODEL,
    GEMINI_BASE_URL,
    reload_local_settings,
)


def _active_provider():
    p = os.getenv('AI_PROVIDER', '').strip().lower()
    if p in ('gemini', 'aibox'):
        return p
    if os.getenv('GEMINI_API_KEY', '').strip() and not os.getenv('AIBOX_API_KEY', '').strip():
        return 'gemini'
    return 'aibox'


def _configuration(api_key=None, model=None):
    try:
        reload_local_settings()
    except (OSError, ValueError):
        raise AIServiceError(
            'invalid_configuration',
            'Không đọc được cấu hình AI Box cục bộ. Kiểm tra quyền truy cập tệp .env.',
        ) from None
    provider = _active_provider()
    if provider == 'gemini':
        key = os.getenv('GEMINI_API_KEY', '') if api_key is None else api_key
        selected = os.getenv('GEMINI_MODEL', DEFAULT_GEMINI_MODEL) if model is None else model
    else:
        key = os.getenv('AIBOX_API_KEY', '') if api_key is None else api_key
        selected = os.getenv('AIBOX_MODEL', DEFAULT_MODEL) if model is None else model
    if not isinstance(key, str) or not key.strip():
        if provider == 'gemini':
            raise AIServiceError(
                'missing_key',
                'Chưa cấu hình Google Gemini API Key. Tạo khóa miễn phí tại https://aistudio.google.com/apikey rồi nhập vào website.',
            )
        raise AIServiceError(
            'missing_key',
            'Chưa cấu hình AIBOX_API_KEY. Nhập khóa AI Box trong phần kết nối AI của ứng dụng; khóa và quota ChatGPT/Codex được giữ riêng.',
        )
    if len(key) > 4096 or any(character in key for character in '\r\n\x00'):
        raise AIServiceError('invalid_configuration', 'Khóa AI Box không hợp lệ; nhập lại khóa một dòng.')
    if not isinstance(selected, str) or not selected.strip():
        selected = DEFAULT_GEMINI_MODEL if provider == 'gemini' else DEFAULT_MODEL
    selected = selected.strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', selected) or '://' in selected:
        raise AIServiceError('invalid_configuration', 'Tên model AI Box không hợp lệ; kiểm tra cấu hình AI.')
    return key.strip(), selected


class AIServiceError(RuntimeError):
    """Only safe, predefined text may cross the boundary into the dashboard."""

    def __init__(self, code: str, message: str, status_code=None, request_id=None):
        self.code = code
        self.message = message
        self.status_code = status_code if isinstance(status_code, int) and 100 <= status_code <= 599 else None
        self.request_id = _safe_request_id(request_id)
        super().__init__(message)


def _safe_request_id(value, secrets=()):
    """Accept only known opaque ID formats, never arbitrary provider/header text."""
    if not isinstance(value, str) or not re.fullmatch(
        r'(?:20[0-9]{15}[A-Za-z0-9]{8,48}|req_[A-Za-z0-9]{16,80}|'
        r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})',
        value,
    ):
        return None
    configured_secrets = [
        item
        for name, item in os.environ.items()
        if any(marker in name.upper() for marker in ('KEY', 'SECRET', 'TOKEN', 'PASSWORD'))
    ]
    for secret in (*configured_secrets, *secrets):
        if isinstance(secret, str) and len(secret) >= 8 and (secret in value or value in secret):
            return None
    return value


def _request_id(error, detail, secrets=()):
    response = getattr(error, 'response', None)
    headers = getattr(response, 'headers', {})
    for name in ('x-request-id', 'x-oneapi-request-id'):
        candidate = _safe_request_id(headers.get(name), secrets)
        if candidate:
            return candidate
    # New API may include the ID only inside this delimited suffix. The rest of
    # the provider message is untrusted and never becomes user-visible text.
    message = detail.get('message')
    if isinstance(message, str):
        match = re.search(r'\(request id: ?([^()\s]{1,100})\)', message[:4096], flags=re.IGNORECASE)
        if match:
            return _safe_request_id(match.group(1), secrets)
    return None



def _service_error(error, sdk, *, api_key=None, sensitive_text=()):
    # Never include the provider message, response body, request, or credential.
    if isinstance(error, sdk.APITimeoutError):
        return AIServiceError('timeout', 'AI Box phản hồi quá thời gian chờ. Kiểm tra mạng rồi thử lại.')
    if isinstance(error, sdk.APIConnectionError):
        return AIServiceError(
            'connection', 'Không kết nối được AI Box. Kiểm tra Internet, VPN hoặc tường lửa rồi thử lại.'
        )
    status = getattr(error, 'status_code', None)
    body = getattr(error, 'body', None)
    detail = body.get('error', body) if isinstance(body, dict) else {}
    if not isinstance(detail, dict):
        detail = {}
    request_id = _request_id(error, detail, (api_key, *sensitive_text))

    def failure(code, message):
        return AIServiceError(code, message, status_code=status, request_id=request_id)

    if status == 401 or (
        status == 400
        and any(
            marker in str(detail.get('message', '')) or marker in str(detail.get('code', ''))
            for marker in ('API_KEY_INVALID', 'API key not valid')
        )
    ):
        return failure(
            'authentication',
            'Khóa API không được chấp nhận hoặc đã bị thu hồi. Nhập khóa API còn hiệu lực.',
        )
    if status == 403:
        return failure(
            'forbidden', 'AI Box từ chối quyền truy cập. Kiểm tra quyền tài khoản và model đã chọn.'
        )
    if status == 404:
        return failure(
            'model_not_found',
            'AI Box không tìm thấy model hoặc tài khoản chưa có quyền dùng model đã chọn. Kiểm tra tên model.',
        )
    if status == 429:
        identifiers = [getattr(error, 'code', None), getattr(error, 'type', None)]
        identifiers.extend((detail.get('code'), detail.get('type')))
        quota_codes = (
            'insufficient_quota',
            'billing_hard_limit_reached',
            'billing_not_active',
            'credit_balance_exhausted',
            'organization_spend_limit_exceeded',
            'project_spend_limit_exceeded',
            'organization_usage_limit_exceeded',
        )
        if any(isinstance(value, str) and value in quota_codes for value in identifiers):
            return failure(
                'quota_exceeded',
                'Tài khoản AI Box đã hết hạn mức hoặc chưa có số dư. Kiểm tra số dư và hạn mức tại AI Box; quota ChatGPT/Codex được giữ riêng.',
            )
        return failure(
            'rate_limit',
            'Đã chạm giới hạn tốc độ AI Box. Chờ một lúc rồi thử lại; yêu cầu chưa được tự động gửi lại.',
        )
    # AI Box's gateway returns HTTP 503 with model_not_found when the key's
    # account group has no active upstream channel. It is not a generic outage.
    model_codes = ('model_not_found', 'no_available_channel', 'model_unavailable')
    if any(
        isinstance(value, str) and value in model_codes
        for value in (getattr(error, 'code', None), detail.get('code'))
    ):
        return failure(
            'model_unavailable',
            'Model đã chọn chưa có kênh phục vụ khả dụng cho nhóm tài khoản của khóa AI Box. '
            'Kiểm tra nhóm/quyền model của API key tại AI Box hoặc nhờ AI Box mở kênh; '
            'chọn model khác rồi kiểm tra sinh văn bản trước khi soạn bài. '
            'Ứng dụng chưa tự đổi model hoặc gửi lại yêu cầu.',
        )
    if isinstance(status, int) and status >= 500:
        return failure('server_error', 'Dịch vụ AI Box đang gặp sự cố. Thử lại sau ít phút.')
    if status in (400, 422):
        return failure(
            'invalid_request',
            'AI Box không chấp nhận yêu cầu. Kiểm tra model và rút ngắn tài liệu nguồn nếu quá dài.',
        )
    return failure(
        'service_error', 'Không hoàn tất được yêu cầu AI Box. Kiểm tra kết nối và cấu hình AI rồi thử lại.'
    )


def _value(item, field, default=None):
    return item.get(field, default) if isinstance(item, dict) else getattr(item, field, default)


def _completed_text(response, probe=False):
    choices = _value(response, 'choices')
    if not isinstance(choices, (list, tuple)) or not choices:
        raise AIServiceError('empty', 'AI Box không trả về văn bản bản nháp. Hãy thử lại hoặc viết thủ công.')
    choice = choices[0]
    message = _value(choice, 'message')
    finish_reason = _value(choice, 'finish_reason')
    if finish_reason == 'content_filter' or _value(message, 'refusal'):
        raise AIServiceError(
            'refused',
            'AI Box từ chối tạo nội dung cho yêu cầu này. Kiểm tra nguồn và hướng dẫn biên tập trước khi thử lại.',
        )
    if _value(message, 'tool_calls') or _value(message, 'function_call'):
        raise AIServiceError(
            'incomplete',
            'Phản hồi AI chưa hoàn tất hoặc đã chạm giới hạn độ dài. Chưa lưu bản nháp; rút ngắn nguồn hoặc thử lại.',
        )
    has_probe_text = bool(_value(message, 'content') or _value(message, 'reasoning_content'))
    if finish_reason != 'stop' and not (probe and finish_reason == 'length' and has_probe_text):
        raise AIServiceError(
            'incomplete',
            'Phản hồi AI chưa hoàn tất hoặc đã chạm giới hạn độ dài. Chưa lưu bản nháp; rút ngắn nguồn hoặc thử lại.',
        )
    text = _value(message, 'content')
    if probe and (not isinstance(text, str) or not text.strip()) and _value(message, 'reasoning_content'):
        text = 'OK'
    if not isinstance(text, str) or not text.strip():
        raise AIServiceError('empty', 'AI Box không trả về văn bản bản nháp. Hãy thử lại hoặc viết thủ công.')
    return text.strip()


def _isolated_headers(sdk, key):
    # The SDK also inherits OPENAI_CUSTOM_HEADERS. Suppress those headers on this
    # client only, including authorization or organization/project overrides.
    # No process environment, Codex config, or ChatGPT credential is changed.
    headers = {}
    for line in os.getenv('OPENAI_CUSTOM_HEADERS', '').splitlines():
        name, separator, _ = line.partition(':')
        if separator and name.strip():
            headers[name.strip()] = sdk.omit
    headers.update(
        {
            'Authorization': f'Bearer {key}',
            'OpenAI-Organization': sdk.omit,
            'OpenAI-Project': sdk.omit,
        }
    )
    return headers


def _request(instructions, source_input, *, api_key=None, model=None, probe=False):
    key, selected = _configuration(api_key, model)
    provider = _active_provider()
    base_url = GEMINI_BASE_URL if provider == 'gemini' else AIBOX_BASE_URL
    try:
        import openai
    except ImportError:
        raise AIServiceError(
            'missing_library', 'Thiếu thư viện OpenAI SDK để kết nối AI. Cài lại requirements.txt.'
        ) from None
    try:
        with openai.DefaultHttpxClient(follow_redirects=False) as transport:
            with openai.OpenAI(
                api_key=key,
                base_url=base_url,
                organization='',
                project='',
                admin_api_key='',
                default_headers=_isolated_headers(openai, key),
                timeout=20.0 if probe else 90.0,
                max_retries=0,
                http_client=transport,
            ) as client:
                response = client.chat.completions.create(
                    model=selected,
                    messages=[
                        {'role': 'system', 'content': instructions},
                        {'role': 'user', 'content': source_input},
                    ],
                    max_tokens=32 if probe else 4096,
                    stream=False,
                )
    except Exception as error:
        raise _service_error(
            error, openai, api_key=key, sensitive_text=(instructions, source_input)
        ) from None
    return _completed_text(response, probe=probe), selected


def check_ai_connection(api_key=None, model=None):
    """Explicit, tiny API probe; no source text or draft is sent."""
    _, selected = _request(
        'This is a connection check. Reply only with OK.',
        'OK',
        api_key=api_key,
        model=model,
        probe=True,
    )
    return {'ok': True, 'model': selected, 'provider': _active_provider()}


def draft_text(instructions, input):
    """Return a completed text draft; refusals/partial output never become drafts."""
    text, _ = _request(instructions, input)
    return text
