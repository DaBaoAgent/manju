#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从《分镜.md》与《视频提示词.md》汇总一份可直接操作的「即梦执行包」。
输出到项目的 交付/ 目录：每镜给出挂图清单、首帧图提示词、视频提示词与时长。
用法：python scripts/build_jimeng_pack.py projects/kangfu-001/剧集/EP001 projects/kangfu-001/交付/EP001-即梦执行包.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BLOCK = re.compile(r"(?m)^(?=## )")
SLOT_SPLIT = re.compile(r"；(?=(?:REF|PLAN)-)")
SLOT_HEAD = re.compile(r"^(REF|PLAN)-([A-Za-z0-9\-]+)（顺序：(\d+)）")
SLOT_LOCATOR = re.compile(r"·\s*(.+?)《(.+?)》（用途：([^；]+)")
USE_PLAN_HINT = {
    "起始帧": "本镜首帧图（按上面的首帧图提示词出图）",
    "结束帧": "本镜尾帧图",
}


def blocks(text: str) -> list:
    return [b for b in re.split(BLOCK, text) if b.strip()]


def quote_after(text: str, heading: str) -> str:
    idx = text.find(heading)
    if idx < 0:
        return ""
    lines = []
    for line in text[idx:].splitlines()[1:]:
        if line.startswith("> "):
            lines.append(line[2:].strip())
        elif line.strip() and lines:
            break
        elif line.strip():
            continue
    return " ".join(lines).strip()


def field(text: str, name: str) -> str:
    m = re.search(rf"(?m)^- {name}：(.*)$", text)
    return m.group(1).strip() if m else ""


def describe_slots(line: str) -> list:
    out = []
    for chunk in SLOT_SPLIT.split(line):
        head = SLOT_HEAD.match(chunk.strip())
        loc = SLOT_LOCATOR.search(chunk)
        if not head:
            continue
        kind, slot, order = head.group(1), head.group(2), head.group(3)
        target = loc.group(1).strip() if loc else "?"
        name = loc.group(2).strip() if loc else "?"
        use = loc.group(3).strip() if loc else "?"
        if kind == "REF":
            out.append((order, f"`{target}`《{name}》", use))
        else:
            hint = USE_PLAN_HINT.get(use, f"按 {target}《{name}》出图")
            out.append((order, hint, use))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="生成即梦执行包")
    parser.add_argument("episode_dir")
    parser.add_argument("out_path")
    args = parser.parse_args()

    episode = Path(args.episode_dir)
    storyboard = (episode / "分镜.md").read_text(encoding="utf-8")
    motions = (episode / "视频提示词.md").read_text(encoding="utf-8")

    motion_by_shot = {}
    for block in blocks(motions):
        if not block.startswith("## MOTION-"):
            continue
        shot = field(block, "分镜")
        motion_by_shot[shot] = {
            "name": block.split("·", 1)[1].split("\n", 1)[0].strip() if "·" in block else "",
            "seconds": field(block, "时长"),
            "mode": field(block, "生成方式"),
            "prompt": quote_after(block, "### 可复制提示词"),
        }

    lines = [
        "# EP001 即梦执行包",
        "",
        "> 生成方式：seedance-2.0 方言（中文提示词）。本文件由 `scripts/build_jimeng_pack.py` 从《分镜.md》《视频提示词.md》自动汇总，改上游后重跑即可刷新。",
        "",
        "## 怎么用（三步一镜）",
        "",
        "1. **先出资产图**：按《图片提示词.md》在即梦里出角色板、场景板、助行器道具板（各存一张），本片全靠它们锁一致性。",
        "2. **出首帧图**：把下面每镜的「首帧图提示词」粘进即梦图片生成，按「挂图」清单挂上参考图，出图后保存。",
        "3. **出视频**：在即梦图生视频里上传该首帧图，粘贴「视频提示词」，时长选标注的秒数，生成。",
        "",
        "生成的视频发回给我，我来做下一步（接戏、配音、成片）。",
        "",
    ]

    count = 0
    for block in blocks(storyboard):
        if not block.startswith("## SHOT-"):
            continue
        title = block.split("\n", 1)[0][3:].strip()
        shot_id = title.split("·")[0].strip()
        seconds = field(block, "时长")
        refs = field(block, "输入参考图")
        keyframe = quote_after(block, "### 冻结关键帧提示词")
        motion = motion_by_shot.get(shot_id)
        count += 1

        lines.append(f"## {title} ｜ {seconds}")
        lines.append("")
        lines.append("**挂图（按顺序）**")
        lines.append("")
        slots = describe_slots(refs)
        if slots:
            for order, target, use in sorted(slots, key=lambda s: int(s[0])):
                lines.append(f"{order}. {target} —— 用途：{use}")
        else:
            lines.append("（无）")
        lines.append("")
        lines.append("**首帧图提示词（即梦图片生成）**")
        lines.append("")
        lines.append(f"> {keyframe}")
        lines.append("")
        if motion:
            lines.append(f"**视频提示词（即梦图生视频，选 {motion['seconds']}）**")
            lines.append("")
            lines.append(f"> {motion['prompt']}")
        else:
            lines.append("**视频提示词**：缺失（此镜尚未写 MOTION 条目）")
        lines.append("")

    out = Path(args.out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {out}（{count} 镜）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
