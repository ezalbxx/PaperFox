"""Deterministic, reference-directed report rendering from supplied values/graphs."""
from __future__ import annotations

import math
import re


def numeric(values):
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError('图表数值必须是来源中的有限数字')
    return values


def plot_values(value, args, lookup):
    kind = args.get('kind', 'bar')
    if kind == 'heatmap':
        matrix = lookup(value, args['matrix_path'])
        if not isinstance(matrix, list) or not matrix or not isinstance(matrix[0], list) or not matrix[0]:
            raise ValueError('matrix_path需要指向非空二维数值数组')
        n = len(matrix[0])
        if any(not isinstance(row, list) or len(row) != n for row in matrix):
            raise ValueError('热图矩阵每行列数需一致')
        for row in matrix:
            numeric(row)
        return matrix
    series = args.get('series', [])
    if not series:
        raise ValueError('plot需要至少一条series')
    measured = []
    for spec in series:
        if 'path' in spec:
            row = lookup(value, spec['path'])
            if not isinstance(row, list):
                raise ValueError('series.path需要指向完整数值数组')
        else:
            row = [lookup(value, key) for key in spec['paths']]
        if not row:
            raise ValueError('数值序列不能为空')
        measured.append(numeric(row))
    if any(len(row) != len(measured[0]) for row in measured):
        raise ValueError('各数值序列长度需一致')
    if args.get('labels') and len(args['labels']) != len(measured[0]):
        raise ValueError('数值路径必须与条件标签一一对应')
    return measured


def value_format(args, measured):
    mode = args.get('number_format', 'auto' if args.get('reference_ids') else 'float')
    flat = [v for row in measured for v in row]
    if mode == 'int':
        return lambda v: f'{v:.0f}', '%.0f', mode
    if mode == 'percent':
        return lambda v: f'{v:.2%}', 'percent:.2%', mode
    if mode == 'scientific':
        return lambda v: f'{v:.2e}', '%.2e', mode
    if mode == 'auto':
        integer = all(float(v).is_integer() for v in flat)
        return (lambda v: f'{v:.0f}' if integer else f'{v:.4g}'), ('%.0f' if integer else '%.4g'), mode
    if mode != 'float':
        raise ValueError('不支持的number_format')
    return lambda v: f'{v:.2f}', '%.2f', mode


def _pyplot():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


def _style(args):
    design = args.get('design', {})
    width = design.get('width_mm', 165)
    height = design.get('height_mm', 90)
    size = design.get('font_size', 10)
    if not 60 <= width <= 240 or not 30 <= height <= 240 or not 7 <= size <= 18:
        raise ValueError('design宽60—240mm、高30—240mm、字体7—18pt')
    return design, width, height, size


