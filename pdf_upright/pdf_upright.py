#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_upright.py — PDF 转正（横躺课件修复）

针对一种特定的坏 PDF：**横版幻灯片被打印成 A4 纵向、内容整体转了 90°，
页面属性 `/Rotate` 却仍是 0**，于是每页都得歪着头看。雨课堂导出的课件就是典型。

成因：导出走的是「打印成 PDF」链路（`Producer: Microsoft: Print To PDF`），
幻灯片先被栅格化（如 720x1280 的竖向位图），再被打印驱动转 90° 塞进纵向 A4 纸张。
旋转只落在像素里，没落进页面属性，所以任何阅读器都不会自动纠正。

修复方式（**不重新编码，画质等同原件**）：
  - 把 90° 旋转直接烘进页面几何：内容流前置一个转置矩阵，页面框换成幻灯片本身的
    大小（`/MediaBox` = `/CropBox` = 16:9 的横向页），`/Rotate` 归 0。
  - 这样不再依赖阅读器对 `/Rotate` 与 `/CropBox` 的解释差异 —— 早先「`/CropBox` + `/Rotate 90`」
    的做法在 SumatraPDF 里会被它自己的 per-file 视图旋转再叠一次，看起来仍然歪。
  - 图像是 `DCTDecode`（JPEG）位图，全程不重新编码：体积基本不变，画质与原件一致。

    python pdf_upright.py                      # 交互面板（总面板进来就是这条路）
    python pdf_upright.py <文件或目录> ...      # 预检 + 就地修复
    python pdf_upright.py <目录> --dry          # 只报告，不写文件
    python pdf_upright.py <目录> -o <输出目录>   # 不动原件，输出到别处
    python pdf_upright.py <目录> -r             # 连子目录一起找
    python pdf_upright.py <目录> --ccw          # 内容躺反了，按逆时针 90° 转正
    python pdf_upright.py <目录> --yes          # 不确认

面板流程：问目录 → 列出该目录下的 PDF 并编号（页数 / 页面尺寸 / 幻灯片尺寸 / 是否需转正）
→ 用编号选 `a` 全部、`1,3`、`2-4`；`r` 切含子目录、`o` 换输出目录、`d` 换转向、回车换目录。

安全性：**默认就地修复，不留「横向版/」之类副本**；覆盖前把原件备份到系统临时目录
`pdf_upright_backup-<时间戳>/`，打印路径可随时取回。已转正的页面（横向页 / 有文字层 /
非整页贴图）逐页跳过，重复跑不会二次旋转。

已知局限：判定只看形状（竖页 + 无文字层 + 整页竖贴图），**分不出内容往哪边躺**。
默认按顺时针 90° 转正（打印驱动产出的是这种）；若结果倒立，说明躺反了，用 `--ccw`
（面板按键 `d`）改逆时针。原件已备份，可以放心重试。
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import pymupdf
except ImportError:          # 缺依赖时在 main() 里换解释器或给出指引
    pymupdf = None

# 旧版输出目录名。现在默认就地修复，不再产出它；
# 保留这个常量只为在递归扫描时跳过历史遗留的副本。
LEGACY_SUBDIR = "横向版"

# 整页贴图的判定门槛：幻灯片图像须占页面面积的这个比例以上
COVER_RATIO = 0.4


