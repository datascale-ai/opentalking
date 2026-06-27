/**
 * 浏览器端简单 VAD（能量阈值）。可在 `.env` / Vite 中覆盖：
 * VITE_VOICE_SPEECH_RMS — 判定「开始说话」的能量下限（约 0.01–0.06）
 * VITE_VOICE_SILENCE_RMS — 判定「静音」的能量上限（应略小于 SPEECH）
 * VITE_VOICE_SILENCE_MS — 持续低于 SILENCE 多久算一句结束
 * VITE_VOICE_MIN_SEGMENT_MS — 最短一句时长，避免杂音触发过短片段
 * VITE_VOICE_ATTACK_FRAMES — 连续多少帧超过 SPEECH 才开始录音（抗噪）
 * VITE_VOICE_SOFT_START_RMS — 低能量起段阈值（轻声首字保护）
 * VITE_VOICE_SOFT_START_FRAMES — 连续多少帧超过 SOFT_START 才触发起段
 * VITE_VOICE_BARGE_SPEECH_RMS — 数字人播报时「抢话」阈值，应高于 SPEECH，减轻回声误触
 * VITE_VOICE_BARGE_ATTACK_FRAMES — 播报时抢话需连续超过阈值的帧数（更严）
 */

function num(envVal: string | undefined, fallback: number): number {
  const n = Number(envVal);
  return Number.isFinite(n) ? n : fallback;
}

export type VoiceVadConfig = {
  speechRms: number;
  silenceRms: number;
  silenceMs: number;
  minSegmentMs: number;
  attackFrames: number;
  softStartRms: number;
  softStartFrames: number;
  bargeInSpeechRms: number;
  bargeInAttackFrames: number;
};

export function getVoiceVadConfig(): VoiceVadConfig {
  const speech = num(import.meta.env.VITE_VOICE_SPEECH_RMS, 0.022);
  const silence = num(import.meta.env.VITE_VOICE_SILENCE_RMS, 0.014);
  const softStart = num(import.meta.env.VITE_VOICE_SOFT_START_RMS, 0.016);
  const barge = num(import.meta.env.VITE_VOICE_BARGE_SPEECH_RMS, 0.045);
  const speechClamped = Math.min(0.2, Math.max(0.005, speech));
  const softStartClamped = Math.min(0.2, Math.max(0.004, softStart));
  const bargeClamped = Math.min(0.2, Math.max(0.015, barge));
  return {
    speechRms: speechClamped,
    silenceRms: Math.min(0.2, Math.max(0.002, silence)),
    silenceMs: Math.min(5000, Math.max(200, num(import.meta.env.VITE_VOICE_SILENCE_MS, 800))),
    minSegmentMs: Math.min(10000, Math.max(200, num(import.meta.env.VITE_VOICE_MIN_SEGMENT_MS, 450))),
    attackFrames: Math.min(30, Math.max(2, Math.floor(num(import.meta.env.VITE_VOICE_ATTACK_FRAMES, 2)))),
    softStartRms: Math.min(speechClamped, softStartClamped),
    softStartFrames: Math.min(
      45,
      Math.max(4, Math.floor(num(import.meta.env.VITE_VOICE_SOFT_START_FRAMES, 12))),
    ),
    bargeInSpeechRms: Math.max(bargeClamped, speechClamped * 1.25),
    bargeInAttackFrames: Math.min(40, Math.max(3, Math.floor(num(import.meta.env.VITE_VOICE_BARGE_ATTACK_FRAMES, 8)))),
  };
}
