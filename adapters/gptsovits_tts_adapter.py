#!/usr/bin/env python3
"""GPT-SoVITS（翔哥音色）TTS adapter for short-drama-produce.

契约: tools/drama-skills/skills/short-drama-produce/references/adapter-contract.md
从 stdin 读一个已确认的 tts job，本机 CPU 合成台词，把最终 wav 拷入 output_root，
stdout 输出适配器契约 JSON。本地即时任务，无 provider 任务号（不用 handle_path）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROFILE = "gptsovits-xiang"

GPT_SOVITS_ROOT = Path(
    os.environ.get("GPTSOVITS_ROOT", r"D:\@佳康顺矩阵\@工具\GPT-SoVITS")
)
SYNTH_SCRIPT = Path(
    os.environ.get(
        "GPTSOVITS_SYNTH_SCRIPT", r"D:\@kaifa\AutoXG\scripts\synthesize_xiang_cpu.py"
    )
)
DEFAULT_REFERENCE = (
    GPT_SOVITS_ROOT
    / "outputs"
    / "wheelchair_top15_voiceclone_cpu"
    / "reference_clip_0316.wav"
)
VENV_PYTHON = GPT_SOVITS_ROOT / ".venv" / "Scripts" / "python.exe"

# 本机 Smart App Control（enforce 模式）会拦截 GPT-SoVITS venv 里未签名的
# opencc_clib*.pyd（WinError 4551）。为此在 shims/ 目录 vendored 了纯 Python 的
# opencc 实现（opencc-python-reimplemented），只通过 PYTHONPATH 注入给合成子进程。
SHIMS_DIR = Path(__file__).resolve().parent / "shims"

INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*]')


def emit_error(code: str, category: str = "configuration", retryable: bool = False) -> int:
    json.dump(
        {
            "error": {
                "provider": PROFILE,
                "category": category,
                "code": code,
                "retryable": retryable,
            }
        },
        sys.stdout,
    )
    return 1


def safe_name(value: str) -> str:
    cleaned = INVALID_WINDOWS_CHARS.sub("_", value).strip(" .")
    return cleaned or "翔哥配音"


def resolve_binding_path(job: dict, binding: dict) -> Path | None:
    raw = binding.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        project_root = job.get("project_root")
        if not isinstance(project_root, str):
            return None
        path = Path(project_root) / path
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="GPT-SoVITS Xiang-voice TTS adapter")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the planned argv and exit 0"
    )
    args = parser.parse_args()

    job = json.load(sys.stdin.buffer)

    if job.get("modality") != "tts":
        return emit_error("unsupported_modality")
    prompt = job.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return emit_error("missing_prompt")
    targets = job.get("outputs") or []
    if len(targets) != 1 or Path(str(targets[0])).suffix.lower() != ".wav":
        return emit_error("unsupported_outputs")
    target = str(targets[0])

    output_root_raw = job.get("output_root")
    if not isinstance(output_root_raw, str):
        return emit_error("missing_output_root")
    output_root = Path(output_root_raw)
    if not output_root.is_absolute() or not output_root.is_dir() or output_root.is_symlink():
        return emit_error("invalid_output_root")

    speed = 1.10
    parameters = job.get("parameters") or {}
    candidate = parameters.get("speed")
    if (
        isinstance(candidate, (int, float))
        and not isinstance(candidate, bool)
        and 0.5 <= float(candidate) <= 2.0
    ):
        speed = float(candidate)

    reference: Path | None = None
    for binding in job.get("reference_bindings") or []:
        if not isinstance(binding, dict) or binding.get("role") != "reference_audio":
            continue
        candidate_path = resolve_binding_path(job, binding)
        if candidate_path is None or not candidate_path.is_file():
            return emit_error("invalid_reference_binding")
        reference = candidate_path
        break

    # synthesize_xiang_cpu.py 的默认 --reference 从硬编码 D:\GPT-SoVITS 推导，
    # 不随 --gpt-sovits-root 变化，必须永远显式传入。
    chosen_reference = reference if reference is not None else DEFAULT_REFERENCE
    for label, path in (
        ("venv_python", VENV_PYTHON),
        ("synth_script", SYNTH_SCRIPT),
        ("reference", chosen_reference),
    ):
        if not path.is_file():
            print(f"{label} missing: {path}", file=sys.stderr)
            return emit_error("missing_dependency")

    name = safe_name(str(job.get("job_id") or "tts"))
    workdir = Path(tempfile.mkdtemp(prefix="gptsovits-tts-"))
    try:
        text_path = workdir / f"{name}.txt"
        text_path.write_text(prompt, encoding="utf-8")
        output_dir = workdir / "out"
        argv = [
            str(VENV_PYTHON),
            "-X",
            "utf8",
            str(SYNTH_SCRIPT),
            "--text",
            str(text_path),
            "--output-dir",
            str(output_dir),
            "--name",
            name,
            "--gpt-sovits-root",
            str(GPT_SOVITS_ROOT),
            "--reference",
            str(chosen_reference),
            "--speed",
            f"{speed:.1f}",
        ]
        if args.dry_run:
            print(json.dumps(argv, ensure_ascii=False))
            return 0

        child_env = os.environ.copy()
        existing_path = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = (
            str(SHIMS_DIR) + os.pathsep + existing_path if existing_path else str(SHIMS_DIR)
        )
        completed = subprocess.run(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=sys.stderr,
            timeout=540,
            env=child_env,
        )
        if completed.returncode != 0:
            return emit_error("synthesis_failed", category="provider_error", retryable=True)

        final_name = f"{name}_翔哥音色_CPU_大段落_{speed:.1f}倍速_句间停顿缩短.wav"
        produced = output_dir / final_name
        if not produced.is_file() or produced.stat().st_size == 0:
            return emit_error(
                "missing_result_file", category="provider_error", retryable=True
            )

        destination = output_root / f"output-0{Path(target).suffix.lower()}"
        shutil.copyfile(produced, destination)
        json.dump(
            {"outputs": [{"target": target, "source": str(destination)}]}, sys.stdout
        )
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
