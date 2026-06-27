# Speech Models

This directory collects speech-related model deployment, weight download, and verification for OpenTalking. Speech models are split into two groups:

- [Speech Recognition Models](stt.md): convert microphone or uploaded audio into text; locally deployable models include [SenseVoice](stt/sensevoice.md).
- [Speech Generation Models](tts.md): convert LLM text output into audio; locally deployable models include [CosyVoice](tts/cosyvoice.md), [IndexTTS](tts/indextts.md), and [Qwen3-TTS](tts/qwen3-tts.md).

The LLM decides what to say and is not classified as a speech model; this section covers input recognition and output synthesis.
