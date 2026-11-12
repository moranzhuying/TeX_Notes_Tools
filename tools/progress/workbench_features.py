"""按需工作台功能；只读登记源码，不导入旧服务或私有旧标记。"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import re

import workbench_readonly as ro

from workbench_store import StoreError


def terms(value):
    if not isinstance(value, str) or len(value) > 512 or '\x00' in value:
        raise StoreError('搜索须为不超过512字符的字符串')
    words = list(dict.fromkeys(value.lower().split()))
    if not words or len(words) > 16 or any(len(w) > 128 for w in words):
        raise StoreError('须为1至16个非空词，每词至多128字符')
    return words


def registered(store):
    # navigation拒绝多登记入口、重复绑定和越界；不调用全量审计或旧JSON。
    return store.navigation()['units']


def tex_unit(store, uid):
    if not isinstance(uid, str):
        raise StoreError('unit须为字符串')
    matches = [u for u in registered(store) if u['id'] == uid]
    if len(matches) != 1:
        raise StoreError('单位未登记')
    unit = matches[0]
    path = store.path(unit['tex_path'])
    if path.suffix.lower() != '.tex' or not path.is_file():
        raise StoreError('仅允许登记TeX文件')
    return unit, path


def search(server, query, book='', limit='100'):
    words = terms(query)
    if not isinstance(limit, str) or len(limit) > 3 or not limit.isascii() or not limit.isdigit() or not 1 <= int(limit) <= 300:
        raise StoreError('搜索上限须为1至300')
    if not isinstance(book, str):
        raise StoreError('book须为字符串')
    from workbench_readonly import discover
    names = [book] if book else [p.name for p in discover(server.root)]
    total = 0
    results = []
    for name in names:
        store = server.store(name, request_read=True)
        for unit in registered(store):
            path = store.path(unit['tex_path'])
            if path.suffix.lower() != '.tex':
                raise StoreError('登记文件不是TeX')
            raw = path.read_bytes()
            snapshot = hashlib.sha256(raw).hexdigest()
            text = raw.decode('utf-8-sig')
            if not all(w in text.lower() for w in words):
                continue
            total += 1
            if len(results) >= int(limit):
                continue
            hits = []
            for number, line in enumerate(text.splitlines(), 1):
                offsets = [line.lower().find(w) for w in words if w in line.lower()]
                if offsets:
                    start = max(0, min(offsets) - 100)
                    hits.append({'line': number, 'text': line[start:start + 400], 'column': start + 1})
                    if len(hits) == 6:
                        break
            results.append({'book': name, 'unit': unit['id'], 'title': unit['title'],
                            'path': unit['tex_path'], 'sha256': snapshot, 'hits': hits})
    return {'terms': words, 'total': total, 'results': results, 'truncated': total > len(results),
            'scope': '已登记TeX实时读取；同文件AND可不同行；不代表审核'}


def source(store, uid, line):
    if not isinstance(line, str) or len(line) > 9 or not line.isascii() or not line.isdigit():
        raise StoreError('line须为正整数')
    unit, path = tex_unit(store, uid)
    raw = path.read_bytes()
    snapshot = hashlib.sha256(raw).hexdigest()
    lines = raw.decode('utf-8-sig').splitlines()
    number = int(line)
    if not 1 <= number <= len(lines):
        raise StoreError('源码行号越界')
    lo, hi = max(0, number - 15), min(len(lines), number + 14)
    return {'book': store.book.name, 'unit': uid, 'path': unit['tex_path'], 'total_lines': len(lines),
            'line': number, 'readonly': True, 'sha256': snapshot,
            'lines': [{'n': i + 1, 'text': lines[i]} for i in range(lo, hi)]}


def stage_counts(rows, stage):
    states = Counter(r['states'].get(stage, '未登记') for r in rows)
    applicable = [r for r in rows if r['states'].get(stage) != '不适用']
    done = '本轮通过' if stage == 'math' else '本轮完成'
    return {'total': len(rows), 'applicable': len(applicable), 'states': dict(states),
            'declared_done': states[done],
            'verified_done': sum(r['states'].get(stage) == done and r['basis'].get(stage) == 'current' for r in applicable),
            'missing_basis': sum(r['basis'].get(stage) == 'missing' for r in applicable),
            'stale': sum(r['basis'].get(stage) == 'stale' for r in applicable)}


def aggregate_book(store):
    nav = store.navigation()
    initialized = nav['initialized']
    units = store._catalog()
    reviews = store._review_index()
    store._request_reviews = reviews
    hashes = {}
    def basis(selected):
        paths = {u[k] for u in selected for k in ('tex', 'entry', 'record')}
        if store.path('Source.md').is_file():
            paths.add('Source.md')
        for path in paths:
            if path not in hashes:
                hashes[path] = hashlib.sha256(store.path(path).read_bytes()).hexdigest()
        return {p: hashes[p] for p in sorted(paths)}
    issues, rows, conflicts = [], [], list(nav['conflicts'])
    def issue(uid, origin, text, path, line=None, stage=None):
        rid = re.search(r'\bR\d+\b', text)
        issues.append({'book': store.book.name, 'unit': uid, 'origin': origin, 'text': text,
                       'id': rid[0] if rid else None, 'key': store.book.name + ':' + (rid[0] if rid else uid + ':' + origin + ':' + str(line)),
                       'path': path, 'line': line, 'stage': stage})
    for uid, unit in units.items():
        states = dict.fromkeys(list(ro.STAGES)[:4], '未登记')
        evidence = dict.fromkeys(states, 'missing')
        try:
            p, text, number, _, _, row = store._review(unit)
            states = {k: row.get(ro.STAGES[k], '未登记') for k in states}
            markers = store._markers(text) if initialized else {}
            current = basis([unit]) if markers else None
            for stage in states:
                saved = markers.get((uid, stage))
                if saved and saved[1].get('basis') is not None:
                    evidence[stage] = 'current' if saved[1]['basis'] == current else 'stale'
            doubt = row.get('疑点', '').strip()
            if doubt not in {'', '无', '无疑点', '未检查', '未登记', '已解决'}:
                issue(uid, 'review疑点', doubt, p.relative_to(store.book).as_posix(), number + 1)
            for stage, value in states.items():
                if value in {'待补', '待修订', '有疑点'}:
                    issue(uid, '阶段状态', ro.STAGES[stage] + '：' + value, p.relative_to(store.book).as_posix(), number + 1, stage)
        except StoreError as exc:
            conflicts.append({'unit': uid, 'error': str(exc)})
        rows.append({'unit': uid, 'states': states, 'basis': evidence})
        path = store.path(unit['tex'])
        for number, line in enumerate(path.read_bytes().decode('utf-8-sig').splitlines(), 1):
            comment = re.search(r'(?<!\\)%', line)
            todo = re.search(r'\bTODO\b\s*[:：]?\s*(.*)', line[comment.start():], re.I) if comment else None
            if todo:
                issue(uid, '源码TODO', todo[1] or '未编号TODO', unit['tex'], number)
    summary_rows = []
    summary_path = store.path('Materials/workbench/summaries.md')
    if summary_path.is_file():
        text = summary_path.read_bytes().decode('utf-8')
        markers = store._markers(text) if initialized else {}
        seen = set()
        allowed = store._scopes(units)
        for line in text.splitlines():
            cells = [v.strip() for v in line.split('|')[1:-1]]
            if len(cells) != 3 or cells[0] not in allowed:
                continue
            scope, state, _ = cells
            if scope in seen:
                raise StoreError('总结scope重复')
            seen.add(scope)
            saved = markers.get((scope, 'summary'))
            ev = 'missing'
            if saved and saved[1].get('basis') is not None:
                current = basis([u for uid, u in units.items() if uid == scope or uid.startswith(scope + '/')])
                ev = 'current' if saved[1]['basis'] == current else 'stale'
            summary_rows.append({'unit': scope, 'states': {'summary': state}, 'basis': {'summary': ev}})
            if state in {'待补', '待修订'}:
                issue(scope, '总结状态', '总结导引：' + state, 'Materials/workbench/summaries.md', stage='summary')
    runtime = store.read_runtime()['data'] if initialized else {}
    groups = {}
    for item in issues:
        if item['origin'] == '源码TODO' and item['id']:
            groups.setdefault(item['id'], []).append(item)
    for rid, refs in groups.items():
        if len({v['text'] for v in refs}) > 1:
            conflicts.append({'code': 'todo_number_conflict', 'book': store.book.name, 'id': rid})
    return {'book': store.book.name, 'units': len(units), 'initialized': initialized,
            'stages': {k: stage_counts(rows, k) for k in list(ro.STAGES)[:4]},
            'summary': {level: stage_counts([r for r in summary_rows if ('/' in r['unit']) == (level == 'section')], 'summary') for level in ('chapter', 'section')},
            'summary_scopes': [r['unit'] for r in summary_rows], 'issues': issues, 'conflicts': conflicts,
            'runtime': {'plan': runtime.get('plan', []), 'current': {k: runtime.get('current_' + k) for k in ('body', 'proof', 'summary')}},
            'plan_scope': '主动计划独立展示，不作为欠账；阶段分母为全书登记目/直接节正文及附录单位',
            'summary_scope': '仅已有summaries登记scope；章和§分表不合成分母，避免嵌套重复覆盖；不读取review逐目总结'}


def aggregate(server, book):
    if not isinstance(book, str):
        raise StoreError('book须为字符串，空字符串代表全书架')
    names = [book] if book else [p.name for p in ro.discover(server.root)]
    return {'books': [aggregate_book(server.store(n, request_read=True)) for n in names],
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'privacy': '旧legacy备注和原始全文不读取、不导出；审核结论不混入未决问题；未检查不是欠账或通过',
            'readonly': True}


def markdown(data):
    def escape(value):
        return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    lines = ['# 写作工作台进度报告', '', data['privacy'], '', '范围：全书登记单位；没有单一总完成率。', '']
    for book in data['books']:
        lines += ['## ' + book['book'], '', book['plan_scope'], '', book['summary_scope'], '',
                  '| 阶段 | 适用分母 | 声明完成 | 版本核验完成 | 缺basis | stale | 状态计数 |',
                  '| --- | --- | --- | --- | --- | --- | --- |']
        counts = [(ro.STAGES[k], v) for k, v in book['stages'].items()]
        counts += [('总结章scope', book['summary']['chapter']), ('总结§scope', book['summary']['section'])]
        for label, count in counts:
            lines.append('| ' + ' | '.join(map(escape, [label, count['applicable'], count['declared_done'], count['verified_done'], count['missing_basis'], count['stale'], count['states']])) + ' |')
        lines += ['', '### 未决清单（聚合只读，源码TODO不会因审核解决而自动消失）', '']
        for item in book['issues']:
            lines.append('- ' + escape(item['origin'] + ' · ' + item['unit'] + ' · ' + (item['id'] or '未编号') + ' · ' + item['text'] + ' · ' + item['path'] + ':' + str(item['line'] or '')))
        if not book['issues']:
            lines.append('- 无已登记未决条目；不表示未检查单位已通过。')
        lines += ['', '主动计划（非欠账）：' + escape(book['runtime']['plan']), '当前位置：' + escape(book['runtime']['current']),
                  '绑定/编号冲突：' + escape(book['conflicts']), '']
    return '\n'.join(lines) + '\n'
