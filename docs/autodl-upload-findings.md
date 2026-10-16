# AutoDL.Art 媒体上传机制 · 验证记录（2026-10-12）

## 最终结论（用户拍板 + AutoMN 生产验证）

**不需要上传、不需要登录：媒体参数直接以 base64 data URL 内联提交**。
依据：AutoMN（DaBaoAgent/AutoMN）production 实测流程——`provider-autodl-h3/src/provider.ts`
将参考图/音频转为 `data:image/png;base64,...` 直接塞进提交载荷（该链路已生产用过多图工作流，
实测出片 736x1280/12.25s）。约束：单张参考 ≤6MB（`maxReferenceBytes: 6291456`），建议最长边
≤1280px（超限自动缩图）；每类工作流的参考图数量上限：b99_003_12s ≤3、lightx2v_v5 系 ≤9、
对口型 1 图+1 音频。

`manju` 的 `adapters/autodl_h3_adapter.py` 已按此模式实现（路由与参数映射照 AutoMN
`hypit.runtime.json` 的 prefer 清单）。用户 2026-10-12 明确指示：不搞登录，纯 API 路线。

## 附：网页上传通道记录（已不用，备查）

媒体参数文档形态是"URL"；网页端存在上传通道但**只认网页登录态**（ComfyUI API 令牌实测被拒
`AuthorizeFailed`，新旧两个令牌都不行）。前端 JS（`/assets/cg-upload.5ac8d0e0.js`）解出的协议：
`POST /api/v1/file/before_upload {md5,file_size}` → `{token,host,quickly_upload}` → 分块 PUT
`{host}/api/v1/file`（10MB/块，头 `FileToken`）→ 合并 POST。上传成功后的文件以
`https://autodl.art/api/v1/file/{id}` 形式对外公开。此路不再需要（base64 内联已覆盖需求）。

## 上传协议（从前端 JS 逆向）

1. `POST /api/v1/file/before_upload`，body `{"md5": "<文件MD5hex>", "file_size": <字节>}`
   → `{"data": {"token": ..., "host": ..., "quickly_upload": bool}}`
   - `quickly_upload=true` 时秒传（服务端已有同 md5 文件，跳过上传）。
2. 分块 PUT 到 `{host}/api/v1/file`（WebUploader，chunkSize=10MB，`method: PUT`）
   - 请求头：`FileToken: <token>`；表单：`md5 / chunk / chunks / chunk_size`。
3. 全部分块完成后 `POST {host}/api/v1/file`（合并），body `{"md5":..., "total_size":..., "chunks":...}`，头 `FileToken`。
   → 响应 `data.next_seq`（断点续传用）。

## 待用户决策的三种落地方式

- **A（推荐）**：Playwright 打开 autodl.art，用户扫码登录一次；脚本持久化会话自动上传拿 URL。会话过期时需偶尔重登。
- **B**：第三方公开图床（如 sm.ms）自动上传（零登录全自动；参考图将托管在第三方公网；需验证其 URL 可被 AutoDL 服务器抓取）。
- **C**：暂缓——先用纯文生视频工作流（`minimax_h3_lightx2v_no_pic` / `z0901`，无媒体参数）跑通付费链路。

## 其他已核实事实

- 工作流目录（2026-10-12，共 18 个）新增 `minimax_h3_image_audio_to_video_v2(_15s)`、`lightx2v_v5(_15s)`、`zm_u24/zm_u08`（多图多音频）等。
- `minimax_h3_b99_003_12s`：prompt（必填，≤20000 字符）、ref_image_0..8（仅 0 必填，URL）、duration 1-12（默认 5）、resolution `736p竖 / 736p横 / 736p(1:1)`（默认竖）。
- 计费（billing_config 实测）：480p 40/错峰30，768p 70/50，1088p 70/50，1440p 80/60（单位以平台扣费为准）。
- 结果 URL 有效期短，SUCCESS 后须立即下载（客户端已实现）。
- 文档 https://autodl.art/docs/comfyui_api 不含任何上传/文件接口说明。

## 对 adapter 的影响

`autodl_h3_adapter.py` 的 `AUTODL_MEDIA_MODE` 设计：
- `passthrough`：绑定里已是 http(s) URL → 直接透传；
- `hosted`：本地文件经"发布器"换成 URL（A/B 方案实现为 uploader 脚本，adapter 调用）；
- 无法解析时 fail closed（不发任务、不产生费用）。
