# 更新日志

本文档记录 OpenTalking 项目的能力进展、主要能力规划和重要兼容性变化。

## 2026 年 5 月

### 2026/05/17

- **QuickTalk 接入**
  QuickTalk / Wav2Lip 新增更便捷使用方式，可通过 OpenTalking 直接拉起推理进行数字人生成。

### 2026/05/15

- **MuseTalk WebRTC 播放优化**
  增加 MuseTalk 媒体 backpressure，提升 WebRTC 播放稳定性。

### 2026/05/14

- **MuseTalk 适配**
  增加 MuseTalk talking-head 路线，用于轻量全帧数字人验证。

### 2026/05/13

- **模型 backend 解耦**
  将 `mock`、`local`、`direct_ws`、`omnirt` 从架构上拆开，支持不同模型按部署形态选择后端。

### 2026/05/08

- **QuickTalk 本地适配器**
  增加 QuickTalk model adapter、配置说明和异步初始化能力。

* * *

## 2026 年 4 月

### 2026/04/16

- **实时数字人基础体验**
  建立 Web 控制台、LLM 对话、TTS、字幕事件和 WebRTC 音视频播放的主链路。

* * *

## 兼容性说明

- 当前更新日志以能力进展为主，尚未按正式 release version 组织。
- 模型接入、推理后端和配置项仍在快速迭代；升级前建议同时查看“模型支持”和“使用指南”。
- Benchmark 数据需要记录硬件、模型、backend、启动状态和输入素材，不能跨环境直接比较。
