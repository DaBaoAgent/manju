#!/usr/bin/env python3
"""AutoDL.Art H3 视频 adapter for short-drama-produce。

照 AutoMN（DaBaoAgent/AutoMN，hypit.runtime.json + provider-autodl-h3 生产验证）的模式：
- 参考图/音频以 base64 data URL 内联提交（无需上传/登录），单张上限 6MB，
  超限自动缩到最长边 1280px（PIL）；
- 提交 POST /api/v1/comfyui/comfyui_workflow/{id} → task_id；
- 轮询 GET /api/v1/comfyui/comfyui_workflow/result/{id}（默认 15s 间隔）；
- SUCCESS → results[] 里 type=="video" 的 url → 直接下载（结果 URL 公开）。

付费护栏（双保险）：只有 AUTODL_ALLOW_SUBMIT=1 且未设 AUTODL_DRY_RUN=1 才真正提交；
否则把将提交的请求体打到 stderr，并以安全错误对象退出（不产生任何费用）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

MAX_REF_BYTES = 6291456  # 6MB，AutoMN 实测值
SHRINK_LONG_SIDE = 1280
POLL_INTERVAL = float(os.environ.get("AUTODL_POLL_INTERVAL", "15"))
POLL_TIMEOUT = float(os.environ.get("AUTODL_POLL_TIMEOUT", "1800"))
DOWNLOAD_TIMEOUT = 900
API_TIMEOUT = 120

MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".flac": "audio/flac",
}

# 工作流路由（照 AutoMN hypit.runtime.json 的规格与 prefer 顺序）
SPEC_B99_003_12S = "minimax_h3_b99_003_12s"
SPEC_V5 = "minimax_h3_lightx2v_v5"
SPEC_V5_15S = "minimax_h3_lightx2v_v5_15s"
SPEC_B99_001 = "minimax_h3_b99_001"
SPEC_NO_PIC = "minimax_h3_lightx2v_no_pic"
SPEC_B99_002 = "minimax_h3_b99_002"
SPEC_AUDIO = "minimax_h3_image_audio_to_video"


class AdapterError(Exception):
    def __init__(self, code: str, category: str = "configuration", retryable: bool = False, http_status: int | None = None):
        super().__init__(code)
        self.code = code
        self.category = category
        self.retryable = retryable
        self.http_status = http_status


def emit_error(exc: AdapterError, profile: str) -> int:
    error = {
        "provider": profile,
        "category": exc.category,
        "code": exc.code,
        "retryable": exc.retryable,
    }
    if exc.http_status is not None:
        error["http_status"] = exc.http_status
    json.dump({"error": error}, sys.stdout)
    return 1


def resolve_path(job: dict, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        project_root = job.get("project_root")
        if not isinstance(project_root, str):
            raise AdapterError("missing_project_root")
        path = Path(project_root) / path
    return path


def to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = MIME_BY_SUFFIX.get(suffix)
    if mime is None:
        raise AdapterError("unsupported_media_type")
    data = path.read_bytes()
    if mime.startswith("image/") and (len(data) > MAX_REF_BYTES or _long_side_exceeds(data, SHRINK_LONG_SIDE)):
        data, mime = _shrink_image(data, mime)
    if len(data) > MAX_REF_BYTES:
        raise AdapterError("reference_too_large")
    return f"data:{mime};base64," + _b64(data)


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")


def _long_side_exceeds(data: bytes, limit: int) -> bool:
    try:
        from PIL import Image

        with Image.open(__import__("io").BytesIO(data)) as im:
            return max(im.size) > limit
    except Exception:
        return False


def _shrink_image(data: bytes, mime: str) -> tuple[bytes, str]:
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        im.load()
        if max(im.size) > SHRINK_LONG_SIDE:
            scale = SHRINK_LONG_SIDE / max(im.size)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
        out = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P") and mime == "image/png":
            im.save(out, format="PNG", optimize=True)
            return out.getvalue(), "image/png"
        im.convert("RGB").save(out, format="JPEG", quality=90)
        return out.getvalue(), "image/jpeg"


def api(base: str, token: str, path: str, body: dict | None = None) -> dict:
    headers = {"authorization": token}
    data = None
    if body is not None:
        headers["content-type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urlrequest.Request(base + path, data=data, headers=headers, method="POST" if body is not None else "GET")
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
    try:
        with opener.open(req, timeout=API_TIMEOUT) as resp:
            envelope = json.load(resp)
    except HTTPError as exc:
        raise AdapterError("api_http_error", category="provider_error", retryable=exc.code >= 500, http_status=exc.code) from exc
    except URLError as exc:
        raise AdapterError("api_unreachable", category="network", retryable=True) from exc
    if not isinstance(envelope, dict) or envelope.get("code") != "Success":
        raise AdapterError("api_rejected", category="provider_error", retryable=False)
    return envelope.get("data") or {}


def write_handle(handle_path: str | None, task_id: str) -> None:
    if not isinstance(handle_path, str) or not handle_path:
        return
    try:
        target = Path(handle_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".handle-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"provider_job_id": task_id}, handle)
        os.replace(tmp, target)
    except OSError as exc:
        print(f"handle write failed (non-fatal): {exc}", file=sys.stderr)


def poll_result(base: str, token: str, task_id: str) -> dict:
    deadline = time.time() + POLL_TIMEOUT
    while True:
        data = api(base, token, f"/api/v1/comfyui/comfyui_workflow/result/{task_id}")
        status = str(data.get("status") or "")
        if status == "SUCCESS":
            return data
        if status in ("FAILED", "ERROR", "CANCELLED"):
            raise AdapterError(f"provider_{status.lower()}", category="provider_error", retryable=False)
        if time.time() >= deadline:
            raise AdapterError("provider_timeout", category="timeout", retryable=True)
        time.sleep(POLL_INTERVAL)


def pick_video_url(data: dict) -> str:
    results = data.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict) and item.get("type") == "video" and isinstance(item.get("url"), str):
                return item["url"]
        for item in results:
            if isinstance(item, dict):
                for key in ("url", "video_url", "file_url"):
                    if isinstance(item.get(key), str) and item[key].startswith("http"):
                        return item[key]
    raise AdapterError("no_video_result", category="provider_error", retryable=True)


def download(url: str, destination: Path) -> None:
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
    tmp = destination.with_suffix(destination.suffix + ".part")
    try:
        with opener.open(url, timeout=DOWNLOAD_TIMEOUT) as resp, tmp.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
        if tmp.stat().st_size == 0:
            raise AdapterError("empty_download", category="provider_error", retryable=True)
        os.replace(tmp, destination)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def route_video(duration: int, has_first_last: bool, ref_count: int) -> str:
    if has_first_last:
        if 4 <= duration <= 15:
            return SPEC_B99_002
        raise AdapterError("unsupported_duration")
    if ref_count > 0:
        if duration == 12 and ref_count <= 3:
            return SPEC_B99_003_12S
        if duration == 15 and ref_count <= 9:
            return SPEC_V5_15S
        if 1 <= duration <= 10 and ref_count <= 9:
            return SPEC_V5
        raise AdapterError("unsupported_duration")
    if 4 <= duration <= 15:
        return SPEC_B99_001
    if 1 <= duration <= 10:
        return SPEC_NO_PIC
    raise AdapterError("unsupported_duration")


def resolution_payload(spec: str, ratio: str, quality: str) -> str:
    portrait = "竖" if ratio == "9:16" else "横" if ratio == "16:9" else None
    if spec == SPEC_B99_003_12S:
        return {"9:16": "736p竖", "16:9": "736p横", "1:1": "736p(1:1)"}[ratio]
    if spec in (SPEC_V5, SPEC_NO_PIC):
        if quality == "1080p":
            if portrait:
                return f"1080p{portrait}"
        elif portrait:
            return f"768p{portrait}"
        raise AdapterError("unsupported_resolution")
    if spec == SPEC_AUDIO:
        if quality == "1080p" and portrait:
            return f"1080p{portrait}"
        if quality == "480p" and portrait:
            return f"480p{portrait}"
        if portrait:
            return f"768p{portrait}"
        raise AdapterError("unsupported_resolution")
    # b99_001 / b99_002 / v5_15s：仅 736p/768p 竖横
    if portrait is None:
        raise AdapterError("unsupported_resolution")
    return ("736p" if spec in (SPEC_B99_001, SPEC_B99_002) else "768p") + portrait


def build_video_payload(job: dict, profile: str) -> dict:
    prompt = job.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise AdapterError("missing_prompt")
    parameters = job.get("parameters") or {}
    duration = parameters.get("duration")
    duration = int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else 5
    ratio = str(parameters.get("ratio") or "9:16")
    quality = str(parameters.get("resolution") or "768p")

    bindings = job.get("reference_bindings") or []
    if not bindings and job.get("references"):
        bindings = [{"path": path, "role": "reference_image"} for path in job["references"]]

    images: list[tuple[str, Path]] = []
    audios: list[tuple[str, Path]] = []
    has_first_last = False
    for binding in bindings:
        if not isinstance(binding, dict):
            raise AdapterError("invalid_binding")
        role = str(binding.get("role") or "")
        raw = binding.get("path")
        if not isinstance(raw, str) or not raw:
            raise AdapterError("invalid_binding")
        path = resolve_path(job, raw)
        if not path.is_file():
            raise AdapterError("reference_missing")
        if role in ("first_frame", "last_frame"):
            has_first_last = True
            images.append((role, path))
        elif role == "reference_image":
            images.append((role, path))
        elif role == "reference_audio":
            audios.append((role, path))
        else:
            raise AdapterError("unsupported_role")

    payload: dict = {"prompt": prompt}
    if profile == "audio":
        image = next((p for r, p in images if r in ("reference_image", "first_frame")), None)
        audio = next((p for r, p in audios if r == "reference_audio"), None)
        if image is None:
            raise AdapterError("missing_reference_image")
        if audio is None:
            raise AdapterError("missing_reference_audio")
        audio_duration = parameters.get("duration")
        audio_duration = int(audio_duration) if isinstance(audio_duration, (int, float)) and not isinstance(audio_duration, bool) else 5
        if not 1 <= audio_duration <= 15:
            raise AdapterError("unsupported_duration")
        payload["ref_image_0"] = to_data_url(image)
        payload["ref_audio_0"] = to_data_url(audio)
        payload["audio_duration"] = audio_duration
        payload["resolution"] = resolution_payload(SPEC_AUDIO, ratio, quality)
        return {"spec": SPEC_AUDIO, "payload": payload}

    spec = route_video(duration, has_first_last, len(images))
    payload["duration"] = duration
    payload["resolution"] = resolution_payload(spec, ratio, quality)
    for index, (role, path) in enumerate([entry for entry in images if entry[0] == "reference_image"]):
        payload[f"ref_image_{index}"] = to_data_url(path)
    for role in ("first_frame", "last_frame"):
        entry = next((p for r, p in images if r == role), None)
        if entry is not None:
            payload[role] = to_data_url(entry)
    return {"spec": spec, "payload": payload}


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoDL.Art H3 video adapter")
    parser.add_argument("--profile", choices=["video", "audio"], default="video")
    parser.add_argument("--selftest", action="store_true", help="从 stdin 构建请求体并打印（不联网）")
    args = parser.parse_args()

    profile = "autodl-h3" if args.profile == "video" else "autodl-h3-audio"
    job = json.load(sys.stdin.buffer)

    try:
        if job.get("modality") != "video":
            raise AdapterError("unsupported_modality")
        targets = job.get("outputs") or []
        if len(targets) != 1 or Path(str(targets[0])).suffix.lower() != ".mp4":
            raise AdapterError("unsupported_outputs")
        target = str(targets[0])

        built = build_video_payload(job, args.profile)
        spec, payload = built["spec"], built["payload"]

        if args.selftest:
            json.dump({"spec": spec, "payload_keys": sorted(payload.keys()), "payload": {k: (v[:60] + "..." if isinstance(v, str) and len(v) > 60 else v) for k, v in payload.items()}}, sys.stdout, ensure_ascii=False, indent=2)
            return 0

        base = os.environ.get("AUTODL_BASE_URL", "https://autodl.art").rstrip("/")
        token = os.environ.get("AUTODL_API_KEY")
        if not token:
            raise AdapterError("missing_api_key")

        collect_id = job.get("collect_provider_job_id")
        if isinstance(collect_id, str) and collect_id:
            task_id = collect_id
        else:
            dry = os.environ.get("AUTODL_DRY_RUN", "") not in ("", "0", "false", "False")
            allowed = os.environ.get("AUTODL_ALLOW_SUBMIT") == "1"
            if dry or not allowed:
                print(json.dumps({"workflow": spec, "payload_preview": {k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v) for k, v in payload.items()}}, ensure_ascii=False), file=sys.stderr)
                raise AdapterError("submit_disabled")
            data = api(base, token, f"/api/v1/comfyui/comfyui_workflow/{spec}", payload)
            task_id = str(data.get("task_id") or "")
            if not task_id:
                raise AdapterError("missing_task_id", category="provider_error", retryable=True)
            write_handle(job.get("handle_path"), task_id)
            print(f"submitted {spec} task_id={task_id}", file=sys.stderr)

        result = poll_result(base, token, task_id)
        url = pick_video_url(result)

        output_root_raw = job.get("output_root")
        if not isinstance(output_root_raw, str):
            raise AdapterError("missing_output_root")
        output_root = Path(output_root_raw)
        if not output_root.is_absolute() or not output_root.is_dir() or output_root.is_symlink():
            raise AdapterError("invalid_output_root")
        destination = output_root / "output-0.mp4"
        download(url, destination)

        json.dump({"outputs": [{"target": target, "source": str(destination)}], "provider_job_id": task_id}, sys.stdout)
        return 0
    except AdapterError as exc:
        return emit_error(exc, profile)
    except Exception as exc:  # 兜底：不外泄敏感信息
        print(f"adapter internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return emit_error(AdapterError("adapter_internal_error", category="adapter", retryable=True), profile)


if __name__ == "__main__":
    raise SystemExit(main())