# --------------------------------------------------------------------------
# 依赖定位：本机 `python` 未必装了 PyMuPDF，自动找装了的解释器重跑自己
# --------------------------------------------------------------------------
def _has_pymupdf(exe):
    try:
        r = subprocess.run([exe, "-c", "import pymupdf"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30)
        return r.returncode == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _candidates():
    """按优先级给出可能的解释器路径（去重）。"""
    seen = set()

    def add(p):
        if not p:
            return None
        p = Path(p)
        key = str(p).lower()
        if key in seen:
            return None
        seen.add(key)
        return p

    env = os.environ.get("PDF_UPRIGHT_PYTHON")
    for c in (add(env), add(sys.executable)):
        if c:
            yield c
    for name in ("python3", "python", "py"):
        c = add(shutil.which(name))
        if c:
            yield c
    home = Path.home()
    # glob 不会用非点开头的模式匹配点开头的目录，所以这里直接写 .workbuddy
    patterns = (
        os.path.join(".workbuddy", "binaries", "python", "envs", "*", "Scripts", "python.exe"),
        os.path.join(".workbuddy", "binaries", "python", "envs", "*", "bin", "python"),
        os.path.join(".workbuddy", "binaries", "python", "versions", "*", "python.exe"),
    )
    for pat in patterns:
        for hit in sorted(glob.glob(os.path.join(str(home), pat))):
            c = add(hit)
            if c:
                yield c


def _reexec_with_pymupdf():
    """换一个装了 PyMuPDF 的解释器重跑。返回退出码；找不到返回 None。"""
    if os.environ.get("PDF_UPRIGHT_REEXEC") == "1":
        return None
    me = Path(sys.executable).resolve() if sys.executable else None
    for exe in _candidates():
        try:
            same = me is not None and exe.resolve() == me
        except OSError:
            same = False
        if same:
            continue
        if _has_pymupdf(str(exe)):
            print(f"  提示：当前解释器缺 PyMuPDF，改用 {exe}", flush=True)
            env = dict(os.environ)
            env["PDF_UPRIGHT_REEXEC"] = "1"
            try:
                return subprocess.call([str(exe), *sys.argv], env=env)
            except OSError as e:
                print(f"  ✗ 换解释器失败：{e}")
                return None
    return None


def _missing_dep():
    print("  ✗ 当前 Python 里没有 PyMuPDF。")
    print("    换用装了它的解释器：")
    print("      python pdf_upright.py <文件或目录>        # 用系统里任一装了 PyMuPDF 的 python")
    print("    或指定：set PDF_UPRIGHT_PYTHON=<python 路径>")
    print("    或安装：pip install pymupdf")
    return 2


# --------------------------------------------------------------------------
# 探测与转换
# --------------------------------------------------------------------------
def largest_image_bbox(page):
    """页面上面积最大的图像在页面坐标系中的 bbox；没有图像返回 None。"""
    best = None
    for info in page.get_images(full=True):
        try:
            bbox = page.get_image_bbox(info)
        except Exception:
            continue
        if bbox.is_empty or bbox.width <= 0 or bbox.height <= 0:
            continue
        area = bbox.width * bbox.height
        if best is None or area > best[0]:
            best = (area, bbox)
    return best[1] if best else None


def is_sideways(page, bbox):
    """判断这一页是不是「横版幻灯片躺在纵向纸上」。"""
    if bbox is None:
        return False
    rect = page.rect
    if rect.width > rect.height:                 # 页面本身已经是横向
        return False
    if page.get_text().strip():                  # 有文字层 → 不是打印贴图
        return False
    if bbox.height <= bbox.width:                # 幻灯片图形不是竖着贴的
        return False
    return bbox.get_area() >= COVER_RATIO * rect.get_area()


def analyze(path):
    """逐页统计，给出「需转正多少页」以及第一页的尺寸信息。"""
    doc = pymupdf.open(path)
    try:
        first = doc[0]
        bbox = largest_image_bbox(first)
        sideways = 0
        for page in doc:
            if is_sideways(page, largest_image_bbox(page)):
                sideways += 1
        return {
            "path": path,
            "pages": doc.page_count,
            "pw": first.rect.width,
            "ph": first.rect.height,
            "bw": bbox.width if bbox else 0.0,
            "bh": bbox.height if bbox else 0.0,
            "sideways_pages": sideways,
            "sideways": sideways > 0,
        }
    finally:
        doc.close()


def bake_upright(doc, page, box, ccw=False):
    """把「内容竖躺」的这一页连同页面几何一起转正（旋转烘进内容流，不重编码位图）。

    `box` 是幻灯片在页面坐标系里的矩形。转正后：
      - 页面框 = (box 高) × (box 宽)，即 16:9 横向；
      - 内容流前置一个转置矩阵：默认顺时针 90°（`0 -1 1 0`，打印驱动产出的那类），
        `ccw=True` 时改逆时针 90°（`0 1 -1 0`，内容躺反了的那种）；
      - `/Rotate` 归 0 —— 方向只由几何决定，阅读器没有解释余地。
    """
    x0, y0, x1, y1 = box.x0, box.y0, box.x1, box.y1
    new_w, new_h = y1 - y0, x1 - x0
    contents = page.get_contents()
    if not contents:
        return False
    if ccw:
        prefix = b"q 0 1 -1 0 %.4f %.4f cm\n" % (y1, -x0)
    else:
        prefix = b"q 0 -1 1 0 %.4f %.4f cm\n" % (-y0, x1)
    if len(contents) == 1:
        stream = doc.xref_stream(contents[0])
        doc.update_stream(contents[0], prefix + stream + b"\nQ\n")
    else:
        head = doc.xref_stream(contents[0])
        doc.update_stream(contents[0], prefix + head)
        tail = doc.xref_stream(contents[-1])
        doc.update_stream(contents[-1], tail + b"\nQ\n")

    page_box = "[0 0 %.4f %.4f]" % (new_w, new_h)
    for key in ("MediaBox", "CropBox"):
        doc.xref_set_key(page.xref, key, page_box)
    existing = doc.xref_get_keys(page.xref)
    for key in ("TrimBox", "BleedBox", "ArtBox"):
        if key in existing:
            doc.xref_set_key(page.xref, key, page_box)
    doc.xref_set_key(page.xref, "Rotate", "0")
    return True


def convert(src, dst, ccw=False):
    """逐页转正，写到 dst（dst 可与 src 相同，由调用方负责原子替换）。

    返回 {fixed, kept, size_before, size_after}。
    """
    doc = pymupdf.open(src)
    fixed = kept = 0
    try:
        for page in doc:
            bbox = largest_image_bbox(page)
            if is_sideways(page, bbox) and bake_upright(doc, page, bbox, ccw):
                fixed += 1
            else:
                kept += 1
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        doc.save(dst, garbage=3, deflate=True)
    finally:
        doc.close()
    return {
        "fixed": fixed,
        "kept": kept,
        "size_before": os.path.getsize(src),
        "size_after": os.path.getsize(dst),
    }


def human(n):
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def collect(inputs, recursive=False):
    """把「文件或目录」展开成 PDF 文件列表。"""
    files = []
    for item in inputs:
        p = Path(str(item).strip().strip('"').strip("'"))
        if p.is_dir():
            files.extend(find_pdfs(p, recursive))
        elif p.is_file():
            files.append(str(p))
    return files


def find_pdfs(folder, recursive=False):
    """目录下的 PDF；顺带排除旧版输出目录里的副本，免得把历史产出当输入。"""
    folder = Path(folder)
    it = folder.rglob("*.pdf") if recursive else folder.glob("*.pdf")
    return sorted(str(p) for p in it
                  if p.is_file() and p.parent.name != LEGACY_SUBDIR)


def parse_selection(text, n):
    """`a` / `1,3` / `2-4` → 序号列表（1 基）；看不懂返回 None。"""
    t = text.strip().lower()
    if t in ("a", "all", "*"):
        return list(range(1, n + 1))
    picked = []
    for piece in t.replace(" ", "").split(","):
        if not piece:
            continue
        if "-" in piece:
            lo, _, hi = piece.partition("-")
            if not (lo.isdigit() and hi.isdigit()):
                return None
            picked += list(range(int(lo), int(hi) + 1))
        elif piece.isdigit():
            picked.append(int(piece))
        else:
            return None
    picked = sorted({i for i in picked if 1 <= i <= n})
    return picked or None


def backup_root():
    """就地修复时原件去哪儿：系统临时目录下的一个带时间戳的兄弟目录。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = Path(tempfile.gettempdir()) / f"pdf_upright_backup-{stamp}"
    n = 1
    while root.exists():                     # 同一秒跑两次也不撞车
        n += 1
        root = Path(tempfile.gettempdir()) / f"pdf_upright_backup-{stamp}-{n}"
    return root


def run_convert(rows, outdir=None, assume_yes=False, ccw=False):
    """转换 rows 里标了需转正的项。返回成功份数。

    不给 `outdir` 时就地覆盖原文件（覆盖前把原件备份到临时目录）；
    给了 `outdir` 则原件不动，结果写到那个目录。
    `ccw=True` 表示内容躺反了，按逆时针 90° 转正。
    """
    targets = [f for f, info in rows if info and info["sideways"]]
    if not targets:
        print("  没有需要转正的页面。")
        return 0
    out_root = None
    if outdir:
        out_root = Path(outdir).resolve()
        # -o 的语义是「原件不动」；指到源目录就会直接覆盖原件，等于悄悄改成就地模式
        clash = [Path(f) for f in targets
                 if (out_root / Path(f).name).resolve() == Path(f).resolve()]
        if clash:
            print(f"  ✗ 输出目录就是源目录，会覆盖原件：{clash[0].parent}")
            print("    -o 表示「原件不动」，请换一个输出目录；要就地覆盖就别传 -o。")
            return 0
    if not assume_yes:
        where = outdir or "就地覆盖原文件（原件备份到临时目录）"
        ans = input(f"\n  转换这 {len(targets)} 份？{where} [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("  已取消。")
            return 0
    done = 0
    backup_dir = None
    for f in targets:
        src = Path(f)
        if outdir:
            dst = Path(outdir) / src.name
            work = dst
        else:
            dst = src
            work = src.with_name(src.name + ".upright.tmp")
            if backup_dir is None:
                backup_dir = backup_root()
            backup_dir.mkdir(parents=True, exist_ok=True)
            # 备份名带上完整路径（分隔符压平），否则 -r 扫到不同目录下的同名 PDF 会互相覆盖
            flat = str(src.resolve()).replace(":", "").replace("\\", "_").replace("/", "_")
            shutil.copy2(src, backup_dir / flat)
        try:
            r = convert(f, str(work), ccw)
        except Exception as e:
            print(f"  ✗ {src.name}：{type(e).__name__} {e}")
            if work != dst and work.exists():
                work.unlink()
            continue
        if work != dst:
            os.replace(work, dst)
        done += 1
        note = "" if not r["kept"] else f"，{r['kept']} 页原样保留"
        print(f"  ✓ {src.name}　转正 {r['fixed']} 页{note}"
              f"　{human(r['size_before'])} → {human(r['size_after'])}")
        print(f"      → {dst}")
    if done:
        if outdir:
            print(f"\n  完成 {done} 份。原件未改动。")
        else:
            print(f"\n  完成 {done} 份，已就地覆盖。原件备份：{backup_dir}")
    return done


def preflight(files):
    """打印编号表（一行一份），返回 [(文件, 分析结果)]；编号与打印序号严格对应。"""
    rows = []
    print("  " + "-" * 68)
    for i, f in enumerate(files, 1):
        name = Path(f).name
        try:
            info = analyze(f)
        except Exception as e:
            rows.append((f, None))
            print(f"  {i:>2}. {name}　✗ 打不开（{type(e).__name__}）：{e}")
            continue
        rows.append((f, info))
        if info["sideways"]:
            tag = f"需转正（{info['sideways_pages']}/{info['pages']} 页）"
        else:
            tag = "跳过（横向 / 有文字层 / 无整页贴图）"
        slide = (f"{info['bw']:.0f}×{info['bh']:.0f}" if info["bw"] else "—")
        print(f"  {i:>2}. {name:<28} {info['pages']:>3} 页　"
              f"{info['pw']:.0f}×{info['ph']:.0f} → {slide}　{tag}")
    print("  " + "-" * 68)
    need = sum(1 for _f, info in rows if info and info["sideways"])
    print(f"  共 {len(rows)} 份：需转正 {need}，跳过 {len(rows) - need}。")
    return rows


# --------------------------------------------------------------------------
# 交互面板
# --------------------------------------------------------------------------
def ask_dir():
    """问一个目录（也接受单个 PDF；回车用当前目录）。返回 (kind, Path) 或 None。"""
    print("  PDF 所在目录（可粘贴或拖入路径；回车用当前目录；q 退出）：")
    while True:
        try:
            line = input("    目录 > ").strip().strip('"').strip("'")
        except (EOFError, KeyboardInterrupt):
            return None
        if line.lower() in ("q", "quit"):
            return None
        p = Path(line) if line else Path.cwd()
        if p.is_file() and p.suffix.lower() == ".pdf":
            return ("file", p)
        if p.is_dir():
            return ("dir", p.resolve())
        print("      ✗ 既不是目录也不是 PDF 文件，再试一次")


def pause():
    """等一次回车；返回 False 表示该退出了。"""
    try:
        input("\n  按回车继续…")
        return True
    except (EOFError, KeyboardInterrupt):
        return False


def interactive():
    print("=" * 68)
    print("  PDF 转正（横躺课件修复）")
    print("=" * 68)
    print("  修「横版幻灯片被打印成 A4 纵向、内容转了 90°」的 PDF：")
    print("  裁掉白边与侧边水印列，再把页面转正成 16:9 横向。不重新编码，画质不变。")
    print("  默认就地修复原文件；覆盖前会把原件备份到系统临时目录。")
    print()

    outdir = None
    recursive = False
    ccw = False
    while True:
        target = ask_dir()
        if target is None:
            return 0
        kind, path = target

        if kind == "file":                       # 直接给了一份 PDF：只处理它
            print()
            rows = preflight([str(path)])
            run_convert(rows, outdir, assume_yes=True, ccw=ccw)
            if not pause():
                return 0
            continue

        while True:                              # 同一目录里反复选
            files = find_pdfs(path, recursive)
            if not files:
                if recursive:
                    print(f"  ✗ {path} 及其子目录下没有 PDF。")
                    break
                print(f"  {path} 下没有 PDF，改成含子目录再看…")
                recursive = True
                continue
            print()
            rows = preflight(files)
            print(f"  目录：{path}{'（含子目录）' if recursive else ''}")
            print(f"  输出：{outdir or '就地覆盖原文件（原件备份到系统临时目录）'}")
            print(f"  转向：{'逆时针 90°' if ccw else '顺时针 90°'}（转出来倒立就换一个）")
            print()
            print("     a                 全部转换")
            print("     1 或 1,3 或 2-4   只转这几个序号")
            print("     r                 切换是否含子目录")
            print("     o                 换成输出到别的目录（不动原件）")
            print("     d                 切换转向（顺时针 / 逆时针 90°）")
            print("     回车 / q          换目录 / 退出")
            try:
                ans = input("\n  选择：").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return 0
            if not ans:
                break
            if ans in ("q", "quit"):
                return 0
            if ans == "r":
                recursive = not recursive
                continue
            if ans == "d":
                ccw = not ccw
                print(f"  转向已切换为：{'逆时针 90°' if ccw else '顺时针 90°'}")
                continue
            if ans == "o":
                try:
                    d = input("  输出目录（留空恢复就地修复）：").strip().strip('"').strip("'")
                except (EOFError, KeyboardInterrupt):
                    return 0
                outdir = d or None
                continue

            picks = parse_selection(ans, len(rows))
            if picks is None:
                print("  ✗ 没看懂，用 a / 1,3 / 2-4 / r / o / d / 回车。")
                continue
            chosen = []
            for i in picks:
                f, info = rows[i - 1]
                if info and info["sideways"]:
                    chosen.append((f, info))
                else:
                    print(f"  · 第 {i} 份（{Path(f).name}）不需要转正，跳过")
            if not chosen:
                print("  选中的都不需要转正。")
            else:
                run_convert(chosen, outdir, assume_yes=True, ccw=ccw)   # 已用编号选过，不再二次确认
            if not pause():
                return 0


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------
def cli(argv):
    args = [a for a in argv]
    dry = "--dry" in args
    yes = "--yes" in args
    ccw = "--ccw" in args
    recursive = "-r" in args or "--recursive" in args
    outdir = None
    for flag in ("-o", "--out"):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                outdir = args[i + 1]
                del args[i:i + 2]
    for flag in ("--dry", "--yes", "--ccw", "-r", "--recursive"):
        while flag in args:
            args.remove(flag)
    inputs = [a for a in args if not a.startswith("-")]
    if not inputs:
        print("用法：python pdf_upright.py <文件或目录> ... [--dry] [-o 另存目录] "
              "[-r 含子目录] [--ccw] [--yes]")
        print("      默认就地覆盖原文件；-o 则原件不动，结果写到指定目录。")
        print("      默认顺时针转正；转出来是倒立的话加 --ccw 换逆时针。")
        return 1

    files = collect(inputs, recursive)
    if not files:
        print("没有找到 PDF。")
        return 1

    rows = preflight(files)
    need = sum(1 for _f, info in rows if info and info["sideways"])
    if not need:
        return 0
    if dry:
        print("  仅预检，未写文件。")
        return 0
    run_convert(rows, outdir, assume_yes=yes, ccw=ccw)
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if pymupdf is None:
        code = _reexec_with_pymupdf()
        if code is not None:
            return code
        return _missing_dep()

    if not sys.argv[1:]:
        return interactive()
    return cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
