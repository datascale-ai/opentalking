import {
  Activity,
  AudioLines,
  Bot,
  Cpu,
  DatabaseZap,
  Mic2,
  Radio,
  Sparkles,
  UserRoundCog,
  Volume2,
} from "lucide-react";
import type { SiteContent } from "../locales";

const heroVideoUrl = "https://github.com/user-attachments/assets/44bbf1d9-75b1-4b0a-9704-c7f81c39446e";

const highlightIcons = [UserRoundCog, Volume2, DatabaseZap, Mic2];
const pipelineIcons = [Bot, AudioLines, Cpu, Radio];

type HeroStageProps = {
  copy: SiteContent["heroStage"];
};

export function HeroStage({ copy }: HeroStageProps) {
  return (
    <div className="hero-stage group">
      <div className="flex items-center justify-between border-b border-white/60 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-mintline" />
        </div>
        <div className="code-font rounded-md bg-white/70 px-2.5 py-1 text-xs text-slate-500 shadow-sm">
          {copy.sessionLabel}
        </div>
      </div>
      <div className="relative grid gap-4 p-4 md:grid-cols-[0.82fr_1fr]">
        <div className="absolute inset-4 rounded-lg bg-[linear-gradient(115deg,rgba(99,102,241,0.14),rgba(251,113,133,0.11),rgba(245,158,11,0.10))]" />
        <div className="relative mx-auto aspect-[9/16] w-full max-w-[320px] overflow-hidden rounded-lg bg-ink shadow-[0_24px_80px_rgba(8,17,31,0.26)] md:translate-x-2 md:translate-y-1.5">
          <video
            className="h-full w-full object-cover transition duration-700 group-hover:scale-[1.018]"
            src={heroVideoUrl}
            autoPlay
            muted
            loop
            playsInline
            controls={false}
          />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,17,31,0),rgba(8,17,31,0.08))]" />
          <div className="absolute left-4 top-4 flex items-center gap-2 rounded-lg bg-white/10 px-3 py-2 text-xs font-medium text-white shadow-sm backdrop-blur-xl">
            <Activity className="h-4 w-4 text-mintline" />
            {copy.recordingLabel}
          </div>
          <span className="scan-line" />
        </div>

        <div className="relative grid gap-2">
          <div className="rounded-lg border border-white/60 bg-white/75 p-4 shadow-sm backdrop-blur-xl">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-ink">{copy.productPanelTitle}</p>
              <Sparkles className="h-4 w-4 text-ember" />
            </div>
            <div className="mt-4 grid gap-3">
              {copy.pipelineItems.map((item, index) => {
                const Icon = pipelineIcons[index] ?? Bot;

                return (
                <div key={item.label} className="pipeline-row">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-cyanline shadow-sm">
                    <Icon className="h-4 w-4" />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-ink">{item.label}</p>
                    <p className="code-font mt-1 text-xs text-slate-500">{item.value}</p>
                  </div>
                </div>
                );
              })}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 -mt-1.4">
            {copy.highlights.map((signal, index) => {
              const Icon = highlightIcons[index] ?? Sparkles;

              return (
              <div key={signal.title} className="signal-card">
                <span className="signal-icon">
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-ink">{signal.title}</p>
                  <p className="code-font mt-0.5 truncate text-[10px] font-semibold uppercase tracking-normal text-indigo-500">
                    {signal.meta}
                  </p>
                </div>
              </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
