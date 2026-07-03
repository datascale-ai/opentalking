import { ArrowLeft, CheckCircle2, ExternalLink, PlayCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { trackAnalyticsEvent } from "../analytics";
import { CaseCard } from "../components/CaseCard";
import type { CaseStudy } from "../content";
import type { SiteContent } from "../locales";

type CaseDetailPageProps = {
  copy: SiteContent["caseDetail"];
  item: CaseStudy;
  relatedCases: CaseStudy[];
  onBack: () => void;
  onOpenCase: (slug: string) => void;
};

export function CaseDetailPage({
  copy,
  item,
  relatedCases,
  onBack,
  onOpenCase,
}: CaseDetailPageProps) {
  const videoItems = useMemo(() => {
    if (item.videoVariants?.length) {
      return item.videoVariants;
    }

    if (!item.videoUrl) {
      return [];
    }

    return [
      {
        title: copy.videoTitle,
        description: item.route,
        url: item.videoUrl,
        poster: item.image,
        videoId: `case-${item.slug}`,
      },
    ];
  }, [copy.videoTitle, item]);
  const [activeVideoIndex, setActiveVideoIndex] = useState(0);
  const activeVideo = videoItems[Math.min(activeVideoIndex, Math.max(videoItems.length - 1, 0))];

  useEffect(() => {
    setActiveVideoIndex(0);
  }, [item.slug]);

  return (
    <>
      <section className="case-detail-hero">
        <div className="section-container">
          <button type="button" className="btn-ghost mb-8" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            {copy.backToLibrary}
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
              <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,17,31,0.02),rgba(8,17,31,0.12))]" />
            </div>
          </div>
        </div>
      </section>

      <section className="section-container">
        <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
          <article className="grid gap-6">
            {activeVideo ? (
              <div className="video-panel">
                <div className="flex items-center gap-2 border-b border-white/14 px-5 py-4 text-white">
                  <PlayCircle className="h-5 w-5 text-indigo-200" />
                  <span className="font-semibold">{copy.videoTitle}</span>
                </div>
                {activeVideo.embedUrl ? (
                  <iframe
                    key={activeVideo.embedUrl}
                    className="aspect-video w-full bg-black"
                    src={activeVideo.embedUrl}
                    title={activeVideo.title}
                    allow="fullscreen; autoplay; encrypted-media; picture-in-picture"
                    allowFullScreen
                    loading="lazy"
                  />
                ) : (
                  <video
                    key={activeVideo.url}
                    className="aspect-video w-full bg-black"
                    src={activeVideo.url}
                    controls
                    poster={activeVideo.poster ?? item.image}
                    onPlay={() =>
                      trackAnalyticsEvent({
                        eventName: "video_play",
                        path: window.location.pathname,
                        language: window.location.pathname === "/en" || window.location.pathname.startsWith("/en/") ? "en" : "zh",
                        page: "caseDetail",
                        caseSlug: item.slug,
                        videoId: activeVideo.videoId ?? `case-${item.slug}`,
                      })
                    }
                  />
                )}
                {videoItems.length > 1 ? (
                  <div className="grid gap-3 border-t border-white/14 bg-indigo-950/95 p-4 md:grid-cols-2">
                    {videoItems.map((video, index) => {
                      const isActive = index === activeVideoIndex;

                      return (
                        <button
                          key={video.url}
                          type="button"
                          className={`group flex cursor-pointer gap-3 rounded-lg border p-2 text-left transition duration-300 ${
                            isActive
                              ? "border-cyanline bg-white text-ink"
                              : "border-white/14 bg-white/10 text-white hover:border-white/30 hover:bg-white/20"
                          }`}
                          onClick={() => setActiveVideoIndex(index)}
                        >
                          <img
                            src={video.poster ?? item.image}
                            alt={`${video.title} preview`}
                            className="h-16 w-24 shrink-0 rounded-md object-cover"
                          />
                          <span className="min-w-0">
                            <span className="block text-sm font-semibold">{video.title}</span>
                            <span className={`mt-1 block max-h-10 overflow-hidden text-xs leading-5 ${isActive ? "text-slate-600" : "text-white/70"}`}>
                              {video.description}
                            </span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ) : null}
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
          </article>

          <aside className="resource-sidebar">
            <p className="text-sm font-semibold text-ink">{copy.outcomesTitle}</p>
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
              {copy.docsCta}
              <ExternalLink className="h-4 w-4" />
            </a>
          </aside>
        </div>
      </section>

      <section className="section-container">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div>
            <p className="eyebrow">{copy.relatedEyebrow}</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-normal text-ink">{copy.relatedTitle}</h2>
          </div>
          <button type="button" className="btn-ghost w-fit" onClick={onBack}>
            {copy.backToLibrary}
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
