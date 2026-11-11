"""写作工作台隔离只读适配层，不调用旧 progress 扫描或保存。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime

STAGES = dict(body="正文整理", source="来源对照", math="数学审核", proof="证明回填", summary="总结导引")
KNOWN = {
    "body": {"未检查", "进行中", "待修订", "本轮完成"},
    "source": {"未检查", "进行中", "待修订", "本轮完成"},
    "math": {"未检查", "进行中", "有疑点", "本轮通过"},
    "proof": {"未检查", "进行中", "待补", "本轮完成", "不适用"},
    "summary": {"未检查", "进行中", "待补", "本轮完成", "不适用"},
}
LOCAL = r"(?:C\d+(?:[-/](?:S|A)\d+)?|A\d+)(?:[-/]N\d+(?:__[A-Za-z0-9_]+)?)?"
DISPLAY = rf"(?:[A-Z]+-)?{LOCAL}"


def read(path):
    return path.read_text(encoding="utf-8-sig")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_id(value):
    match = re.search(LOCAL, value)
    return match.group().replace("-", "/") if match else None


def safe(book, relative):
    relative = relative.strip().strip("`").replace("\\", "/")
    path = (book / relative).resolve()
    if Path(relative).is_absolute() or re.match(r"^[A-Za-z]:", relative) or not path.is_relative_to(book.resolve()):
        raise ValueError("路径越界：" + relative)
    return path


def tables(text):
    headers = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip().startswith("|"):
            headers = None
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if "目编号" in cells and "TeX" in cells:
            headers = cells
        elif headers and not all(re.fullmatch(r"[: -]+", c) for c in cells):
            yield number, dict(zip(headers, cells))


def bindings(path):
    text = read(path)
    rows = []
    for number, row in tables(text):
        if "资料目录" in row:
            rows.append((row["目编号"], row["TeX"], row["资料目录"], number))
    for number, line in enumerate(text.splitlines(), 1):
        if not line.startswith("-") or "TeX" not in line or "Materials/" not in line:
            continue
        material = re.search(r"Materials/((?:C|A)\d+(?:/[SAN]\d+)*(?:__[A-Za-z0-9_]+)?)", line)
        tex = re.search(r"(?:TeX\s*`|TeX[：:]\s*`?)([^`；（\s]+\.tex)", line)
        if material and tex:
            lid = material[1]
            display = re.search(DISPLAY, line[:line.index("TeX")])
            rows.append((display[0] if display and local_id(display[0]) == lid else lid, tex[1], "Materials/" + lid, number))
    # 表格与直接正文追加登记可重复叙述同一绑定，不重复计数。
    unique = []
    seen = set()
    for row in rows:
        key = (local_id(row[0]), row[1], row[2])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def discover(root):
    """只发现登记入口，不读取正文；每次调用重新检查书架边界。"""
    root = Path(root).resolve()
    shelf = root / "LaTeX_Notes" if (root / "LaTeX_Notes").is_dir() else root
    books = []
    for p in sorted(shelf.iterdir()):
        if not p.is_dir() or not list(p.glob("*_Content.md")):
            continue
        if not p.resolve().is_relative_to(shelf.resolve()):
            raise ValueError("书架入口越界：" + p.name)
        books.append(p)
    return books


def navigation_titles(book, units, resolve):
    """只读标题层：按实际 input 路径继承上下文，不以资料章号猜 TeX 章。"""
    import workbench_tex as titles
    cache = {}
    def text(relative):
        path = resolve(relative)
        if relative not in cache:
            if not path.is_file():
                cache[relative] = ""
            else:
                with path.open('r', encoding='utf-8-sig') as stream:
                    cache[relative] = stream.read(65536)
        return cache[relative]
    token = re.compile(r'\\(part|chapter|appendixchapter|section|appendixsubsection|subsection|subsubsection|title|input|include)\*?\s*(?:\[[^\]]*\])?\s*\{')
    def commands(raw):
        raw = '\n'.join(re.split(r'(?<!\\)%', line)[0] for line in raw.splitlines())
        for match in token.finditer(raw):
            value, _ = titles.take_group(raw, match.end() - 1)
            yield match[1], value
    contexts = {}
    seen = set()
    def walk(relative, inherited):
        if relative in seen:
            return
        seen.add(relative)
        context = dict(inherited)
        own = {}
        for command, value in commands(text(relative)):
            if command in {'input', 'include'}:
                target = value.removeprefix('./')
                if not target.endswith('.tex'):
                    target += '.tex'
                child = walk(target, context)
                if child:
                    for key in ('part', 'chapter', 'appendixchapter', 'section', 'appendixsubsection'):
                        context.pop(key, None)
                        if key in child:
                            context[key] = child[key]
            else:
                label = titles.clean_label(value)
                own[command] = label
                context[command] = label
                if command in {'chapter', 'appendixchapter'}:
                    context.pop('appendixchapter' if command == 'chapter' else 'chapter', None)
                    context.pop('section', None)
                    context.pop('appendixsubsection', None)
                if command in {'section', 'appendixsubsection'}:
                    context.pop('appendixsubsection' if command == 'section' else 'section', None)
                    context.pop('subsection', None)
        contexts[relative] = (own, context)
        return context
    # 纯 TeX 解析的主文件 input 标题映射，不读取旧面板配置或状态。
    resolve('main.tex')
    entries = titles.scan_main(book, {})
    main = titles.main_headings(book, entries)
    walk('main.tex', {})
    scopes = {}
    # 多个登记资料章挂在同一本地 input 下时，以该子树 section 作为资料父标题。
    split_parts = any(len({u['id'].split('/')[0] for u in units if u['tex_path'].startswith(Path(target).parent.as_posix() + '/')}) > 1 for target in main)
    for unit in units:
        relative = unit['tex_path']
        if relative not in contexts:
            walk(relative, {})
        own, context = contexts.get(relative, ({}, {}))
        for target, headings in main.items():
            if relative == target or relative.startswith(str(Path(target).parent).replace('\\', '/') + '/'):
                context = headings | context
                break
        unit['title'] = next((own[k] for k in ('subsection', 'appendixsubsection', 'subsubsection', 'section', 'appendixchapter', 'chapter') if own.get(k)), unit.get('title') or '标题未登记')
        uid = unit['id']
        chapter_keys = ('appendixchapter', 'section', 'chapter', 'part') if split_parts else ('appendixchapter', 'chapter', 'part')
        for depth, keys in ((1, chapter_keys), (2, ('appendixsubsection', 'section', 'chapter'))):
            scope = '/'.join(uid.split('/')[:depth])
            label = next((context[k] for k in keys if context.get(k)), '')
            if scope not in scopes or not scopes[scope]['title']:
                prefix = '附录 ' if '/A' in scope or scope.startswith('A') else ('Chap ' if depth == 1 else '§')
                number = str(int(scope.split('/')[-1][1:]))
                if split_parts and depth == 1:
                    prefix, number = '', ''
                scopes[scope] = {'id': scope, 'title': label, 'label': (prefix + number + ' · ' if prefix or number else '') + (label or '标题未登记'), 'display_id': scope}
        unit['chapter_title'] = ((context.get('chapter', '') + ' / ') if split_parts else '') + scopes[uid.split('/')[0]]['label']
        unit['section_title'] = scopes['/'.join(uid.split('/')[:2])]['label']
    for scope, value in scopes.items():
        sample = next((u for u in units if u['id'] == scope or u['id'].startswith(scope + '/')), None)
        prefix = sample['display_id'].split('-')[0] if sample and re.match(r'^[A-Z]+-', sample['display_id']) else ''
        value['display_id'] = (prefix + '-' if prefix else '') + scope.replace('/', '-')
    book_title = next((titles.clean_label(v) for k, v in commands(text('main.tex')) if k == 'title'), '')
    if not book_title:
        readme = resolve('README.md')
        if readme.is_file():
            book_title = next((line.lstrip('# ').strip() for line in read(readme).splitlines() if line.startswith('# ')), '')
    return book_title or book.name, scopes


def content(path, raw=None):
    if not path.exists():
        return {"state": "missing", "sha256": None, "review_basis": "missing"}
    if not path.is_file():
        return {"state": "invalid_type", "sha256": None, "review_basis": "missing"}
    raw = path.read_bytes() if raw is None else raw
    text = raw.decode("utf-8-sig")
    lines = [re.split(r"(?<!\\)%", line)[0] for line in text.splitlines()]
    lines = ["" if re.fullmatch(r"\s*\\(?:appendixchapter|appendixsubsection|chapter|section|subsection|subsubsection|paragraph)\*?(?:\[[^\]]*\])?\{.*\}\s*", line) else line for line in lines]
    meaningful = re.sub(r"\\(?:appendixchapter|appendixsubsection|chapter|section|subsection|subsubsection|paragraph|label|input|include|addcontentsline|setcounter|markboth)\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})+", "", "\n".join(lines))
    return {"state": "content" if meaningful.strip() else "skeleton", "sha256": hashlib.sha256(raw).hexdigest(), "review_basis": "missing"}


def scan(root):
    root = Path(root).resolve()
    shelf = root / "LaTeX_Notes" if (root / "LaTeX_Notes").is_dir() else root
    result = {"schema_version": 1, "snapshot_at": datetime.now().astimezone().isoformat(timespec="seconds"), "readonly": True, "identity_policy": "项目目录展示命名空间，未建立永久不可变book_id", "books": [], "conflicts": [], "legacy": {}, "summary": {}}
    for book in sorted(p for p in shelf.iterdir() if p.is_dir() and list(p.glob("*_Content.md"))):
        if not book.resolve().is_relative_to(shelf.resolve()):
            result["conflicts"].append({"code": "path_escape", "book_id": book.name, "unit_id": None, "path": str(book)})
            continue
        entries = sorted(p for p in book.glob("*_Content.md") if p.resolve().is_relative_to(book.resolve()))
        selected = [p for p in entries if bindings(p)]
        conflicts = []
        def conflict(code, unit=None, **extra):
            item = {"code": code, "book_id": book.name, "unit_id": unit, **extra}
            conflicts.append(item)
        if len(selected) != 1:
            conflict("binding_entry_count", count=len(selected))
        source_path = book / "Source.md"
        source = read(source_path) if source_path.exists() and source_path.resolve().is_relative_to(book.resolve()) else ""
        data = {"book_id": book.name, "name": book.name, "title": book.name, "units": [], "conflicts": conflicts, "content_entries": [p.name for p in entries], "source_info": {"path": "Source.md", "text": source}}
        review_rows = []
        records = []
        for p in sorted((book / "Materials").rglob("review.md")):
            if not p.resolve().is_relative_to(book.resolve()):
                conflict("path_escape", path=str(p))
                continue
            review_rows.extend((p, n, r) for n, r in tables(read(p)))
        for p in sorted((book / "Materials").rglob("record.md")):
            if p.resolve().is_relative_to(book.resolve()):
                records.append(p)
        review_index = {}
        for p, n, row in review_rows:
            review_index.setdefault(local_id(row.get("目编号", "")), []).append((p, n, row))
        seen_ids = set()
        seen_paths = {}
        for entry in selected:
            prefix = entry.stem.removesuffix("_Content")
            for display, tex, material, line in bindings(entry):
                uid = local_id(display)
                if uid in seen_ids:
                    conflict("duplicate_id", uid, path=tex)
                seen_ids.add(uid)
                if tex in seen_paths and seen_paths[tex] != uid:
                    conflict("duplicate_tex_binding", uid, other=seen_paths[tex])
                seen_paths[tex] = uid
                unit = {"id": uid, "display_id": display if display.startswith(prefix + "-") else prefix + "-" + uid.replace("/", "-"), "kind": "appendix" if "/A" in uid or uid.startswith("A") else ("item" if "/N" in uid else "section"), "tex_path": tex, "materials_path": material, "chapter": uid.split("/")[0], "section": "/".join(uid.split("/")[:2]), "statuses": dict.fromkeys(STAGES, "未登记"), "issues": [], "todos": [], "source_info": {}, "content_state": {}, "binding_provenance": {"path": entry.name, "line": line}, "title": Path(tex).stem}
                data["units"].append(unit)
                try:
                    tp, mp = safe(book, tex), safe(book, material)
                    for name in ("body.md", "proof.md", "record.md"):
                        safe(book, material + "/" + name)
                except ValueError as exc:
                    conflict("path_escape", uid, detail=str(exc))
                    unit["content_state"] = {"state": "unsafe", "sha256": None, "review_basis": "missing"}
                    continue
                tex_bytes = tp.read_bytes() if tp.is_file() else None
                unit["content_state"] = content(tp, tex_bytes)
                if not tp.exists():
                    conflict("missing_tex", uid, path=tex)
                elif not tp.is_file():
                    conflict("invalid_tex_type", uid, path=tex)
                for name in ("body.md", "proof.md", "record.md"):
                    if not (mp / name).is_file():
                        conflict("missing_material", uid, path=material + "/" + name)
                rp = mp / "record.md"
                if rp.is_file():
                    rt = read(rp)
                    rec_id = local_id(rt.splitlines()[0]) if rt.splitlines() else None
                    rec_tex = re.search(r"TeX[：:]\s*`?([^`\n]+)", rt)
                    if rec_id != uid:
                        conflict("record_id_mismatch", uid, actual=rec_id)
                    if not rec_tex or rec_tex[1].strip() != tex:
                        conflict("record_tex_mismatch", uid, actual=rec_tex[1].strip() if rec_tex else None)
                    unit["source_info"] = {"record_path": rp.relative_to(book).as_posix(), "fields": {m[1]: m[2] for m in re.finditer(r"^- ([^：]+)：(.*)$", rt, re.M) if m[1] != "TeX"}}
                matches = review_index.get(uid, [])
                if len(matches) != 1:
                    conflict("review_row_count", uid, count=len(matches))
                if len(matches) > 1:
                    unit["review_conflicting_rows"] = [r for _, _, r in matches]
                for p, n, row in matches if len(matches) == 1 else []:
                    if row.get("TeX") != tex:
                        conflict("review_tex_mismatch", uid, actual=row.get("TeX"))
                        unit["review_conflicting_rows"] = [row]
                        continue
                    display_raw = row.get("目编号", "")
                    if re.match(r"^[A-Z]+-", display_raw) and not display_raw.startswith(prefix + "-"):
                        conflict("review_prefix_mismatch", uid, actual=display_raw)
                        unit["review_conflicting_rows"] = [row]
                        continue
                    unit["title"] = row.get("标题", unit["title"])
                    for key, heading in STAGES.items():
                        value = row.get(heading, "未登记")
                        unit["statuses"][key] = value
                        if value not in KNOWN[key]:
                            conflict("unknown_status", uid, stage=key, raw=value)
                    unit["review_path"] = p.relative_to(book).as_posix()
                    unit["conclusion"] = row.get("结论", "未登记")
                    if row.get("疑点") not in (None, "", "未检查", "无"):
                        unit["issues"].append({"id": None, "category": "审核", "text": row["疑点"], "status": "未判定", "line": n})
                if tp.is_file():
                    for number, text in enumerate(tex_bytes.decode("utf-8-sig").splitlines(), 1):
                        comment = re.search(r"(?<!\\)%", text)
                        if not comment:
                            continue
                        todo = re.search(r"\bTODO\b\s*(?:[：:]\s*)?(.*)", text[comment.start():], re.I)
                        if todo:
                            rid = re.search(r"\bR\d+\b", todo[1])
                            unit["todos"].append({"id": rid[0] if rid else None, "text": todo[1], "path": tex, "line": number, "status": "待关联"})
        for p, n, row in review_rows:
            rid = local_id(row.get("目编号", ""))
            if rid and rid not in seen_ids:
                conflict("review_unregistered", rid, path=p.relative_to(book).as_posix(), line=n)
        for p in records:
            rid = p.parent.relative_to(book / "Materials").as_posix()
            if rid not in seen_ids:
                conflict("record_unregistered", rid, path=p.relative_to(book).as_posix())
        todo_groups = {}
        for unit in data["units"]:
            for todo in unit["todos"]:
                if todo["id"]:
                    todo_groups.setdefault(todo["id"], []).append(todo)
        for rid, todos in todo_groups.items():
            if len({t["text"] for t in todos}) > 1:
                conflict("todo_number_conflict", issue_id=rid, references=todos)
        result["books"].append(data)
        result["conflicts"].extend(conflicts)
    result["legacy"] = {"active": False, "raw": {}, "candidates": [], "migration_performed": False, "done_policy": "旧标记不参与新版工作台数据；显式归档工具另行使用"}
    units = [u for b in result["books"] for u in b["units"]]
    result["summary"] = {"books": len(result["books"]), "units": len(units), "conflicts": len(result["conflicts"]), "content_states": dict(Counter(u["content_state"]["state"] for u in units)), "stages": {k: dict(Counter(u["statuses"][k] for u in units)) for k in STAGES}, "todos": sum(len(u["todos"]) for u in units), "audit_scope": "全量现行登记绑定核查，非原书目录逐目核定"}
    return result


def main():
    parser = argparse.ArgumentParser(description="隔离只读工作台JSON导出")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        root, output = args.root.resolve(), args.output.resolve()
        if not root.is_dir():
            raise ValueError("root不是现有目录")
        if output.exists():
            raise ValueError("输出已存在，禁止覆盖任何现有文件")
        if output.suffix.lower() != ".json" or not output.parent.is_dir():
            raise ValueError("输出须为现有目录下的新JSON文件")
        shelf = root / "LaTeX_Notes" if (root / "LaTeX_Notes").is_dir() else root
        if output.is_relative_to(shelf) or any(output.is_relative_to(root / part) for part in ("Tools", "Template")):
            raise ValueError("输出不得写入真实输入目录")
        data = scan(root)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps(data["summary"], ensure_ascii=False))
    except (OSError, ValueError) as exc:
        parser.exit(2, "导出失败：" + str(exc) + "\n")


if __name__ == "__main__":
    main()
