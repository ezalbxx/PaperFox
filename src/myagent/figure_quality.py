"""Measured figure checks and physical-size handoff; no VLM claims."""
from __future__ import annotations
import json
import re


FIGURE_LABEL = r'图\s*(\d+(?:[-–－.．]\d+)*)'


def text_layout_check(fig, ax):
    """Check visible text in this axes at the actual export resolution."""
    from matplotlib.text import Text
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    groups = [[t for t in axis.get_ticklabels() if t.get_visible() and t.get_text()]
              for axis in (ax.xaxis, ax.yaxis)]
    issues = []
    for group in groups:
        for i, text in enumerate(group):
            box = text.get_window_extent(renderer)
            if any(box.overlaps(other.get_window_extent(renderer)) for other in group[i + 1:]):
                issues.append('刻度标签重叠：' + text.get_text())
    texts = [t for t in ax.findobj(Text) if t.get_visible() and t.get_text()]
    # Tick objects outside the active limits are not displayed by Matplotlib.
    active = ax.texts + [ax.xaxis.label, ax.yaxis.label, ax.title] + list(fig.texts)
    for text in active:
        if not text.get_text():
            continue
        box = text.get_window_extent(renderer)
        if box.x0 < 0 or box.y0 < 0 or box.x1 > fig.bbox.width or box.y1 > fig.bbox.height:
            issues.append('文字超出画布：' + text.get_text())
    annotations = [t for t in ax.texts if t.get_visible() and t.get_text()]
    for i, text in enumerate(annotations):
        if any(text.get_window_extent(renderer).overlaps(other.get_window_extent(renderer)) for other in annotations[i + 1:]):
            issues.append('数值标注重叠：' + text.get_text())
    legend = ax.get_legend()
    if legend:
        box = legend.get_window_extent(renderer)
        if any(box.overlaps(t.get_window_extent(renderer)) for t in annotations):
            issues.append('图例压住数值标注')
    other_axes = [other for other in fig.axes if other is not ax and other.get_visible()]
    for text in active:
        if text.get_visible() and text.get_text():
            if any(text.get_window_extent(renderer).overlaps(other.bbox) for other in other_axes):
                issues.append('文字与其他绘图区重叠：' + text.get_text())
    fonts = texts + [text for text in fig.texts if text.get_visible() and text.get_text()]
    return {'passed': not issues, 'issues': issues,
            'minimum_font_pt': min((t.get_fontsize() for t in fonts), default=10),
            'scope': '刻度、标注、图例、其他绘图区及画布边界的几何检查'}


def asset_quality(project, asset):
    from .lab_project import digest
    provenance = asset.get('provenance', {})
    if isinstance(provenance, str):
        try:
            provenance = json.loads(project.file(provenance).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            provenance = {}
    spec = provenance.get('render_spec', asset.get('render_spec', {}))
    quality = dict(spec.get('quality', {}))
    if asset.get('sha256') and digest(project.file(asset['path'])) != asset['sha256']:
        return {'status': 'stale', 'reason': '图片已改变，检查失效'}
    return {'status': 'checked' if quality.get('layout_passed') and not quality.get('raster_text_unverified') else 'unverified',
            'design_width_mm': spec.get('width_mm'), 'minimum_font_pt': quality.get('minimum_font_pt'),
            'language': quality.get('language', 'unverified'), **quality}


def placement_check(quality, width_mm, minimum_pt=7):
    design_width = quality.get('design_width_mm')
    font = quality.get('minimum_font_pt')
    effective = font * width_mm / design_width if font and design_width else None
    return {**quality, 'placed_width_mm': width_mm, 'effective_font_pt': effective,
            'size_passed': effective >= minimum_pt if effective is not None else None,
            'minimum_required_pt': minimum_pt}


def numbered_document(document, *, repairs=None):
    """Resolve stable references and unambiguous legacy labels in a display copy."""
    import copy
    result = copy.deepcopy(document)
    numbers = {}
    legacy = {}
    local_labels = []
    for section in result['sections']:
        labels = {}
        local_labels.append(labels)
        for block in section['blocks']:
            if block['type'] == 'image':
                number = len(numbers) + 1
                numbers[block['id']] = number
                caption = block.get('caption', '')
                label = re.match(r'^\s*' + FIGURE_LABEL + r'\s*', caption)
                if label:
                    labels.setdefault(label[1], set()).add(block['id'])
                    legacy.setdefault(label[1], set()).add(block['id'])
                    caption = caption[label.end():]
                block['caption'] = f'图{number} {caption}'
    def resolve(match):
        identifier = match.group(1)
        if identifier not in numbers:
            raise ValueError('未知图表引用ID：' + identifier)
        return '图' + str(numbers[identifier])
    for section, labels in zip(result['sections'], local_labels):
        for block in section['blocks']:
            if block['type'] == 'text':
                def resolve_label(match):
                    choices = labels.get(match[1]) or legacy.get(match[1], set())
                    if len(choices) != 1:
                        raise ValueError(f"稳定图号无法定位：{block['id']} 引用 {match[0]}，候选图片ID={sorted(choices)}")
                    identifier = next(iter(choices))
                    if repairs is not None:
                        repairs.append({'block_id': block['id'], 'old_label': match[0], 'figure_id': identifier})
                    return '{{figure:' + identifier + '}}'
                block['text'] = re.sub(FIGURE_LABEL, resolve_label, block.get('text', ''))
            for field in ('text', 'caption'):
                if field in block:
                    block[field] = re.sub(r'\{\{figure:([^}]+)\}\}', resolve, block[field])
    return result, numbers
