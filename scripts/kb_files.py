#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""公司知识库文件通道客户端（8789 HTTP）。

用途：把公司知识库/网盘里的原始素材（产品图、视频、说明书等）拉到本地，
供 manju 漫剧项目当参考图/资产用。MCP 只给文字，二进制一律走这条 HTTP 通道。

依赖：只用标准库；鉴权读环境变量 COMPANY_KB_TOKEN（不要写进任何文件）。

常用命令：
  列目录（一层）：
    python scripts/kb_files.py list --root archive --path "10 产品高清图"
  列目录（递归）：
    python scripts/kb_files.py list --root archive --path "10 产品高清图/白底图" -r --depth 3
  递归下载（先干跑看清单，再真下）：
    python scripts/kb_files.py pull --root archive --path "10 产品高清图/白底图/朋友2-绿-带扶手" --dest assets/refs/jks/助行器朋友2/白底图-带扶手 -r --dry-run
    python scripts/kb_files.py pull --root archive --path "10 产品高清图/白底图/朋友2-绿-带扶手" --dest assets/refs/jks/助行器朋友2/白底图-带扶手 -r --include "*.png"
  下载单个文件：
    python scripts/kb_files.py get --root archive --path "10 产品高清图/白底图/x.png" --dest assets/refs/jks

要点：
- root 只能取 files / archive / inbox。
- pull 会在 --dest 下写 _manifest.json（来源路径、字节数、sha256、抓取时间），可追溯、可增量重跑。
- --dry-run 只打印清单不落盘；--max-bytes 挡住超大单文件；--include 按文件名 glob 过滤。
- 显式禁用系统代理（内网直连更稳），并可用 KB_FILES_BASE 覆盖服务地址。
- 中文名坑：8789 的 /api/get 目前对非 ASCII 文件名会直接断连（服务端 bug，ASCII 名正常）。
  传 --mirror-root，或设环境变量 KB_MIRROR_ARCHIVE / KB_MIRROR_FILES 指向本机同名镜像目录后，
  中文名会自动改走本地复制，并仍按远端 size 校验一致性。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE = os.environ.get("KB_FILES_BASE", "http://192.168.1.79:8789")
ALLOWED_ROOTS = ("files", "archive", "inbox")
TIMEOUT = 300


class KbError(RuntimeError):
    """知识库通道错误；配置了本地镜像时可由调用方回落到本地复制。"""


def token() -> str:
    tok = os.environ.get("COMPANY_KB_TOKEN", "").strip()
    if not tok:
        raise SystemExit("缺少环境变量 COMPANY_KB_TOKEN")
    return tok


def request(path: str, params: dict) -> bytes:
    url = f"{DEFAULT_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()[:400].decode("utf-8", "replace")
        raise KbError(f"HTTP {exc.code} {url}\n{body}")
    except Exception as exc:
        raise KbError(f"请求失败 {url}\n{exc}")


def api_list(root: str, path: str) -> list:
    if root not in ALLOWED_ROOTS:
        raise SystemExit(f"root 只能是 {ALLOWED_ROOTS}")
    data = json.loads(request("/api/list", {"root": root, "path": path}))
    if not data.get("ok"):
        raise SystemExit(f"列目录失败：{data}")
    return data.get("entries", [])


def api_get(root: str, path: str, dest: Path) -> tuple:
    blob = request("/api/get", {"root": root, "path": path})
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return len(blob), hashlib.sha256(blob).hexdigest()


def is_ascii(name: str) -> bool:
    return all(ord(ch) < 128 for ch in name)


def mirror_root_for(args) -> Path | None:
    """本次运行的 root 对应的本地镜像目录（--mirror-root 或 KB_MIRROR_<ROOT>）。"""
    base = getattr(args, "mirror_root", None) or os.environ.get(f"KB_MIRROR_{args.root.upper()}")
    if not base:
        return None
    path = Path(base)
    return path if path.is_dir() else None


def copy_from_mirror(base: Path, rel: str, dest: Path, expect_size: int) -> tuple:
    src = base / Path(rel)
    if not src.is_file():
        raise KbError(f"本地镜像缺少文件：{src}")
    size = src.stat().st_size
    if expect_size and size != expect_size:
        raise KbError(f"本地镜像与远端大小不一致（远端 {expect_size} / 本地 {size}）：{src}\n"
                      f"多半是百度网盘还没同步完，等同步后再重跑")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return size, hashlib.sha256(dest.read_bytes()).hexdigest()


