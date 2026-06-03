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