def render_plot(value, args, image, lookup):
    import numpy as np
    from matplotlib.ticker import PercentFormatter
    plt = _pyplot()
    kind = args.get('kind', 'bar')
    if args.get('orientation'):
        expected = {'horizontal': 'barh', 'vertical': 'bar'}.get(args['orientation'])
        if expected != kind:
            raise ValueError('图表方向orientation与kind不一致；横向用barh，纵向用bar')
    if kind in ('bar', 'barh') and ('category_label' in args or 'value_label' in args):
        if not args.get('category_label') or not args.get('value_label'):
            raise ValueError('条形图需同时给出category_label与value_label，由程序映射坐标轴')
        value_label = args['value_label'] + (f"（{args['value_unit']}）" if args.get('value_unit') else '')
        args = {**args, 'xlabel': value_label if kind == 'barh' else args['category_label'],
                'ylabel': args['category_label'] if kind == 'barh' else value_label}
    if kind not in ('bar', 'barh', 'line', 'scatter', 'heatmap'):
        raise ValueError('不支持的图形类型')
    measured = plot_values(value, args, lookup)
    design, width, height, size = _style(args)
    formatter, fmt, mode = value_format(args, measured)
    if args.get('label_language') == 'zh':
        explanations = [args.get(k,'') for k in ('xlabel','ylabel','colorbar_label')]
        explanations += args.get('labels',[]) + args.get('row_labels',[]) + [s.get('label','') for s in args.get('series',[])]
        common_terms = {'epoch', 'epochs', 'batch', 'batches', 'loss', 'accuracy', 'train', 'test',
                        'training', 'validation', 'val', 'step', 'steps', 'iteration', 'iterations',
                        'learning', 'rate', 'cross', 'entropy', 'bce', 'mse', 'mae', 'rmse',
                        'precision', 'recall', 'f1', 'auc', 'roc', 'iou', 'dice', 'gradient',
                        'gradients', 'autograd', 'adam', 'sgd', 'relu', 'softmax', 'sigmoid',
                        'logit', 'logits', 'cpu', 'gpu', 'ms', 's', 'mb', 'gb'}
        def common_technical_label(label):
            words = re.findall(r'[A-Za-z]+\d*', label.lower())
            return bool(words) and all(word in common_terms for word in words)
        foreign = [s for s in explanations if s and re.search(r'[A-Za-z]',s) and not re.search(r'[\u4e00-\u9fff]',s)
                   and not common_technical_label(s)
                   and not re.fullmatch(r'(?:[xyz]\d?|[wbn]|dL/d[wb]|\d+(?:\.\d+)?|[%μa-zA-Z]+/s)',s)]
        if foreign:
            raise ValueError('图内解释性标签以中文为主，通用技术术语可保留；请检查：' + '；'.join(foreign[:4]))
    spec = {'kind': kind, 'xlabel': args.get('xlabel', ''), 'ylabel': args.get('ylabel', ''), 'number_format': mode,
            'value_label_format': fmt, 'width_mm': width, 'height_mm': height}
    # Use rc_context so a figure's reference style does not leak into later plots.
    with plt.rc_context({'font.sans-serif': ['Microsoft YaHei', 'Noto Sans CJK SC', 'DejaVu Sans'], 'axes.unicode_minus': False,
                         'font.size': size, 'svg.fonttype': 'none'}):
        fig, ax = plt.subplots(figsize=(width / 25.4, height / 25.4), dpi=216, layout='constrained')
        try:
            labels = args.get('labels', [])
            if kind == 'heatmap':
                row_labels = args.get('row_labels', [str(i) for i in range(len(measured))])
                labels = labels or [str(i) for i in range(len(measured[0]))]
                if len(row_labels) != len(measured) or len(labels) != len(measured[0]):
                    raise ValueError('热图行/列标签必须匹配矩阵')
                im = ax.imshow(measured, cmap=design.get('cmap', 'Blues'), aspect='auto')
                fig.colorbar(im, ax=ax, label=args.get('colorbar_label', ''))
                ax.set_xticks(range(len(labels)), labels, rotation=45 if len(labels) > 5 else 0, ha='right' if len(labels) > 5 else 'center')
                ax.set_yticks(range(len(row_labels)), row_labels)
                if args.get('annotate', True):
                    for i, row in enumerate(measured):
                        for j, v in enumerate(row):
                            red, green, blue, _ = im.cmap(im.norm(v))
                            channels = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in (red, green, blue)]
                            luminance = sum(c * w for c, w in zip(channels, (.2126, .7152, .0722)))
                            ax.text(j, i, formatter(v), ha='center', va='center', fontsize=max(7, size - 2),
                                    color='white' if luminance < .179 else 'black')
                spec.update(row_labels=row_labels, matrix_path=args['matrix_path'])
            else:
                count = len(measured[0])
                x = numeric(lookup(value, args['x_path'])) if args.get('x_path') else list(range(count))
                if len(x) != count:
                    raise ValueError('x_path长度必须与数值序列一致')
                if args.get('x_path') and kind in ('bar', 'barh'):
                    raise ValueError('数值横轴x_path用于line/scatter；条形图使用labels')
                series = args['series']
                colors = design.get('colors', [])
                for i, (series_spec, row) in enumerate(zip(series, measured)):
                    kwargs = {'label': series_spec['label'], **({'color': colors[i % len(colors)]} if colors else {})}
                    if kind == 'line':
                        ax.plot(x, row, linewidth=1.7, **({'marker': 'o'} if count <= 30 else {}), **kwargs)
                    elif kind == 'scatter':
                        ax.scatter(x, row, s=30, **kwargs)
                    else:
                        bar_width = .78 / len(series)
                        positions = np.arange(count) + (i - (len(series) - 1) / 2) * bar_width
                        bars = ax.barh(positions, row, bar_width, **kwargs) if kind == 'barh' else ax.bar(positions, row, bar_width, **kwargs)
                        if count <= 12:
                            ax.bar_label(bars, labels=[formatter(v) for v in row], padding=3, fontsize=max(7, size - 2))
                if not args.get('x_path'):
                    labels = labels or [str(i) for i in x]
                    if kind == 'barh':
                        ax.set_yticks(x, labels); ax.invert_yaxis()
                    else:
                        ax.set_xticks(x, labels, rotation=20 if len(labels) > 5 and kind != 'line' else 0)
                if mode == 'percent':
                    (ax.xaxis if kind == 'barh' else ax.yaxis).set_major_formatter(PercentFormatter(1, decimals=0))
                if len(series) > 1:
                    ax.legend(frameon=False)
                ax.spines[['top', 'right']].set_visible(False)
                ax.grid(axis='x' if kind == 'barh' else 'y', alpha=.18); ax.set_axisbelow(True)
                if kind == 'barh':
                    ax.margins(x=.18)  # Reserve room for exact percentage/count labels.
                elif kind == 'bar':
                    ax.margins(y=.15)
                spec.update(x_order=x if args.get('x_path') else labels,
                    x_path=args.get('x_path'), legend_labels=[s['label'] for s in series] if len(series) > 1 else [])
                if kind not in ('bar', 'barh') or count > 12:
                    spec['value_label_format'] = None
            ax.set(xlabel=args.get('xlabel', ''), ylabel=args.get('ylabel', ''))
            if design.get('show_title', True):
                if kind == 'heatmap':
                    fig.suptitle(args['title'])
                else:
                    ax.set_title(args['title'])
            from .figure_quality import text_layout_check
            check = text_layout_check(fig, ax)
            if not check['passed'] and kind != 'barh' and any('刻度标签重叠' in issue for issue in check['issues']):
                # Retry label arrangement once at the same physical dimensions.
                for label in ax.get_xticklabels():
                    label.set_rotation(45); label.set_ha('right')
                check = text_layout_check(fig, ax)
            if not check['passed']:
                raise ValueError('数据图布局未通过：' + '；'.join(check['issues'][:4]) +
                    '。缩短/换行标签、改用barh或增大画布后重画，保持字号。')
            explanatory = [args.get(k, '') for k in ('xlabel', 'ylabel', 'colorbar_label')]
            explanatory += list(labels) + [s.get('label', '') for s in args.get('series', [])]
            language = 'zh' if any(re.search(r'[\u4e00-\u9fff]', str(s)) for s in explanatory) else 'unverified'
            # A language declaration alone never establishes pixel-language QA.
            spec['quality'] = {'layout_passed': True, 'minimum_font_pt': check['minimum_font_pt'],
                               'language': language, 'language_basis': 'CJK label presence; identifiers may remain Latin',
                               'layout_check': check}
            fig.savefig(image, dpi=216)
            fig.savefig(image.with_suffix('.svg'))
        finally:
            plt.close(fig)
    return {'labels': labels, 'series': args.get('series', []), 'measured_values': measured, 'render_spec': spec}


