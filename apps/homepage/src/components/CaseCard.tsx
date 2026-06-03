import { ArrowUpRight } from "lucide-react";
import type { CaseStudy } from "../content";

type CaseCardProps = {
  item: CaseStudy;
  onOpenCase: (slug: string) => void;
};

export function CaseCard({ item, onOpenCase }: CaseCardProps) {
  return (
    <article className={`case-card case-card-${item.accent}`}>
      <div className="case-stage">
        <img src={item.image} alt={`${item.title} demo`} className="h-full w-full object-cover" />
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,17,31,0.04),rgba(8,17,31,0.72))]" />
        <div className="absolute left-4 top-4 rounded-lg border border-white/30 bg-white/75 px-3 py-1 text-xs font-semibold text-ink shadow-sm backdrop-blur-xl">
          {item.categoryLabel}
        </div>
        <div className="absolute bottom-4 left-4 right-4 rounded-lg border border-white/24 bg-white/90 p-3 shadow-sm backdrop-blur-xl">
          <p className="text-sm font-semibold text-ink">{item.title}</p>
          <p className="mt-1 text-xs text-slate-500">{item.route}</p>
        </div>
      </div>
      <div className="p-5">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-cyanline">
          {item.eyebrow}
        </p>
        <p className="text-sm leading-7 text-slate-600">{item.description}</p>
        <div className="mt-5 flex flex-wrap gap-2">
          {item.features.map((feature) => (
            <span key={feature} className="rounded-lg bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {feature}
            </span>
          ))}
        </div>
        <button
          type="button"
          className="focus-ring mt-5 inline-flex cursor-pointer items-center gap-2 rounded-lg text-sm font-semibold text-cyanline transition hover:text-ink"
          onClick={() => onOpenCase(item.slug)}
        >
          查看案例详情
          <ArrowUpRight className="h-4 w-4" />
        </button>
      </div>
    </article>
  );
}
