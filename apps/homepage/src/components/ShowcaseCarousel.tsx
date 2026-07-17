import { ArrowLeft, ArrowRight, PlayCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CaseStudy } from "../content";
import type { SiteContent } from "../locales";

type ShowcaseCarouselProps = {
  copy: SiteContent["showcase"];
  items: CaseStudy[];
  onOpenCase: (slug: string) => void;
};

export function ShowcaseCarousel({ copy, items, onOpenCase }: ShowcaseCarouselProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const activeItem = items[activeIndex];

  const progressItems = useMemo(() => items.slice(0, 7), [items]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setActiveIndex((index) => (index + 1) % items.length);
    }, 5600);

    return () => window.clearInterval(timer);
  }, [items.length]);

  const goTo = (index: number) => {
    setActiveIndex((index + items.length) % items.length);
  };

  return (
    <div className="showcase-carousel">
      <div className="relative min-h-[430px] overflow-hidden rounded-lg">
        <div key={activeItem.slug} className="absolute inset-0 animate-[showcase-image_1100ms_ease_both]">
          <img
            src={activeItem.image}
            alt={`${activeItem.title} showcase`}
            className="h-full w-full object-cover"
            style={{ objectPosition: activeItem.imagePosition ?? "center" }}
          />
          <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(8,17,31,0.86),rgba(8,17,31,0.32)_54%,rgba(8,17,31,0.10))]" />
        </div>
        <div key={`${activeItem.slug}-content`} className="relative flex min-h-[430px] animate-[showcase-copy_820ms_ease_both] flex-col justify-between p-6 text-white md:p-8">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-lg border border-white/24 bg-white/10 px-3 py-1 text-xs font-semibold backdrop-blur">
              {activeItem.categoryLabel}
            </span>
            <span className="rounded-lg border border-white/24 bg-white/10 px-3 py-1 text-xs font-semibold backdrop-blur">
              {activeItem.route}
            </span>
          </div>
          <div className="max-w-xl">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-indigo-200">
              {copy.featuredLabel}
            </p>
            <h3 className="mt-4 text-3xl font-semibold tracking-normal md:text-5xl">
              {activeItem.title}
            </h3>
            <p className="mt-4 text-base leading-8 text-white/82">{activeItem.detailIntro}</p>
            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <button type="button" className="btn-light" onClick={() => onOpenCase(activeItem.slug)}>
                <PlayCircle className="h-4 w-4" />
                {copy.openResourceCta}
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="carousel-icon-button"
                  aria-label={copy.previousLabel}
                  onClick={() => goTo(activeIndex - 1)}
                >
                  <ArrowLeft className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  className="carousel-icon-button"
                  aria-label={copy.nextLabel}
                  onClick={() => goTo(activeIndex + 1)}
                >
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {progressItems.map((item, index) => (
          <button
            key={item.slug}
            type="button"
            className={`showcase-thumb ${activeIndex === index ? "showcase-thumb-active" : ""}`}
            onClick={() => goTo(index)}
          >
            <span className="block truncate text-sm font-semibold">{item.title}</span>
            <span className="mt-1 block truncate text-xs text-slate-500">{item.categoryLabel}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
