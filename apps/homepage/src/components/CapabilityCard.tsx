import { Captions, PlugZap, RadioTower, UserRound } from "lucide-react";
import type { Capability } from "../content";

const iconMap = {
  radio: RadioTower,
  user: UserRound,
  captions: Captions,
  plug: PlugZap,
};

type CapabilityCardProps = {
  capability: Capability;
};

export function CapabilityCard({ capability }: CapabilityCardProps) {
  const Icon = iconMap[capability.icon];

  return (
    <article className="panel-card group">
      <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-cyanline/10 text-cyanline transition group-hover:bg-cyanline group-hover:text-white">
        <Icon className="h-5 w-5" />
      </div>
      <p className="mt-6 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
        {capability.meta}
      </p>
      <h3 className="mt-3 text-xl font-semibold tracking-normal text-ink">
        {capability.title}
      </h3>
      <p className="mt-3 text-sm leading-7 text-slate-600">{capability.description}</p>
    </article>
  );
}
