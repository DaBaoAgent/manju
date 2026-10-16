#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把《分镜.md》每镜的「输入参考图」行同步到《视频提示词.md》对应 MOTION 条目。
分镜是参考图清单的唯一权威，视频文档必须逐字一致（creator_markdown_check.py 会核对）。
用法：python scripts/sync_ref_lines.py projects/kangfu-001/剧集/EP001 [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SHOT_ID = re.compile(r"(?m)^## (SHOT-\S+?) ·")
MOTION_ID = re.compile(r"(?m)^## (MOTION-\S+?) ·")
FIELD = re.compile(r"(?m)^- 输入参考图：(.*)$")
SOURCE = re.compile(r"(?m)^- 分镜：(SHOT-\S+)\s*$")


def blocks(text: str) -> list:
    return [p for p in re.split(r"(?m)^(?=## )", text) if p.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="同步分镜到视频提示词的输入参考图行")
    parser.add_argument("episode_dir")
    parser.add_argument("--check", action="store_true", help="只报告差异，不写回")
    args = parser.parse_args()
    episode = Path(args.episode_dir)
    sb_path = episode / "分镜.md"
    vp_path = episode / "视频提示词.md"
    sb_text = sb_path.read_text(encoding="utf-8")
    vp_text = vp_path.read_text(encoding="utf-8")

    refs = {}
    for block in blocks(sb_text):
        shot = SHOT_ID.match(block)
        field = FIELD.search(block)
        if shot and field:
            refs[shot.group(1)] = field.group(1).strip()

    changed = 0
    out = []
    for block in blocks(vp_text):
        motion = MOTION_ID.match(block)
        source = SOURCE.search(block)
        field = FIELD.search(block)
        if motion and source and field and source.group(1) in refs:
            want = refs[source.group(1)]
            if field.group(1).strip() != want:
                block = FIELD.sub("- 输入参考图：" + want, block, count=1)
                changed += 1
                print(f"  同步 {motion.group(1)} <- {source.group(1)}")
        out.append(block)

    if changed and not args.check:
        vp_path.write_text("".join(out), encoding="utf-8")
    print(f"{'发现' if args.check else '修正'} {changed} 处不一致")
    return 1 if (changed and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