def render_diagram(args, image):
    from collections import defaultdict, deque
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    from matplotlib.path import Path as DrawingPath
    plt = _pyplot()
    nodes = args.get('nodes') or [{'id': str(i), 'label': step} for i, step in enumerate(args.get('steps', []))]
    edges = args.get('edges')
    if edges is None:
        edges = [{'from': nodes[i]['id'], 'to': nodes[i + 1]['id']} for i in range(len(nodes) - 1)]
    ids = [n['id'] for n in nodes]
    if not 2 <= len(nodes) <= 12 or len(set(ids)) != len(ids) or any(not n.get('label') or len(n['label']) > 90 for n in nodes):
        raise ValueError('流程图需2—12个唯一节点及简短标签')
    if any(e.get('from') not in ids or e.get('to') not in ids for e in edges):
        raise ValueError('流程图连线必须指向实际节点')
    layout = args.get('design', {}).get('layout', 'horizontal' if args.get('reference_ids') else 'vertical')
    diagram_design = {'height_mm': 45 if layout == 'horizontal' else 90, **args.get('design', {})}
    design, width, height, size = _style({**args, 'design': diagram_design})
    if layout not in ('horizontal', 'vertical'):
        raise ValueError('流程layout使用horizontal或vertical')
    incoming = {identifier: 0 for identifier in ids}; outgoing = defaultdict(list)
    # Feedback is explicit; ordinary graph edges determine topological layers.
    for edge in edges:
        a, b = edge['from'], edge['to']
        if edge.get('kind') != 'feedback':
            outgoing[a].append(b); incoming[b] += 1
    queue = deque(n for n in ids if incoming[n] == 0); ranks = dict.fromkeys(ids, 0)
    visited = []
    while queue:
        a = queue.popleft()
        visited.append(a)
        for b in outgoing[a]:
            ranks[b] = max(ranks[b], ranks[a] + 1); incoming[b] -= 1
            if incoming[b] == 0:
                queue.append(b)
    if len(visited) != len(nodes):
        raise ValueError('循环返回边请标注kind=feedback，其他连线需形成可排列的数据流')
    layers = defaultdict(list)
    for n in ids:
        layers[ranks[n]].append(n)
    positions = {}
    for rank, members in layers.items():
        for index, identifier in enumerate(members):
            across = index - (len(members) - 1) / 2
            positions[identifier] = (rank * 1.7, -across * 1.2) if layout == 'horizontal' else (across * 1.7, -rank * 1.2)
    xs, ys = zip(*positions.values())
    feedback_count = 0
    with plt.rc_context({'font.sans-serif': ['Microsoft YaHei', 'Noto Sans CJK SC', 'DejaVu Sans'], 'axes.unicode_minus': False,
                         'svg.fonttype': 'none', 'font.size': size}):
        fig, ax = plt.subplots(figsize=(width / 25.4, height / 25.4), dpi=216, layout='constrained')
        try:
            colors = design.get('colors') or ['#edf3ee', '#e7eef5', '#f8eee0']
            groups = list(dict.fromkeys(n.get('group', '') for n in nodes))
            node_artists, edge_labels = [], []
            for edge in edges:
                start, end = positions[edge['from']], positions[edge['to']]
                feedback = edge.get('kind') == 'feedback'
                if feedback:
                    # Route returns outside the node envelope, rather than
                    # bending through a parallel branch and its text.
                    rail = (max(ys) + .9 if layout == 'horizontal' else max(xs) + 1.1) + feedback_count * .4
                    feedback_count += 1
                    if layout == 'horizontal':
                        start, end = (start[0], start[1] + .36), (end[0], end[1] + .36)
                        points = [start, (start[0], rail), (end[0], rail), end]
                        label_point = ((start[0] + end[0]) / 2, rail + .1)
                    else:
                        start, end = (start[0] + .66, start[1]), (end[0] + .66, end[1])
                        points = [start, (rail, start[1]), (rail, end[1]), end]
                        label_point = (rail + .05, (start[1] + end[1]) / 2)
                    ax.add_patch(FancyArrowPatch(path=DrawingPath(points, [DrawingPath.MOVETO] + [DrawingPath.LINETO] * 3),
                        arrowstyle='-|>', mutation_scale=12, linewidth=1.2, linestyle='--', color='#54746d', zorder=1))
                    if edge.get('label'):
                        edge_labels.append(ax.text(*label_point, edge['label'], ha='center', fontsize=max(7, size - 1), color='#46605a'))
                    continue
                dx, dy = end[0] - start[0], end[1] - start[1]
                if dx == 0 and dy == 0:
                    raise ValueError('自循环请用明确的独立条件/返回节点表达')
                portion = min(.66 / abs(dx) if dx else float('inf'), .36 / abs(dy) if dy else float('inf'))
                start = (start[0] + dx * portion, start[1] + dy * portion)
                end = (end[0] - dx * portion, end[1] - dy * portion)
                ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>', mutation_scale=12,
                    connectionstyle='arc3,rad=0', linewidth=1.2,
                    color='#54746d', zorder=1))
                if edge.get('label'):
                    edge_labels.append(ax.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + .19,
                            edge['label'], ha='center', fontsize=max(7, size - 1), color='#46605a'))
            for node in nodes:
                x, y = positions[node['id']]
                box = FancyBboxPatch((x - .62, y - .32), 1.24, .64,
                    boxstyle='round,pad=.03,rounding_size=.06', edgecolor='#729389',
                    facecolor=colors[groups.index(node.get('group', '')) % len(colors)], zorder=2)
                ax.add_patch(box)
                xs = [p[0] for p in positions.values()]
                text = ax.text(x, y, node['label'], ha='center', va='center', zorder=3)
                node_artists.append((box, text, node['label']))
            ax.set_xlim(min(xs) - .9, max(xs) + (.9 if layout == 'horizontal' or not feedback_count else 1.5 + feedback_count * .4))
            ax.set_ylim(min(ys) - .8, max(ys) + (.8 if layout == 'vertical' or not feedback_count else 1.3 + feedback_count * .4))
            ax.axis('off')
            if design.get('show_title', True):
                ax.set_title(args['title'])
            # Measure actual font glyphs at export size: a Chinese glyph and an
            # ASCII letter do not have the same width. Never shrink fonts to fit.
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            padding = 2 * fig.dpi / 72
            for box, text, raw in node_artists:
                available = box.get_window_extent(renderer).width - 2 * padding
                lines = []
                for paragraph in raw.split('\n'):
                    current = ''
                    for character in paragraph:
                        trial = current + character
                        measured = renderer.get_text_width_height_descent(trial, text.get_fontproperties(), False)[0]
                        if current and measured > available:
                            lines.append(current); current = character
                        else:
                            current = trial
                    lines.append(current)
                text.set_text('\n'.join(lines))
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            issues = []
            for box, text, raw in node_artists:
                outer = box.get_window_extent(renderer)
                inner = text.get_window_extent(renderer)
                if not (outer.x0 + padding <= inner.x0 and inner.x1 <= outer.x1 - padding
                        and outer.y0 + padding <= inner.y0 and inner.y1 <= outer.y1 - padding):
                    issues.append('节点文字放不下：' + raw)
            all_labels = [text for _, text, _ in node_artists] + edge_labels
            for i, text in enumerate(all_labels):
                bounds = text.get_window_extent(renderer)
                if any(bounds.overlaps(other.get_window_extent(renderer)) for other in all_labels[i + 1:]):
                    issues.append('文字相互重叠：' + text.get_text().replace('\n', ''))
            for text in edge_labels:
                if any(text.get_window_extent(renderer).overlaps(box.get_window_extent(renderer)) for box, _, _ in node_artists):
                    issues.append('连线说明压住节点：' + text.get_text())
            if issues:
                raise ValueError('流程图布局未通过：' + '；'.join(issues[:4]) +
                    '。保持可读字号，增加width_mm/height_mm、调整horizontal/vertical或缩短标签后重画。')
            layout_check = {'passed': True, 'font_size': size, 'node_labels_checked': len(node_artists),
                            'edge_labels_checked': len(edge_labels),
                            'scope': '节点文字容纳、文字互相重叠、连线说明与节点；不含完整箭头避障或语义审阅'}
            fig.savefig(image, dpi=216); fig.savefig(image.with_suffix('.svg'))
        finally:
            plt.close(fig)
    return {'steps': args.get('steps', []), 'nodes': nodes, 'edges': edges,
            'render_spec': {'layout': layout, 'width_mm': width, 'height_mm': height, 'font_size': size, 'layout_check': layout_check,
                'quality': {'layout_passed': True, 'minimum_font_pt': min(size, max(7, size - 1)) if edge_labels else size,
                            'language': 'zh' if any(re.search(r'[\u4e00-\u9fff]', n['label']) for n in nodes) else 'unverified'}},
            'rendering': 'Authored source-linked diagram; not an experiment screenshot or automatic semantic verification'}
