import type { CreateVideoCreationJobInput, VideoCreationAudioSource } from "./api";
import { DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG } from "../components/VideoCreationWorkspace";

const voiceCloneSource: VideoCreationAudioSource = "voice_clone";
const videoCreationDefaultMouthOpen: 0.9 = DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG.mouth_open_multiplier;
const videoCreationDefaultAnimationRegion: "lip" = DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG.animation_region;
const videoCreationDefaultNormalizeLip: false = DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG.flag_normalize_lip;

const fasterLivePortraitVoiceCloneJob: CreateVideoCreationJobInput = {
  model: "fasterliveportrait",
  avatarId: "anchor",
  audioSource: voiceCloneSource,
  text: "这是一个复刻音色驱动的视频创作任务。",
  ttsProvider: "dashscope",
  ttsModel: "cosyvoice-v2",
  voice: "voice-clone-1",
  fasterliveportraitConfig: {
    mouth_open_multiplier: 2.0,
    animation_region: "all",
    flag_pasteback: false,
  },
};

void videoCreationDefaultMouthOpen;
void videoCreationDefaultAnimationRegion;
void videoCreationDefaultNormalizeLip;
void fasterLivePortraitVoiceCloneJob;


const indexttsVideoCreationJob: CreateVideoCreationJobInput = {
  model: "quicktalk",
  avatarId: "anchor",
  audioSource: "tts_text",
  text: "这是一个 IndexTTS 情绪控制测试。",
  ttsProvider: "indextts",
  ttsModel: "IndexTeam/IndexTTS-2",
  voice: "indextts-clear-cn",
  indexttsConfig: {
    emotion_mode: "text",
    emo_alpha: 0.6,
    emo_text: "开心、自然",
    use_random: false,
    interval_silence_ms: 0,
  },
};

void indexttsVideoCreationJob;

const indexttsVideoCreationWithEmotionAudio: CreateVideoCreationJobInput = {
  model: "quicktalk",
  avatarId: "anchor",
  audioSource: "tts_text",
  text: "这是一个 IndexTTS 情绪参考音频测试。",
  ttsProvider: "indextts",
  ttsModel: "IndexTeam/IndexTTS-2",
  voice: "indextts-clear-cn",
  indexttsConfig: {
    emotion_mode: "audio",
    emo_alpha: 0.9,
  },
  indexttsEmotionAudioFile: new File(["RIFF"], "emotion.wav", { type: "audio/wav" }),
};

void indexttsVideoCreationWithEmotionAudio;

const indexTtsVideoCreationVoiceClone: CreateVideoCreationJobInput = {
  model: "quicktalk",
  avatarId: "anchor",
  audioSource: "voice_clone",
  text: "这是一个 IndexTTS 复刻音色驱动测试。",
  ttsProvider: "indextts",
  ttsModel: "IndexTeam/IndexTTS-2",
  voice: "indextts-local-voice",
  indexttsConfig: {
    emotion_mode: "vector",
    emo_alpha: 1,
    emo_vector: [0, 1, 0, 0, 0, 0, 0, 0],
    use_random: true,
    interval_silence_ms: 40,
  },
};

void indexTtsVideoCreationVoiceClone;


const duoDialogPerRoleTtsJob: CreateVideoCreationJobInput = {
  model: "quicktalk",
  avatarId: "duo-anchor",
  audioSource: "duo_dialog",
  duoDialog: {
    lines: [
      { id: "line-1", role: "left", text: "左侧开场" },
      { id: "line-2", role: "right", text: "右侧回应" },
    ],
    speakers: {
      left: { tts_provider: "edge", voice: "zh-CN-XiaoxiaoNeural" },
      right: { tts_provider: "xiaomi_mimo", tts_model: "mimo-v2.5-tts", voice: "冰糖" },
    },
    gap_ms: 120,
  },
};

void duoDialogPerRoleTtsJob;
