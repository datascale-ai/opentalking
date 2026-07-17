# 语音模型

本目录汇总 OpenTalking 中与语音相关的模型部署、权重下载和验证。语音模型分为两类：

- [语音识别模型](stt.md)：把麦克风或上传音频转为文本；可本地部署的模型见 [SenseVoice](stt/sensevoice.md)。
- [语音生成模型](tts.md)：把 LLM 输出文本转为音频；可本地部署的模型见 [CosyVoice](tts/cosyvoice.md)、[IndexTTS](tts/indextts.md) 和 [Qwen3-TTS](tts/qwen3-tts.md)。

LLM 负责决定“说什么”，不属于语音模型；语音模型只覆盖输入识别与输出合成。
