import { CheckCircle2 } from "lucide-react";
import type { CSSProperties } from "react";
import type { DeploymentRoute as DeploymentRouteType } from "../content";

type DeploymentRouteProps = {
  route: DeploymentRouteType;
  index: number;
};

export function DeploymentRoute({ route, index }: DeploymentRouteProps) {
  const accents = ["#6366f1", "#fb7185", "#f59e0b"];

  return (
    <article className="deployment-card" style={{ "--route-accent": accents[index] } as CSSProperties}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <span className="rounded-lg bg-cyanline/10 px-3 py-1 text-xs font-semibold text-cyanline">
            {route.badge}
          </span>
          <h3 className="mt-4 text-xl font-semibold tracking-normal text-ink">{route.name}</h3>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-ink text-sm font-semibold text-white">
          {index + 1}
        </span>
      </div>
      <p className="mt-4 text-sm leading-7 text-slate-600">{route.description}</p>
      <div className="mt-5 rounded-lg bg-indigo-50/80 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-indigo-500">预期效果</p>
        <p className="mt-2 text-sm font-semibold leading-6 text-ink">{route.outcome}</p>
      </div>
      <div className="mt-5 grid gap-3 text-sm">
        <p className="flex gap-2 text-slate-700">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mintline" />
          <span>
            <strong className="text-ink">模型：</strong>
            {route.models}
          </span>
        </p>
        <p className="flex gap-2 text-slate-700">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mintline" />
          <span>
            <strong className="text-ink">适合：</strong>
            {route.bestFor}
          </span>
        </p>
      </div>
    </article>
  );
}
