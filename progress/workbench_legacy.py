"""旧标记仅归档，不生成审核结论；公开manifest不含原备注。"""
import argparse
import json
from pathlib import Path

import workbench_readonly as ro
from workbench_store import BookStore, Conflict, encode, digest


def plan(root, raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('旧标记必须为对象')
    stores = [BookStore(root, p.name) for p in ro.discover(root)]
    paths = {}
    basenames = {}
    for store in stores:
        for p in store.book.rglob('*.tex'):
            if '.git' in p.relative_to(store.book).parts:
                continue
            relative = p.relative_to(store.book).as_posix()
            paths.setdefault(relative, []).append(store.book.name)
            basenames.setdefault(p.name, []).append((store.book.name, relative))
    rows = []
    for group in ('entries', 'nodes', 'chapters'):
        values = data.get(group, {})
        if not isinstance(values, dict):
            raise ValueError('旧标记分组必须为对象')
        for key, value in sorted(values.items()):
            if not isinstance(key, str):
                raise ValueError('旧标记路径必须为字符串')
            candidates = paths.get(key, [])
            samebase = basenames.get(Path(key).name, [])
            confirmed = len(candidates) == 1 and len(samebase) == 1
            rows.append({'group': group, 'key': key,
                         'record_sha256': digest(encode(value)),
                         'book': candidates[0] if confirmed else None,
                         'status': 'confirmable_exact_unique' if confirmed else 'pending_claim',
                         'candidate_books': sorted(set(candidates)),
                         'basename_candidates': [{'book': b, 'path': p} for b, p in sorted(samebase)]})
    return {'schema_version': 1, 'source_sha256': digest(raw),
            'semantics': 'legacy_only_no_review_promotion', 'records': rows}


def publish(path, payload):
    """硬链接发布避免覆盖，断点重跑只接受同bytes。"""
    import os
    import uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise Conflict('归档已存在且内容不同')
        return
    temp = path.with_name('.' + path.name + '.' + str(uuid.uuid4()) + '.tmp')
    BookStore._exclusive(temp, payload)
    try:
        os.link(temp, path)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise Conflict('并发归档内容冲突')
    finally:
        temp.unlink(missing_ok=True)


def migrate(root, source, private):
    root, source, private = Path(root).resolve(strict=True), Path(source), Path(private)
    raw = source.read_bytes()
    manifest = plan(root, raw)
    ident = manifest['source_sha256']
    # 完整原JSON在非公开本机目录备份；歧义记录不分配给任何书。
    publish(private / ident / 'original.json', raw)
    publish(private / ident / 'manifest.json', encode(manifest))
    original = json.loads(raw)
    for name in sorted({r['book'] for r in manifest['records'] if r['book']}):
        store = BookStore(root, name)
        with store.lock():
            store.identity()
            rows = [r for r in manifest['records'] if r['book'] == name]
            subset = {group: {r['key']: original[group][r['key']] for r in rows if r['group'] == group}
                      for group in ('entries', 'nodes', 'chapters')}
            base = store.path('Materials/workbench/legacy/' + ident)
            publish(base / 'original.json', raw)
            publish(base / 'records.json', encode(subset))
            publish(base / 'provenance.json', encode({'schema_version': 1, 'book_id': store.identity()['book_id'],
                    'source_name': source.name, 'source_sha256': ident, 'records': rows,
                    'semantics': manifest['semantics']}))
    if source.read_bytes() != raw:
        raise Conflict('源旧标记发生外部变化；归档保留，请重新规划')
    return manifest


def main():
    parser = argparse.ArgumentParser(description='旧标记仅legacy归档，不提升审核状态')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = migrate(args.root, args.source, args.private) if args.apply else plan(args.root, args.source.read_bytes())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