def human(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{n}B" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}GB"


def walk(root: str, path: str, depth: int) -> list:
    """递归收集 (相对路径, 条目)。depth < 0 表示不限深度，0 表示只看本层。"""
    out = []
    for entry in api_list(root, path):
        rel = f"{path}/{entry['name']}" if path else entry["name"]
        if entry.get("is_dir"):
            if depth != 0:
                out.extend(walk(root, rel, depth - 1))
        else:
            out.append((rel, entry))
    return out


def cmd_list(args) -> int:
    if args.recursive:
        items = walk(args.root, args.path, args.depth)
        total = sum(e.get("size", 0) for _, e in items)
        for rel, entry in items:
            print(f"{human(entry.get('size', 0)):>10}  {rel}")
        print(f"\n共 {len(items)} 个文件，合计 {human(total)}")
    else:
        entries = api_list(args.root, args.path)
        for entry in entries:
            kind = "DIR " if entry.get("is_dir") else "FILE"
            print(f"{kind} {human(entry.get('size', 0)):>10}  {entry['name']}")
        print(f"\n{args.path or '/'} 下 {len(entries)} 项")
    return 0


def select(items: list, patterns: list, max_bytes: int) -> list:
    picked = []
    for rel, entry in items:
        if patterns and not any(fnmatch.fnmatch(entry["name"].lower(), p.lower()) for p in patterns):
            continue
        if max_bytes and entry.get("size", 0) > max_bytes:
            print(f"  跳过（超过 --max-bytes）：{rel} {human(entry['size'])}")
            continue
        picked.append((rel, entry))
    return picked


def cmd_pull(args) -> int:
    depth = args.depth if args.recursive else 0
    items = walk(args.root, args.path, depth)
    picked = select(items, args.include or [], args.max_bytes)
    if not picked:
        print("没有匹配的文件")
        return 1
    total = sum(e["size"] for _, e in picked)
    print(f"候选 {len(picked)} 个文件，合计 {human(total)} → {args.dest}")
    if args.dry_run:
        for rel, entry in picked:
            print(f"  DRY {human(entry['size']):>10}  {rel}")
        return 0

    dest_root = Path(args.dest).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    manifest_path = dest_root / "_manifest.json"
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "source_base": DEFAULT_BASE,
                "root": args.root, "source_path": args.path, "files": []}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.setdefault("files", [])
        except json.JSONDecodeError:
            pass
    known = {f["source_path"]: f for f in manifest["files"]}

    mirror = mirror_root_for(args)
    if mirror:
        print(f"本地镜像：{mirror}（中文名或 HTTP 失败时改走本地复制）")
    for rel, entry in picked:
        local_rel = rel[len(args.path):].lstrip("/") if (args.flatten or not args.keep_tree) else rel
        local = dest_root / local_rel
        if local.exists() and local.stat().st_size == entry.get("size", 0) and rel in known:
            print(f"  已存在，跳过：{local_rel}")
            continue
        via = "http"
        if mirror and not is_ascii(Path(rel).name):
            via = "mirror"
            size, sha = copy_from_mirror(mirror, rel, local, entry.get("size", 0))
        else:
            try:
                size, sha = api_get(args.root, rel, local)
            except KbError:
                if not mirror:
                    raise
                print(f"  HTTP 失败，回落本地镜像：{rel}")
                via = "mirror"
                size, sha = copy_from_mirror(mirror, rel, local, entry.get("size", 0))
        if size != entry.get("size", 0):
            print(f"  警告：字节数不一致（远端 {entry.get('size')} / 本地 {size}）：{rel}")
        known[rel] = {"source_path": rel, "via": via,
                      "local_path": str(local.relative_to(dest_root)).replace("\\", "/"),
                      "bytes": size, "sha256": sha,
                      "fetched_at": datetime.now(timezone.utc).isoformat()}
        label = "下载" if via == "http" else "镜像"
        print(f"  {label} {human(size):>10}  {local_rel}")

    manifest["files"] = sorted(known.values(), key=lambda f: f["source_path"])
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成，清单写入 {manifest_path}")
    return 0


def cmd_get(args) -> int:
    name = args.path.rstrip("/").split("/")[-1]
    dest = Path(args.dest)
    if dest.is_dir() or args.dest.endswith(("/", "\\")):
        dest = dest / name
    size, sha = api_get(args.root, args.path, dest)
    print(f"已下载 {human(size)} → {dest}\nsha256={sha}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="公司知识库文件通道客户端（8789）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出目录")
    p_list.add_argument("--root", default="files")
    p_list.add_argument("--path", default="")
    p_list.add_argument("-r", "--recursive", action="store_true")
    p_list.add_argument("--depth", type=int, default=-1, help="递归深度，-1=不限")
    p_list.set_defaults(func=cmd_list)

    p_pull = sub.add_parser("pull", help="递归下载目录")
    p_pull.add_argument("--root", default="files")
    p_pull.add_argument("--path", required=True)
    p_pull.add_argument("--dest", required=True)
    p_pull.add_argument("-r", "--recursive", action="store_true")
    p_pull.add_argument("--depth", type=int, default=-1)
    p_pull.add_argument("--include", action="append", help="文件名 glob，可重复")
    p_pull.add_argument("--max-bytes", type=int, default=0, help="单文件字节上限，0=不限")
    p_pull.add_argument("--flatten", action="store_true", help="只保留文件名，不保留来源目录层级")
    p_pull.add_argument("--keep-tree", action="store_true", help="按来源完整相对路径落盘")
    p_pull.add_argument("--mirror-root", help="本机镜像根目录（对应 --root 的磁盘路径），中文名/失败时走本地复制")
    p_pull.add_argument("--dry-run", action="store_true")
    p_pull.set_defaults(func=cmd_pull)

    p_get = sub.add_parser("get", help="下载单个文件")
    p_get.add_argument("--root", default="files")
    p_get.add_argument("--path", required=True)
    p_get.add_argument("--dest", required=True)
    p_get.set_defaults(func=cmd_get)

    args = parser.parse_args()
    try:
        return args.func(args)
    except KbError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
