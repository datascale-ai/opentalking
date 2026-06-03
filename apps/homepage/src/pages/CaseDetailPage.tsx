import { ArrowLeft, CheckCircle2, ExternalLink, PlayCircle } from "lucide-react";
import { CaseCard } from "../components/CaseCard";
import { ArchitectureFlow } from "../components/ArchitectureFlow";
import type { CaseStudy } from "../content";

type CaseDetailPageProps = {
  item: CaseStudy;
  relatedCases: CaseStudy[];
  onBack: () => void;
  onOpenCase: (slug: string) => void;
};

export function CaseDetailPage({
  item,
  relatedCases,
  onBack,
  onOpenCase,
}: CaseDetailPageProps) {
  return (
    <>
      <section className="case-detail-hero">
        <div className="section-container">
          <button type="button" className="btn-ghost mb-8" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            返回案例库
          </button>
          <div className="grid gap-10 lg:grid-cols-[0.92fr_1.08fr] lg:items-center">
            <div>
              <p className="eyebrow">{item.categoryLabel}</p>
              <h1 className="page-title">{item.title}</h1>
              <p className="page-copy">{item.detailIntro}</p>
              <div className="mt-6 flex flex-wrap gap-2">
                {item.features.map((feature) => (
                  <span key={feature} className="rounded-lg bg-white/75 px-3 py-2 text-sm font-medium text-slate-700 shadow-sm">
                    {feature}
                  </span>
                ))}
              </div>
            </div>
            <div className="case-detail-media">
              <img src={item.image} alt={`${item.title} resource cover`} />
              <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,17,31,0.02),rgba(8,17,31,0.54))]" />
              <div className="absolute bottom-5 left-5 right-5 rounded-lg border border-white/24 bg-white/90 p-4 backdrop-blur-xl">
                <p className="text-sm font-semibold text-ink">{item.route}</p>
                <p className="mt-1 text-sm text-slate-600">可放置演示视频、客户故事或部署录屏。</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="section-container">
        <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
          <article className="grid gap-6">
            {item.videoUrl ? (
              <div className="video-panel">
                <div className="flex items-center gap-2 border-b border-white/14 px-5 py-4 text-white">
                  <PlayCircle className="h-5 w-5 text-indigo-200" />
                  <span className="font-semibold">案例视频</span>
                </div>
                <video className="aspect-video w-full bg-black" src={item.videoUrl} controls poster={item.image} />
              </div>
            ) : null}

            <div className="grid gap-5 md:grid-cols-3">
              {item.sections.map((section) => (
                <section key={section.title} className="resource-section-card">
                  <h2 className="text-xl font-semibold tracking-normal text-ink">{section.title}</h2>
                  <p className="mt-4 text-sm leading-7 text-slate-600">{section.body}</p>
                </section>
              ))}
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-panel">
              <h2 className="text-2xl font-semibold tracking-normal text-ink">OpenTalking 链路</h2>
              <p className="mt-3 text-sm leading-7 text-slate-600">
                这个资源页可以继续扩展行业背景、客户故事、实施步骤、演示视频和可复用配置。
              </p>
              <div className="mt-6">
                <ArchitectureFlow />
              </div>
            </div>
          </article>

          <aside className="resource-sidebar">
            <p className="text-sm font-semibold text-ink">预期收益</p>
            <div className="mt-4 grid gap-3">
              {item.outcomes.map((outcome) => (
                <div key={outcome} className="flex gap-3 rounded-lg bg-slate-50 p-3">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mintline" />
                  <p className="text-sm leading-6 text-slate-700">{outcome}</p>
                </div>
              ))}
            </div>
            <a
              className="btn-primary mt-5 w-full"
              href="https://datascale-ai.github.io/opentalking/"
              target="_blank"
              rel="noreferrer"
            >
              查看部署文档
              <ExternalLink className="h-4 w-4" />
            </a>
          </aside>
        </div>
      </section>

      <section className="section-container">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div>
            <p className="eyebrow">Related stories</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-normal text-ink">继续查看相关场景</h2>
          </div>
          <button type="button" className="btn-ghost w-fit" onClick={onBack}>
            回到案例库
          </button>
        </div>
        <div className="mt-8 grid gap-5 md:grid-cols-3">
          {relatedCases.map((related) => (
            <CaseCard key={related.slug} item={related} onOpenCase={onOpenCase} />
          ))}
        </div>
      </section>
    </>
  );
}
