# Wav2Lip 架构 V2 迁移说明（OpenTalking）

!!! abstract "TL;DR"
    2026-05-09 的 PR 说明：把 Wav2Lip 迁到 architecture-v2，OpenTalking 这边的改动。新边界：OpenTalking 负责形象资产、会话编排和音频驱动；OmniRT 负责 Wav2Lip 推理和帧产出。

!!! note "归档说明"
    本文针对一次具体 PR，时点性强。Wav2Lip 的最新接入方式请看 [配置 § 推理服务](../user-guide/configuration.md#2)。

日期：2026-05-09

本文档用于 PR 展示，记录本次在 OpenTalking 侧为 Wav2Lip 迁移到
architecture-v2 所做的改动。迁移后的职责边界是：OpenTalking 负责形象资产、
会话配置、前端/API 和 WebRTC 播放；OmniRT 负责 Wav2Lip 推理服务和后处理。

## 改动摘要

- 保持“形象资产”和“驱动模型”解耦：用户选择的 avatar 只提供参考图和口型
  metadata，具体由哪个模型驱动由会话里的 model 决定。
- 扩展 avatar manifest，为内置资产和自定义资产记录 Wav2Lip 所需的嘴部
  metadata，包括 mouth polygon、mouth center/radius、face box、source image
  hash。
- 新增 `opentalking/avatar/mouth_metadata.py`，在创建或更新 avatar 参考图时，
  使用 MediaPipe 自动检测嘴部 landmark 并写入 manifest。
- 自定义形象上传会创建新的 avatar 资产目录，写入 `preview.png`、
  `reference.png`，并为 Wav2Lip 资产同步写入首帧。
- 大图只在超过实时推理上限时等比例缩小，小图不会被强行放大，避免改变已有
  内置资产的画面比例。

## 运行时对接

- Wav2Lip 会话会把 `wav2lip_postprocess_mode`、`mouth_metadata` 和视频尺寸
  配置透传给 OmniRT 的 FlashTalk-compatible WebSocket。
- WebSocket init payload 新增 width、height、fps、postprocess mode 状态和
  mouth metadata。
- `source_image_hash` 会在会话启动前重新校验，避免用户换图后继续使用旧 polygon。
- reference frame 会按目标视频尺寸处理，保证初始 WebRTC 帧和后续生成帧尺寸一致。

## 安全和兼容性

- 上传图片限制为 10MB，并使用固定目标文件名写入，不使用用户原始文件名作为磁盘路径。
- `avatar_id` 和 `base_avatar_id` 进入磁盘访问前都会做 `resolve()` 和
  `relative_to()` 校验，防止路径穿越。
- 如果 MediaPipe 不可用或检测失败，会清理不可用 metadata，推理侧会退回基础逻辑。

## 测试覆盖

- 增加 Wav2Lip WebSocket init payload 测试，覆盖 enhanced flag、视频配置和
  mouth metadata 透传。
- 增加 reference frame resize 测试。
- 扩展 custom avatar 测试，覆盖资产创建、缩略图/参考图输出、图片大小限制和嘴部
  metadata 更新。

## PR 关注点

- 本 PR 只在 OpenTalking 侧维护资产与会话协议，不在 OpenTalking 内部承载
  Wav2Lip 推理。
- Wav2Lip 的增强融合和模型加载在 OmniRT PR 中实现；两个 PR 需要配套部署。
