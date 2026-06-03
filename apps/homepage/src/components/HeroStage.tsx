import { Activity, AudioLines, Bot, Cpu, Radio, Sparkles } from "lucide-react";
import { liveSignals } from "../content";

const heroVideoUrl = "https://github.com/user-attachments/assets/a3abce76-12c0-4b8b-844f-bbc5c3227dc7";

export function HeroStage() {
  return (
    <div className="hero-stage group">
      <div className="flex items-center justify-between border-b border-white/60 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-mintline" />
        </div>
        <div className="code-font rounded-md bg-white/70 px-2.5 py-1 text-xs text-slate-500 shadow-sm">
          live-session: 24fps
        </div>
      </div>
      <div className="relative grid gap-4 p-4 md:grid-cols-[0.82fr_1fr]">
        <div className="absolute inset-4 rounded-lg bg-[linear-gradient(115deg,rgba(99,102,241,0.14),rgba(251,113,133,0.11),rgba(245,158,11,0.10))]" />
        <div className="relative mx-auto aspect-[9/16] w-full max-w-[320px] overflow-hidden rounded-lg bg-ink shadow-[0_24px_80px_rgba(8,17,31,0.26)]">
          <video
            className="h-full w-full object-cover opacity-95 transition duration-700 group-hover:scale-[1.018]"
            src={heroVideoUrl}
            autoPlay
            muted
            loop
            playsInline
            controls={false}
          />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,17,31,0.04),rgba(8,17,31,0.50))]" />
          <div className="absolute left-4 top-4 flex items-center gap-2 rounded-lg bg-white/10 px-3 py-2 text-xs font-medium text-white shadow-sm backdrop-blur-xl">
            <Activity className="h-4 w-4 text-mintline" />
            实时录制 Demo
          </div>
          <div className="absolute right-4 top-4 rounded-lg bg-ink/70 px-3 py-2 text-xs font-semibold text-indigo-100 shadow-sm backdrop-blur-xl">
            竖屏素材
          </div>
          <span className="scan-line" />
        </div>

        <div className="relative grid gap-3">
          <div className="rounded-lg border border-white/60 bg-white/75 p-4 shadow-sm backdrop-blur-xl">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-ink">产品链路</p>
              <Sparkles className="h-4 w-4 text-ember" />
            </div>
            <div className="mt-4 grid gap-3">
              {[
                { icon: Bot, label: "LLM大脑", value: "Qwen / DeepSeek / GPT" },
                { icon: AudioLines, label: "声音与字幕", value: "TTS / STT / 多音色 / 音色克隆" },
                { icon: Cpu, label: "数字人驱动", value: "QuickTalk / Wav2Lip / FlashTalk" },
                { icon: Radio, label: "实时播放", value: "WebRTC audio/video" },
              ].map((item) => (
                <div key={item.label} className="pipeline-row">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-cyanline shadow-sm">
                    <item.icon className="h-4 w-4" />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-ink">{item.label}</p>
                    <p className="code-font mt-1 text-xs text-slate-500">{item.value}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {liveSignals.map((signal) => (
              <div key={signal} className="signal-card">
                <span className="mb-3 block h-1.5 w-10 rounded-full bg-gradient-to-r from-cyanline to-mintline" />
                <p className="text-sm font-semibold text-ink">{signal}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
