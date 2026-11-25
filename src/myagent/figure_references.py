"""Local, attributed design references, kept separate from experiment evidence."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

from .tools.base import ToolResult

VERSION = 1
GUIDANCE = '''figure_reference_library是设计参考目录，不是本次实验结果。按当前图要回答的问题选1—3张；用figure_references search/read读取借鉴点，并在lab_figure及最终交付中保存reference_ids、reference_use与design。
模仿参考的布局、信息层级与视觉编码；图中解释性文字使用中文，必要的代码标识、单位、模型名与缩写保留原文。不要因参考是英文而把本次图改成英文。
条形图提供category_label、value_label、value_unit，程序按kind映射坐标轴；orientation=horizontal对应barh，vertical对应bar。长类别优先横向。布局错误是需要修改图的反馈，不能将报错图标成ready。复用原图前检查语言：英文说明图优先用源数据另绘中文版，保留原件；无法核验时标needs_review，不把原图登记等同中文验收通过。
数据图调用设置label_language=zh，解释性说明以中文为主；epoch、batch、loss、accuracy等通用技术术语、代码标识与单位可以自然保留英文，不机械逐词翻译。
先决定完整数据范围或实际节点/边，再选择图形、分面、配色、标签与最终尺寸。数据来自本次登记产物；不沿用参考论文的数值、模型机制或输出实例。已有完整图可直接复用，不因短JSON方便读取就用局部曲线替代完整过程。
input_mode=images时，read会实际附上参考PNG，inspect可查看本次登记图片；这表示提供图片输入，不等于视觉检查已经通过。input_mode=metadata时只可依据设计说明，不声称看过像素。
lab_figure支持bar/barh/line/scatter/heatmap、数值横轴、完整数组取值、数字格式和节点连线图。参考选择不强求复杂布局；按报告最终宽高设计。图与表服务不同信息，避免同一组数值重复画大图。'''


def library_root():
    explicit = os.getenv('MYAGENT_FIGURE_REFERENCE_LIBRARY', '').strip()
    return Path(explicit).expanduser().resolve() if explicit else Path(__file__).resolve().parents[2] / 'references/figure-reference-library'


def library():
    root = library_root()
    path = root / 'manifest.json'
    data = path.read_bytes()
    return root, json.loads(data), hashlib.sha256(data).hexdigest()


def reference_packet(*, images_enabled=False):
    try:
        _, manifest, sha = library()
    except (OSError, ValueError) as exc:
        return {'version': VERSION, 'available': False, 'reason': str(exc),
                'notice': '参考库不可用；仍可根据本次真实材料作图，不虚构参考或阻断报告。'}
    return {'version': VERSION, 'available': True, 'manifest_sha256': sha,
            'input_mode': 'images' if images_enabled else 'metadata',
            'catalog': [{k: r[k] for k in ('id', 'category', 'title', 'tags')} for r in manifest['figures']],
            'notice': '设计参考不属于实验材料。按问题选择少量参考；read读取具体借鉴点。'}


def reference_records(ids):
    if not isinstance(ids, list) or len(ids) > 3 or len(set(ids)) != len(ids):
        raise ValueError('reference_ids需要0—3个不重复的参考ID')
    if not ids:
        return []
    root, manifest, sha = library()
    by_id = {r['id']: r for r in manifest['figures']}
    records = []
    for identifier in ids:
        if identifier not in by_id:
            raise ValueError('未知参考图ID：' + str(identifier))
        r = by_id[identifier]
        image = root / r['image']
        if hashlib.sha256(image.read_bytes()).hexdigest() != r['image_sha256']:
            raise ValueError('参考图片版本已变化：' + identifier)
        records.append({**{k: r[k] for k in ('id', 'category', 'title', 'learn', 'use', 'avoid',
                         'source_url', 'figure', 'page', 'image', 'image_sha256')},
                        'library_manifest_sha256': sha})
    return records


def reference_provenance(project, args):
    ids = args.get('reference_ids', [])
    records = reference_records(ids)
    use = args.get('reference_use', '')
    if records and (not isinstance(use, str) or not use.strip()):
        raise ValueError('使用参考图时需用reference_use说明借鉴的布局/编码方式')
    reads = project.data.get('figure_reference_reads', [])
    return {'reference_ids': ids, 'reference_use': use,
            'design': args.get('design', {}),
            'references': [{k: r[k] for k in ('id', 'source_url', 'figure', 'page', 'image_sha256', 'library_manifest_sha256')} for r in records],
            'reference_input_modes': {identifier: next((r['input_mode'] for r in reversed(reads)
                if identifier in r.get('reference_ids', [])), 'not_read') for identifier in ids}}


def image_input(path, label):
    data = path.read_bytes()
    return {'label': label, 'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(),
            'url': 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')}


def validate_figure_result(project, result):
    from .lab_figures import registered_assets
    if not isinstance(result.get('figures'), list):
        raise ValueError('图表交付需要figures数组')
    assets = {project.file(a['path']): a for a in registered_assets(project)}
    for figure in result['figures']:
        if not figure.get('id'):
            raise ValueError('图表交付需要计划ID')
        if figure.get('path'):
            asset = assets.get(project.file(figure['path']))
            if asset is None:
                raise ValueError('交付图片必须为本次登记产物；参考库原图不能充当实验结果')
            from .figure_quality import asset_quality
            figure['quality'] = asset_quality(project, asset)
            if figure['quality']['status'] == 'stale':
                raise ValueError('图片改变后需重新检查，不能沿用旧质量记录')
            for key in ('reference_ids', 'reference_use', 'design'):
                # Actual generation metadata is authoritative, including []:
                # don't attach references to an asset that wasn't rendered with them.
                if key in asset:
                    figure[key] = asset[key]
        if figure.get('reference_ids'):
            reference_records(figure['reference_ids'])
            if not figure.get('reference_use', '').strip():
                raise ValueError('图表交付需说明reference_use')


class FigureReferences:
    name = 'figure_references'
    description = ('Read our attributed design-reference library, separate from experiment results. '
        'search: query/category, returns up to 3 candidates. read: ids (1-3), optional reference_use; '
        'returns design notes, and actual reference images only when image inputs are enabled. '
        'inspect: path to a registered experiment/report PNG; inspect final output in image mode. '
        'Do not adopt reference images as experimental evidence.')
    parameters = {'type': 'object', 'properties': {
        'operation': {'type': 'string', 'enum': ['search', 'read', 'inspect']},
        'query': {'type': 'string'}, 'category': {'type': 'string', 'enum': ['data', 'flow']},
        'ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 3},
        'reference_use': {'type': 'string'}, 'path': {'type': 'string'}}, 'required': ['operation']}

    def __init__(self, project):
        self.project = project

    def run(self, args, ctx):
        mode = 'images' if getattr(ctx, 'image_inputs_enabled', False) else 'metadata'
        if args['operation'] == 'inspect':
            from .lab_figures import registered_assets
            from PIL import Image
            path = self.project.file(args['path'])
            if path not in {self.project.file(a['path']) for a in registered_assets(self.project)}:
                raise ValueError('inspect仅查看本次已登记图片，参考图用read')
            with Image.open(path) as im:
                width, height = im.size
                if im.format != 'PNG':
                    raise ValueError('当前图片查看入口使用PNG')
            payload = {'path': args['path'], 'width': width, 'height': height, 'input_mode': mode,
                       'notice': '实际图片输入；需自行检查可读性。' if mode == 'images' else '只有尺寸信息，本模型未开启图片输入。'}
            return ToolResult(output=json.dumps(payload, ensure_ascii=False),
                              images=[image_input(path, '本次产物：' + args['path'])] if mode == 'images' else [])
        root, manifest, sha = library()
        if args['operation'] == 'search':
            query = args.get('query', '').lower()
            terms = set(re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]', query))
            terms.update(query[i:i + 2] for i in range(len(query) - 1) if query[i:i + 2].strip())
            rows = [r for r in manifest['figures'] if not args.get('category') or r['category'] == args['category']]
            def score(r):
                text = ' '.join(str(r[k]) for k in ('title', 'tags', 'use', 'learn')).lower()
                return sum(len(t) for t in terms if t in text)
            rows = sorted(rows, key=score, reverse=True)[:3]
            return ToolResult(output=json.dumps({'candidates': [{k: r[k] for k in ('id', 'title', 'tags', 'learn', 'use', 'avoid')} for r in rows],
                'input_mode': mode, 'notice': '先匹配表达问题；read读取所选参考，不能把参考当本次产物。'}, ensure_ascii=False))
        if args['operation'] != 'read' or not args.get('ids'):
            raise ValueError('read需要1—3个参考图ID')
        rows = reference_records(args['ids'])
        self.project.data.setdefault('figure_reference_reads', []).append({
            'reference_ids': args['ids'], 'reference_use': args.get('reference_use', ''),
            'manifest_sha256': sha, 'input_mode': mode})
        self.project.save()
        return ToolResult(output=json.dumps({'references': rows, 'input_mode': mode,
            'notice': '仅迁移视觉表达，本次事实和数值仍来自登记材料。'}, ensure_ascii=False),
            images=[image_input(root / r['image'], '设计参考 ' + r['id'] + '：' + r['title']) for r in rows] if mode == 'images' else [])
