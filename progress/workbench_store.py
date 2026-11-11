"""书内受控保存；不初始化真实书架，不提供任意文件编辑接口。"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

try:
    from . import workbench_readonly as ro
except ImportError:
    import workbench_readonly as ro


class StoreError(ValueError):
    """输入、绑定或持久化契约不成立。"""


class Conflict(StoreError):
    """版本过时或书锁已被占用。"""


STATES = ro.KNOWN
COLUMNS = {k: v for k, v in ro.STAGES.items() if k != "summary"}
COLUMNS.update(issues="疑点", conclusion="结论")
HASH = re.compile(r"[0-9a-f]{64}\Z")
SCOPE = re.compile(r"(?:C\d+(?:/(?:S|A)\d+)?|A\d+)\Z")
MARKER = re.compile(r"^<!-- workbench-basis (.+) -->$", re.M)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def cell(value):
    if not isinstance(value, str) or any(c in value for c in "\r\n|\x00"):
        raise StoreError("单元格必须是无换行、竖线或NUL的字符串")
    if "<!--" in value or "-->" in value:
        raise StoreError("禁止注释注入")
    return value


class BookStore:
    """所有写接口都要求完整文件SHA256；打开不会建立任何目录。"""

    def __init__(self, root, book_dir, *, request_read=False):
        self.root = Path(root).resolve(strict=True)
        raw = Path(book_dir)
        if ".." in raw.parts:
            raise StoreError("书目录不得含父目录跳转")
        self.book = (raw if raw.is_absolute() else self.root / raw).resolve(strict=True)
        if not self.book.is_dir() or self.book == self.root or not self.book.is_relative_to(self.root):
            raise StoreError("书目录必须位于root内")
        self.meta = self.path("Materials/workbench")
        self._request_read = request_read
        self._request_catalog = None
        self._request_reviews = None

    def path(self, relative):
        raw = Path(relative)
        if raw.is_absolute() or ".." in raw.parts or "\\" in str(relative) or re.match(r"^[A-Za-z]:", str(relative)):
            raise StoreError("拒绝绝对路径或父目录跳转")
        target = (self.book / raw).resolve()
        if not target.is_relative_to(self.book) or target == self.book:
            raise StoreError("路径或符号链接越过书界")
        return target

    @contextmanager
    def lock(self):
        # 持久文件不可删除/替换；旧mkdir锁目录留证，不用于新锁协议。
        path = self.path(".workbench-store.advisory.lock")
        acquired = False
        # 写操作永远不使用请求读快照，锁内重新核查真实绑定。
        self._request_read = False
        self._request_catalog = None
        self._request_reviews = None
        with path.open("a+b", buffering=0) as handle:
            try:
                handle.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise Conflict("书籍OS锁已被占用或无法获取") from exc
                acquired = True
                yield
            finally:
                if acquired:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                # with关闭句柄；即使显式解锁失败也释放OS持有的锁。

    def identity(self):
        data = json.loads(self.path("Materials/workbench/book.json").read_bytes())
        if data.get("schema_version") != 1 or str(uuid.UUID(data["book_id"])) != data["book_id"]:
            raise StoreError("身份文件格式无效")
        return data

    def init(self):
        with self.lock():
            self.path("Materials").mkdir(exist_ok=True)
            self.meta.mkdir(exist_ok=True)
            identity = self.path("Materials/workbench/book.json")
            if not identity.exists():
                self._write(identity, encode({"schema_version": 1, "book_id": str(uuid.uuid4())}), None)
            result = self.identity()
            runtime = self.path("Materials/workbench/runtime.json")
            if not runtime.exists():
                self._write(runtime, encode({"schema_version": 1, "book_id": result["book_id"], "revision": 0,
                                             "current_body": None, "current_proof": None, "current_summary": None,
                                             "plan": [], "version_basis": {}}), None)
            return result

    def _check(self, target, expected):
        if expected is not None and (not isinstance(expected, str) or not HASH.fullmatch(expected)):
            raise StoreError("expected必须为完整SHA256")
        old = target.read_bytes() if target.exists() else None
        if (digest(old) if old is not None else None) != expected:
            raise Conflict("version mismatch")
        return old

    def _backup(self, target, old):
        base = self.path("Materials/workbench/backups")
        base.mkdir(exist_ok=True)
        ident = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + str(uuid.uuid4())
        folder = self.path("Materials/workbench/backups/" + ident)
        folder.mkdir()
        manifest = {"schema_version": 1, "book_id": self.identity()["book_id"] if self.path("Materials/workbench/book.json").exists() else None,
                    "target": target.relative_to(self.book).as_posix(), "existed": old is not None,
                    "sha256": digest(old) if old is not None else None, "backup_id": ident}
        if old is not None:
            self._exclusive(folder / "payload", old)
        self._exclusive(folder / "manifest.json", encode(manifest))
        return ident

    @staticmethod
    def _exclusive(path, data):
        with path.open("xb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())

    def _write(self, target, data, expected):
        # 所有调用都在同一书锁内；外部编辑器不遵守锁，替换前再检查完整哈希。
        relative = target.relative_to(self.book).as_posix()
        target = self.path(relative)
        old = self._check(target, expected)
        backup = self._backup(target, old)
        temp = target.with_name("." + target.name + "." + str(uuid.uuid4()) + ".tmp")
        self._exclusive(temp, data)
        if self.path(relative) != target:
            raise Conflict("目标路径已变化")
        self._check(target, expected)
        os.replace(temp, target)
        if target.read_bytes() != data:
            raise StoreError("替换后核对失败；磁盘可能已保存，请重新读取，勿显示成功")
        # 失败tmp留证，不删除；成功时由原子替换消费tmp。
        return {"sha256": digest(data), "backup_id": backup}

    def navigation(self):
        """实时登记导航；只检查入口及路径边界，不代表正文/record审核。"""
        selected = []
        entries = []
        for raw in sorted(self.book.glob("*_Content.md")):
            entry = self.path(raw.relative_to(self.book).as_posix())
            entries.append(raw.name)
            rows = ro.bindings(entry)
            if rows:
                selected.append((entry, rows))
        if len(selected) != 1:
            raise StoreError("登记入口不唯一")
        entry, rows = selected[0]
        units = {}
        texes = set()
        for display, tex, material, line in rows:
            uid = ro.local_id(display)
            if not uid or uid in units or tex in texes or material != "Materials/" + uid:
                raise StoreError("导航登记编号或绑定冲突")
            tp, mp = self.path(tex), self.path(material)
            if not tp.is_file() or not mp.is_dir():
                raise StoreError("导航登记目录或TeX绑定无效")
            texes.add(tex)
            units[uid] = {"id": uid, "display_id": display, "title": Path(tex).stem,
                          "tex_path": tex, "materials_path": material,
                          "binding_provenance": {"path": entry.name, "line": line}}
        # 多表/多行保留为未决冲突，不以最后一行覆盖前一行。
        titles = {}
        for raw in sorted(self.path("Materials").rglob("review.md")):
            p = self.path(raw.relative_to(self.book).as_posix())
            for line, row in ro.tables(ro.read(p)):
                titles.setdefault(ro.local_id(row.get("目编号", "")), []).append((p, line, row))
        conflicts = []
        for uid, unit in units.items():
            matches = titles.get(uid, [])
            if len(matches) != 1:
                conflicts.append({"code": "review_row_count", "unit_id": uid, "count": len(matches)})
                continue
            p, line, row = matches[0]
            prefix = entry.stem.removesuffix("_Content")
            if not self.path(unit["materials_path"]).is_relative_to(p.parent) or row.get("TeX") != unit["tex_path"] or (re.match(r"^[A-Z]+-", row.get("目编号", "")) and not row["目编号"].startswith(prefix + "-")):
                conflicts.append({"code": "review_binding_mismatch", "unit_id": uid})
                continue
            unit["title"] = row.get("标题", unit["title"])
            unit["display_id"] = row.get("目编号", unit["display_id"])
            unit["review_path"] = p.relative_to(self.book).as_posix()
        title, scope_titles = ro.navigation_titles(self.book, list(units.values()), self.path)
        source = self.path("Source.md")
        return {"book_id": self.book.name, "name": self.book.name, "title": title,
                "scope_titles": scope_titles,
                "units": list(units.values()), "scopes": self.ordered_scopes(units),
                "conflicts": conflicts, "content_entries": entries,
                "source_info": {"path": "Source.md", "text": ro.read(source) if source.is_file() else ""},
                "initialized": self.path("Materials/workbench/book.json").is_file()}

    @staticmethod
    def ordered_scopes(units):
        groups = {}
        for uid in units:
            parts = uid.split('/')
            sections = groups.setdefault(parts[0], [])
            if len(parts) > 1:
                scope = '/'.join(parts[:2])
                if scope not in sections:
                    sections.append(scope)
        return [scope for chapter, sections in groups.items() for scope in [*sections, chapter]]

    def _catalog(self):
        if self._request_read and self._request_catalog is not None:
            return self._request_catalog
        selected = []
        for entry in self.book.glob("*_Content.md"):
            entry = self.path(entry.relative_to(self.book).as_posix())
            rows = ro.bindings(entry)
            if rows:
                selected.append((entry, rows))
        if len(selected) != 1:
            raise StoreError("登记入口不唯一")
        entry, rows = selected[0]
        units = {}
        for display, tex, material, _ in rows:
            uid = ro.local_id(display)
            if not uid or uid in units:
                raise StoreError("单位编号缺失或重复")
            if material != "Materials/" + uid:
                raise StoreError("登记目录或TeX绑定无效")
            if self._request_read:
                for relative in (tex, material):
                    raw = Path(relative)
                    if raw.is_absolute() or '..' in raw.parts or '\\' in relative or re.match(r'^[A-Za-z]:', relative):
                        raise StoreError('拒绝绝对路径或父目录跳转')
                tp, mp = self.path(tex), self.path(material)
                if not tp.is_file() or not mp.is_dir():
                    raise StoreError('登记目录或TeX绑定无效')
                rp = self.book / material / 'record.md'
            else:
                tp, mp = self.path(tex), self.path(material)
                if not tp.is_file() or not mp.is_dir():
                    raise StoreError("登记目录或TeX绑定无效")
                rp = self.path(material + "/record.md")
            if not self._request_read:
                text = rp.read_text(encoding="utf-8-sig")
                match = re.search(r"TeX[：:]\s*`?([^`\n]+)", text)
                if ro.local_id(text.splitlines()[0]) != uid or not match or match[1].strip() != tex:
                    raise StoreError("record绑定不一致")
            units[uid] = {"id": uid, "display": display, "tex": tex, "material": material,
                          "entry": entry.relative_to(self.book).as_posix(), "record": rp.relative_to(self.book).as_posix()}
        if len({u["tex"] for u in units.values()}) != len(units):
            raise StoreError("多个单位绑定同一TeX")
        if self._request_read:
            self._request_catalog = units
        return units

    def registered_ids(self):
        """未初始化GET仅校验登记ID；无正文/record读取，无写入。"""
        selected = []
        for raw in self.book.glob("*_Content.md"):
            entry = self.path(raw.relative_to(self.book).as_posix())
            rows = ro.bindings(entry)
            if rows:
                selected.append(rows)
        if len(selected) != 1:
            raise StoreError("登记入口不唯一")
        units = {}
        for display, tex, material, _ in selected[0]:
            uid = ro.local_id(display)
            if not uid or uid in units or material != "Materials/" + uid:
                raise StoreError("单位编号或登记目录冲突")
            for relative in (tex, material):
                raw = Path(relative)
                if raw.is_absolute() or '..' in raw.parts or '\\' in relative or re.match(r'^[A-Za-z]:', relative):
                    raise StoreError('拒绝绝对路径或父目录跳转')
            units[uid] = {"id": uid}
        return units

    def _unit(self, uid):
        units = self._catalog()
        if not isinstance(uid, str) or uid not in units:
            raise StoreError("单位未登记")
        unit = units[uid]
        if self._request_read:
            if not self.path(unit['tex']).is_file() or not self.path(unit['material']).is_dir():
                raise StoreError('登记目录或TeX绑定无效')
            text = self.path(unit['record']).read_text(encoding='utf-8-sig')
            match = re.search(r'TeX[：:]\s*`?([^`\n]+)', text)
            if not text.splitlines() or ro.local_id(text.splitlines()[0]) != uid or not match or match[1].strip() != unit['tex']:
                raise StoreError('record绑定不一致')
        return unit

    def _review(self, unit):
        index = None
        if index is None or (self._request_read and unit['id'] not in index):
            paths = None
            if self._request_read:
                paths = []
                directory = self.path(unit['material'])
                materials = self.path('Materials')
                while directory.is_relative_to(materials):
                    candidate = directory / 'review.md'
                    if candidate.is_file():
                        paths.append(candidate)
                    if directory == materials:
                        break
                    directory = directory.parent
            index = self._review_index(paths)
            if self._request_read:
                self._request_reviews = index
        matches = index.get(unit["id"], [])
        if len(matches) != 1:
            raise StoreError("审核单位行缺失或重复")
        p, text, number, headers, parts, row = matches[0]
        if len(parts[1:-1]) != len(headers) or len(set(headers)) != len(headers):
            raise StoreError("审核表列不完整或重复")
        directory = self.path(unit["material"])
        if not directory.is_relative_to(p.parent) or row["TeX"] != unit["tex"]:
            raise StoreError("review目录/TeX错绑定")
        prefix = Path(unit["entry"]).stem.removesuffix("_Content")
        if re.match(r"^[A-Z]+-", row["目编号"]) and not row["目编号"].startswith(prefix + "-"):
            raise StoreError("review别名与登记入口不一致")
        return p, text, number, headers, parts, row

    def _review_index(self, paths=None):
        index = {}
        for raw in (self.path("Materials").rglob("review.md") if paths is None else paths):
            p = self.path(raw.relative_to(self.book).as_posix())
            text = p.read_bytes().decode("utf-8")
            if "\r" in text:
                raise StoreError("审核文件须为LF；不擅自规范化历史文件")
            headers = None
            for number, line in enumerate(text.splitlines(keepends=True)):
                if not line.strip().startswith("|"):
                    headers = None
                    continue
                parts = line.rstrip("\n").split("|")
                cells = [c.strip().strip("`") for c in parts[1:-1]]
                if "目编号" in cells and "TeX" in cells:
                    headers = cells
                elif headers and not all(re.fullmatch(r"[: -]+", c) for c in cells):
                    row = dict(zip(headers, cells))
                    uid = ro.local_id(row.get("目编号", ""))
                    index.setdefault(uid, []).append((p, text, number, headers, parts, row))
        return index

    def _basis(self, units):
        paths = {u[k] for u in units for k in ("tex", "entry", "record")}
        if self.path("Source.md").exists():
            paths.add("Source.md")
        return {p: digest(self.path(p).read_bytes()) for p in sorted(paths)}

    def _markers(self, text):
        result = {}
        for match in MARKER.finditer(text):
            try:
                data = json.loads(match[1])
                key = (data["unit_id"], data["stage"])
                if key in result or data["book_id"] != self.identity()["book_id"]:
                    raise StoreError("版本依据重复或身份不匹配")
                result[key] = (match, data)
            except (KeyError, json.JSONDecodeError) as exc:
                raise StoreError("版本依据损坏") from exc
        return result

    def _put_basis(self, text, uid, stage, basis):
        markers = self._markers(text)
        value = {"book_id": self.identity()["book_id"], "unit_id": uid, "stage": stage, "basis": basis}
        line = "<!-- workbench-basis " + json.dumps(value, ensure_ascii=True, sort_keys=True) + " -->"
        if (uid, stage) in markers:
            match, _ = markers[(uid, stage)]
            return text[:match.start()] + line + text[match.end():]
        return text + ("" if text.endswith("\n") else "\n") + line + "\n"

    @staticmethod
    def _validate_states(patch, row, summary=False):
        allowed = {"summary", "reason"} if summary else set(COLUMNS)
        if not isinstance(patch, dict) or not patch or set(patch) - allowed:
            raise StoreError("patch字段不合法")
        for key, value in patch.items():
            cell(value)
            if key in STATES and value not in STATES[key]:
                raise StoreError("非法stage状态")
        merged = dict(row)
        for key, value in patch.items():
            merged[("总结导引" if key == "summary" else "理由") if summary else COLUMNS[key]] = value
        stages = ["summary"] if summary else list(ro.STAGES)[:4]
        for stage in stages:
            label = ro.STAGES[stage]
            value = merged.get(label)
            if value == "不适用" and not merged.get("理由" if summary else "结论", "").strip():
                raise StoreError("不适用必须给出理由")
            if value in {"本轮完成", "本轮通过"}:
                reason = merged.get("理由" if summary else "结论", "")
                if not reason.strip() or re.search(r"错误|不通过|未通过|待修|待补|未解决|有疑点", reason):
                    raise StoreError("错误或缺失结论不能升级完成状态")
                if not summary and merged.get("疑点", "") not in {"", "无", "无疑点"}:
                    raise StoreError("存在未决疑点，不能升级完成")
                if stage == "math" and reason not in {"通过", "本轮通过", "审核通过", "无误"}:
                    raise StoreError("数学通过须有明确通过结论")

    def read_review(self, uid):
        initialized = self.path("Materials/workbench/book.json").is_file()
        if not initialized:
            entries = [(self.path(p.relative_to(self.book).as_posix()), ro.bindings(self.path(p.relative_to(self.book).as_posix()))) for p in self.book.glob("*_Content.md")]
            entries = [(p, rows) for p, rows in entries if rows]
            if len(entries) != 1:
                raise StoreError("登记入口不唯一")
            entry, rows = entries[0]
            matches = [(display, tex, material) for display, tex, material, _ in rows if ro.local_id(display) == uid]
            if len(matches) != 1:
                raise StoreError("单位未登记或重复")
            _, tex, material = matches[0]
            if material != "Materials/" + uid:
                raise StoreError("登记目录冲突")
            if not self.path(tex).is_file() or not self.path(material).is_dir():
                raise StoreError('登记目录或TeX绑定无效')
            unit = {"id": uid, "tex": tex, "material": material, "entry": entry.name}
            _, text, _, _, _, row = self._review(unit)
            return {"initialized": False, "unit_id": uid, "row": row,
                    "basis_status": {stage: "missing（未初始化，未核验依据）" for stage in ro.STAGES if stage != "summary"}}
        self.identity()
        unit = self._unit(uid)
        p, text, _, _, _, row = self._review(unit)
        markers = self._markers(text)
        current = self._basis([unit])
        evidence = {}
        for stage in COLUMNS.keys() - {"issues", "conclusion"}:
            saved = markers.get((uid, stage))
            evidence[stage] = "missing" if not saved or saved[1].get("basis") is None else ("current" if saved[1].get("basis") == current else "stale")
        return {"unit_id": uid, "sha256": digest(text.encode("utf-8")), "row": row, "basis_status": evidence}

    def patch_review(self, uid, patch, expected):
        with self.lock():
            self.identity()
            unit = self._unit(uid)
            p, text, n, headers, parts, row = self._review(unit)
            self._check(p, expected)
            if expected is None:
                raise StoreError("审核补丁必须有expected")
            self._validate_states(patch, row)
            for key, value in patch.items():
                heading = COLUMNS[key]
                if heading not in headers:
                    raise StoreError("目标列不存在")
                index = headers.index(heading) + 1
                old = parts[index]
                left = old[:len(old) - len(old.lstrip())]
                right = old[len(old.rstrip()):]
                parts[index] = left + value + right
            lines = text.splitlines(keepends=True)
            lines[n] = "|".join(parts) + ("\n" if lines[n].endswith("\n") else "")
            updated = "".join(lines)
            basis = self._basis([unit])
            for stage in patch.keys() & STATES.keys():
                updated = self._put_basis(updated, uid, stage, basis)
            # 只更新审核文字也会使原完成依据缺失，不能冒充新一轮核验。
            if {"issues", "conclusion"} & patch.keys():
                for stage in COLUMNS.keys() - {"issues", "conclusion"} - patch.keys():
                    if (uid, stage) in self._markers(updated):
                        updated = self._put_basis(updated, uid, stage, None)
            if self._basis([unit]) != basis:
                raise Conflict("正文或绑定在保存期间变化")
            return self._write(p, updated.encode("utf-8"), expected)

    def read_runtime(self):
        identity = self.identity()
        data = self.path("Materials/workbench/runtime.json").read_bytes()
        value = json.loads(data)
        if value.get("book_id") != identity["book_id"] or type(value.get("revision")) is not int:
            raise StoreError("runtime身份或版本无效")
        return {"sha256": digest(data), "data": value}

    def patch_runtime(self, patch, expected, expected_revision):
        with self.lock():
            old = self.read_runtime()
            if old["sha256"] != expected or type(expected_revision) is not int or old["data"]["revision"] != expected_revision:
                raise Conflict("runtime version mismatch")
            allowed = {"current_body", "current_proof", "current_summary", "plan", "version_basis"}
            if not isinstance(patch, dict) or not patch or set(patch) - allowed:
                raise StoreError("运行状态patch字段无效")
            units = self._catalog()
            scopes = self._scopes(units)
            for key, value in patch.items():
                if key.startswith("current_"):
                    valid = scopes if key == "current_summary" else units
                    if value is not None and (not isinstance(value, str) or value not in valid):
                        raise StoreError("当前位置须为已登记单位/总结范围或null")
                elif key == "plan":
                    if not isinstance(value, list) or any(not isinstance(v, str) or v not in units for v in value) or len(set(value)) != len(value):
                        raise StoreError("计划须为不重复的已登记unit列表")
                elif key == "version_basis":
                    if not isinstance(value, dict) or any(not isinstance(k, str) or k not in units or not isinstance(v, str) or not HASH.fullmatch(v) for k, v in value.items()):
                        raise StoreError("运行版本依据须为unit到完整SHA256映射；不充当审核权威")
            value = old["data"] | patch
            value["revision"] += 1
            return self._write(self.path("Materials/workbench/runtime.json"), encode(value), expected)

    def _scopes(self, units):
        scopes = set()
        for uid in units:
            for n in (1, 2):
                candidate = "/".join(uid.split("/")[:n])
                if SCOPE.fullmatch(candidate) and self.path("Materials/" + candidate).is_dir():
                    scopes.add(candidate)
        return scopes

    def create_summaries(self):
        with self.lock():
            self.identity()
            units = self._catalog()
            rows = ["# 章/§总结审核\n\n", "| 范围 | 总结导引 | 理由 |\n", "| --- | --- | --- |\n"]
            rows.extend("| " + scope + " | 未检查 |  |\n" for scope in sorted(self._scopes(units)))
            return self._write(self.path("Materials/workbench/summaries.md"), "".join(rows).encode("utf-8"), None)

    def _summary(self, scope):
        units = self._catalog()
        if not isinstance(scope, str) or scope not in self._scopes(units):
            raise StoreError("总结范围未登记")
        p = self.path("Materials/workbench/summaries.md")
        text = p.read_bytes().decode("utf-8")
        if "\r" in text:
            raise StoreError("总结文件必须为LF")
        matches = []
        for n, line in enumerate(text.splitlines(keepends=True)):
            parts = line.rstrip("\n").split("|")
            if len(parts) == 5 and parts[1].strip() == scope:
                matches.append((n, parts))
        if len(matches) != 1:
            raise StoreError("总结行缺失或重复")
        n, parts = matches[0]
        basis = self._basis([u for uid, u in units.items() if uid == scope or uid.startswith(scope + "/")])
        return p, text, n, parts, basis

    def read_summary(self, scope):
        self.identity()
        p, text, _, parts, basis = self._summary(scope)
        saved = self._markers(text).get((scope, "summary"))
        return {"sha256": digest(text.encode("utf-8")), "state": parts[2].strip(), "reason": parts[3].strip(),
                "basis_status": "missing" if not saved or saved[1].get("basis") is None else ("current" if saved[1]["basis"] == basis else "stale")}

    def patch_summary(self, scope, patch, expected):
        with self.lock():
            self.identity()
            p, text, n, parts, basis = self._summary(scope)
            if expected is None:
                raise StoreError("总结补丁必须有expected")
            self._check(p, expected)
            self._validate_states(patch, {"总结导引": parts[2].strip(), "理由": parts[3].strip()}, summary=True)
            for key, value in patch.items():
                parts[2 if key == "summary" else 3] = " " + value + " "
            lines = text.splitlines(keepends=True)
            lines[n] = "|".join(parts) + ("\n" if lines[n].endswith("\n") else "")
            updated = self._put_basis("".join(lines), scope, "summary", basis if "summary" in patch else None)
            if self._summary(scope)[4] != basis:
                raise Conflict("总结依据在保存期间变化")
            return self._write(p, updated.encode("utf-8"), expected)

    def list_backups(self):
        self.identity()
        base = self.path("Materials/workbench/backups")
        result = []
        if base.exists():
            for folder in sorted(base.iterdir()):
                if not re.fullmatch(r"\d{8}T\d{12}Z_[0-9a-f-]{36}", folder.name):
                    continue
                manifest = self.path("Materials/workbench/backups/" + folder.name + "/manifest.json")
                data = json.loads(manifest.read_bytes())
                if data.get("book_id") == self.identity()["book_id"] and data.get("backup_id") == folder.name:
                    result.append(data)
        return result

    def restore(self, backup_id, expected):
        with self.lock():
            whitelist = {b["backup_id"]: b for b in self.list_backups()}
            if not isinstance(backup_id, str) or backup_id not in whitelist:
                raise StoreError("备份不在本书清单白名单内")
            b = whitelist[backup_id]
            if not b["existed"] or expected is None:
                raise StoreError("仅恢复已有文件内容，必须指定当前expected")
            target = b["target"]
            allowed = {"Materials/workbench/runtime.json", "Materials/workbench/summaries.md"}
            for unit in self._catalog().values():
                directory = self.path(unit["material"])
                while directory != self.path("Materials").parent:
                    candidate = directory / "review.md"
                    if candidate.is_file():
                        allowed.add(self.path(candidate.relative_to(self.book).as_posix()).relative_to(self.book).as_posix())
                    if directory == self.path("Materials"):
                        break
                    directory = directory.parent
            if target not in allowed:
                raise StoreError("不允许恢复身份或任意文件")
            data = self.path("Materials/workbench/backups/" + backup_id + "/payload").read_bytes()
            if digest(data) != b["sha256"]:
                raise StoreError("备份内容哈希不匹配")
            return self._write(self.path(target), data, expected)


def init(root, book_dir):
    """唯一显式初始化入口；身份已存在时保持原始字节。"""
    return BookStore(root, book_dir).init()


def main():
    parser = argparse.ArgumentParser(description="书内受控保存，不启动HTTP/UI")
    parser.add_argument("--root", required=True)
    parser.add_argument("--book", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("runtime")
    sub.add_parser("backups")
    sub.add_parser("create-summaries")
    for name in ("review", "summary"):
        p = sub.add_parser(name)
        p.add_argument("unit")
    for name in ("patch-review", "patch-summary", "patch-runtime"):
        p = sub.add_parser(name)
        if name != "patch-runtime":
            p.add_argument("unit")
        p.add_argument("--patch", required=True, help="JSON字段补丁，不接受文件路径")
        p.add_argument("--expected", required=True)
        if name == "patch-runtime":
            p.add_argument("--revision", required=True, type=int)
    p = sub.add_parser("restore")
    p.add_argument("backup_id")
    p.add_argument("--expected", required=True)
    args = parser.parse_args()
    try:
        store = BookStore(args.root, args.book)
        if args.command == "init":
            result = store.init()
        elif args.command == "runtime":
            result = store.read_runtime()
        elif args.command == "backups":
            result = store.list_backups()
        elif args.command == "create-summaries":
            result = store.create_summaries()
        elif args.command == "review":
            result = store.read_review(args.unit)
        elif args.command == "summary":
            result = store.read_summary(args.unit)
        elif args.command == "patch-runtime":
            result = store.patch_runtime(json.loads(args.patch), args.expected, args.revision)
        elif args.command == "restore":
            result = store.restore(args.backup_id, args.expected)
        else:
            method = store.patch_review if args.command == "patch-review" else store.patch_summary
            result = method(args.unit, json.loads(args.patch), args.expected)
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, "保存失败：" + str(exc) + "\n")


if __name__ == "__main__":
    main()
