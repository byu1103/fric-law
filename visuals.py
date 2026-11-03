"""Optional cited visuals requiring explicit human review of the supplied facts."""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import tempfile
from pathlib import Path

from core import WORKSPACE, canonical


def _safe_html(value):
    # Folium may embed labels in JavaScript template literals as well as HTML.
    return html.escape(value, quote=True).replace('`', '&#96;').replace('$', '&#36;').replace('\\', '&#92;')


def _metadata(path, payload):
    path.with_suffix('.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _output(kind, payload, suffix):
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    directory = WORKSPACE / 'visuals'
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f'{kind}_{digest}{suffix}'


def location_map(project, lat, lon, location_source_url, *, coordinates_verified=False):
    if not coordinates_verified:
        raise ValueError('Cần xác nhận đã đối chiếu tọa độ với nguồn đáng tin cậy.')
    if not isinstance(project, str) or not project.strip():
        raise ValueError('Cần tên dự án cụ thể, không dùng tọa độ mặc định cho dự án.')
    if isinstance(lat, bool) or isinstance(lon, bool):
        raise ValueError('Tọa độ không hợp lệ.')
    try:
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        raise ValueError('Tọa độ không hợp lệ.') from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Tọa độ không hợp lệ.')
    source = canonical(location_source_url)
    import folium

    title = _safe_html(project.strip())
    link = _safe_html(source)
    popup = f'<strong>{title}</strong><br>坐标来源：<a href="{link}" target="_blank" rel="noopener noreferrer">{link}</a>'
    mapping = folium.Map(location=[lat, lon], zoom_start=10, tiles='OpenStreetMap')
    folium.Marker([lat, lon], tooltip=title, popup=folium.Popup(popup, max_width=500)).add_to(mapping)
    # The citation remains visible even when the marker popup is closed.
    mapping.get_root().html.add_child(
        folium.Element(
            '<div style="position:fixed;bottom:32px;left:12px;z-index:9999;background:white;'
            'padding:10px;max-width:70%;overflow-wrap:anywhere;font:13px sans-serif">'
            f'{title} · 已由编辑核验所提供坐标<br>坐标来源：<a href="{link}" target="_blank" '
            f'rel="noopener noreferrer">{link}</a></div>'
        )
    )
    metadata = {
        'project': project.strip(),
        'latitude': lat,
        'longitude': lon,
        'source_url': source,
        'coordinates_verified_by_editor': True,
        'kind': 'coordinate_map',
        'inferred_coordinates': False,
    }
    output = _output('project_map', metadata, '.html')
    mapping.save(str(output))
    _metadata(output, metadata)
    return output


def fact_visual(title, fact, source_url, *, reviewed=False):
    if not reviewed:
        raise ValueError('Cần biên tập viên xác nhận dữ kiện và nguồn trước khi tạo thẻ.')
    if not isinstance(title, str) or not title.strip() or not isinstance(fact, str) or not fact.strip():
        raise ValueError('Điền tiêu đề và một dữ kiện đã kiểm chứng.')
    source = canonical(source_url)
    from PIL import Image, ImageDraw, ImageFont

    candidates = [
        '/System/Library/Fonts/PingFang.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    ]
    font_path = next((path for path in candidates if Path(path).is_file()), None)
    if not font_path:
        raise RuntimeError('Cài font PingFang hoặc Noto Sans CJK để vẽ chữ Trung.')
    image = Image.new('RGB', (1200, 630), '#f5f6f4')
    drawing = ImageDraw.Draw(image)
    heading = ImageFont.truetype(font_path, 44)
    normal = ImageFont.truetype(font_path, 34)
    small = ImageFont.truetype(font_path, 18)
    brand = ImageFont.truetype(font_path, 28)

    def wrap(text, font, width):
        lines, line = [], ''
        for character in text.replace('\r', '').replace('\n', ' '):
            if line and drawing.textlength(line + character, font=font) > width:
                lines.append(line)
                line = character
            else:
                line += character
        if line:
            lines.append(line)
        return lines

    title_lines = wrap(title.strip(), heading, 990)
    fact_lines = wrap(fact.strip(), normal, 990)
    source_lines = wrap('来源：' + source, small, 990)
    if len(title_lines) > 2 or len(fact_lines) > 3 or len(source_lines) > 6:
        raise ValueError('Nội dung quá dài cho thẻ; rút gọn câu chữ hoặc URL gốc. Không tự cắt dữ kiện.')
    drawing.rounded_rectangle([42, 35, 1158, 610], radius=20, fill='white')
    drawing.rectangle([42, 35, 55, 610], fill='#184f56')
    drawing.text((90, 65), 'FRIC LAW | 越南投资观察 · 资料卡', font=brand, fill='#184f56')
    for index, line in enumerate(title_lines):
        drawing.text((90, 125 + index * 60), line, font=heading, fill='#193038')
    for index, line in enumerate(fact_lines):
        drawing.text((90, 260 + index * 44), line, font=normal, fill='#405b61')
    for index, line in enumerate(source_lines):
        drawing.text((90, 430 + index * 21), line, font=small, fill='#526e76')
    drawing.text((90, 577), '编辑已确认所提供事实及来源 · 非项目实景或效果图', font=small, fill='#526e76')
    metadata = {
        'title': title.strip(),
        'fact': fact.strip(),
        'source_url': source,
        'reviewed_by_editor': True,
        'kind': 'sourced_fact_card',
        'actual_project_rendering': False,
    }
    output = _output('fact_visual', metadata, '.png')
    fd, temporary = tempfile.mkstemp(prefix=output.stem + '.', suffix='.png', dir=output.parent)
    os.close(fd)
    try:
        image.save(temporary, format='PNG')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    _metadata(output, metadata)
    return output


def generate_ai_image(prompt: str, title: str | None = None) -> Path:
    """Generate a conceptual illustration for editorial use via AI image synthesis."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('Vui lòng nhập mô tả (prompt) để tạo ảnh minh họa AI.')
    prompt = prompt.strip()
    if len(prompt) > 2000:
        prompt = prompt[:2000]

    import urllib.error
    import urllib.parse
    import urllib.request

    encoded_prompt = urllib.parse.quote(prompt)
    url = f'https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true'

    metadata = {
        'prompt': prompt,
        'title': (title or '').strip(),
        'kind': 'ai_conceptual_illustration',
        'is_conceptual_illustration': True,
        'actual_project_rendering': False,
    }
    output = _output('ai_image', metadata, '.jpg')

    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'FRIC-LAW-Studio/1.0'},
    )
    try:
        with urllib.request.urlopen(req, timeout=40.0) as response:
            image_data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (402, 429, 503):
            raise RuntimeError(
                'Dịch vụ tạo ảnh AI miễn phí đang bận hoặc cần chờ giãn cách (khoảng 15-30 giây). Vui lòng thử lại sau ít giây.'
            ) from exc
        raise RuntimeError('Không thể tạo ảnh AI lúc này. Kiểm tra kết nối mạng rồi thử lại.') from exc
    except Exception as exc:
        raise RuntimeError('Không thể tạo ảnh AI lúc này. Kiểm tra kết nối mạng rồi thử lại.') from exc

    if not image_data or len(image_data) < 1000:
        raise RuntimeError('Ảnh tạo từ AI không hợp lệ hoặc dữ liệu trống.')

    fd, temporary = tempfile.mkstemp(prefix=output.stem + '.', suffix='.jpg', dir=output.parent)
    os.close(fd)
    try:
        Path(temporary).write_bytes(image_data)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    _metadata(output, metadata)
    return output

