import { ArrowRight, BookOpen, Github, PlayCircle, Quote } from "lucide-react";
import { CapabilityCard } from "../components/CapabilityCard";
import { DeploymentRoute } from "../components/DeploymentRoute";
import { HeroStage } from "../components/HeroStage";
import { SectionHeader } from "../components/SectionHeader";
import { ShowcaseCarousel } from "../components/ShowcaseCarousel";
import {
  productLinks,
  type PageKey,
} from "../content";
import type { SiteContent } from "../locales";

type HomePageProps = {
  content: SiteContent;
  onNavigate: (page: PageKey) => void;
  onOpenCase: (slug: string) => void;
};

const showcaseCaseSlugs = [
  "ecommerce-livestream",
  "huangshan-tour-guide",
  "medical-guide-assistant",
  "dual-news-anchor",
  "museum-artifact-guide",
  "government-service-guide",
  "multilingual-product-demo",
];

export function HomePage({ content, onNavigate, onOpenCase }: HomePageProps) {
  const { home } = content;
  const showcaseCases = showcaseCaseSlugs.flatMap((slug) => {
    const item = content.caseStudies.find((caseItem) => caseItem.slug === slug);
    return item ? [item] : [];
  });

  return (
    <>
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(99,102,241,0.13),rgba(255,255,255,0)_36%),linear-gradient(260deg,rgba(251,113,133,0.12),rgba(255,255,255,0)_34%)]" />
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(99,102,241,0.36),rgba(251,113,133,0.28),transparent)]" />
        <div className="section-container relative grid items-center gap-12 pt-14 lg:grid-cols-[0.88fr_1.12fr] lg:pt-20">
        <div className="animate-[reveal-up_620ms_ease_both]">
          <h1 className="max-w-4xl text-4xl font-semibold leading-[1.08] tracking-normal text-ink min-[420px]:text-5xl md:text-6xl">
            {home.heroTitleTop}
            <span className="gradient-text">{home.heroTitleAccent}</span>
          </h1>
          <p className="mt-8 max-w-2xl text-lg leading-8 text-slate-600 md:mt-10">
            {home.heroDescription}
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <button type="button" className="btn-primary h-12 px-5" onClick={() => onNavigate("cases")}>
              <PlayCircle className="h-4 w-4" />
              {home.demoCta}
            </button>
            <button type="button" className="btn-ghost h-12 px-5" onClick={() => onNavigate("docs")}>
              <BookOpen className="h-4 w-4" />
              {home.quickStartCta}
            </button>
            <a className="btn-ghost h-12 px-5" href={productLinks.github} target="_blank" rel="noreferrer">
              <Github className="h-4 w-4" />
              GitHub
            </a>
          </div>
        </div>
        <HeroStage copy={content.heroStage} />
        </div>
      </section>

      <section className="section-container">
        <SectionHeader
          eyebrow={home.capabilityEyebrow}
          title={home.capabilityTitle}
          description={home.capabilityDescription}
        />
        <div className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
          {content.capabilities.map((capability) => (
            <CapabilityCard key={capability.title} capability={capability} />
          ))}
        </div>
      </section>

      <section className="relative overflow-hidden bg-white/60">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(8,17,31,0.12),transparent)]" />
        <div className="section-container">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <SectionHeader
            eyebrow={home.showcaseEyebrow}
            title={home.showcaseTitle}
            description={home.showcaseDescription}
          />
          <button type="button" className="btn-ghost w-fit" onClick={() => onNavigate("cases")}>
            {home.allCasesCta}
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-10">
          <ShowcaseCarousel copy={content.showcase} items={showcaseCases} onOpenCase={onOpenCase} />
        </div>
        </div>
      </section>

      <section className="section-container">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <SectionHeader
            eyebrow={home.deploymentEyebrow}
            title={home.deploymentTitle}
            description={home.deploymentDescription}
          />
          <a className="btn-ghost w-fit" href={content.docsHref} target="_blank" rel="noreferrer">
            {home.deploymentDocsCta}
            <ArrowRight className="h-4 w-4" />
          </a>
        </div>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {content.deploymentRoutes.map((route, index) => (
            <DeploymentRoute copy={content.deploymentCard} key={route.name} route={route} index={index} />
          ))}
        </div>
      </section>

      <section className="section-container pt-8 md:pt-10">
        <SectionHeader eyebrow={home.wordEyebrow} title={home.wordTitle} description={home.wordDescription} />
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {content.testimonials.map((item) => (
            <article key={item.name} className="testimonial-card">
              <div className="flex items-center justify-between gap-4">
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-lg bg-indigo-50 text-cyanline">
                  <Quote className="h-5 w-5" />
                </span>
                <span className="rounded-full border border-indigo-100 bg-white px-3 py-1 text-xs font-semibold text-indigo-700">
                  {item.role}
                </span>
              </div>
              <p className="mt-6 text-lg font-medium leading-9 text-ink">"{item.quote}"</p>
              <div className="mt-8 flex items-center gap-3 border-t border-indigo-100 pt-5">
                <img
                  src={item.avatar}
                  alt={`${item.name} avatar`}
                  className="h-12 w-12 rounded-full border border-indigo-100 bg-white object-cover p-0.5 shadow-sm"
                />
                <div>
                  <p className="font-semibold text-ink">{item.name}</p>
                  <p className="mt-1 text-sm text-slate-500">{home.feedbackLabel}</p>
                </div>
              </div>
            </article>
          ))}
        </div>
        <div className="mt-10 rounded-lg border border-indigo-100 bg-white/80 p-5 shadow-sm backdrop-blur-xl md:flex md:items-center md:justify-between">
          <div>
            <p className="text-lg font-semibold text-ink">{home.finalCtaTitle}</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">{home.finalCtaDescription}</p>
          </div>
          <div className="mt-5 flex flex-col gap-3 sm:flex-row md:mt-0">
            <button type="button" className="btn-primary" onClick={() => onNavigate("cases")}>
              {home.finalCasesCta}
              <ArrowRight className="h-4 w-4" />
            </button>
            <a className="btn-ghost" href={productLinks.github} target="_blank" rel="noreferrer">
              {home.githubRepoCta}
              <Github className="h-4 w-4" />
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
