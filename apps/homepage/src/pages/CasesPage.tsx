import { Filter, Layers3 } from "lucide-react";
import { useMemo, useState } from "react";
import { CaseCard } from "../components/CaseCard";
import type { CaseStudy } from "../content";
import type { SiteContent } from "../locales";

type CasesPageProps = {
  caseCategories: SiteContent["caseCategories"];
  caseStudies: CaseStudy[];
  copy: SiteContent["casesPage"];
  onOpenCase: (slug: string) => void;
};

type CategoryKey = SiteContent["caseCategories"][number]["key"];

export function CasesPage({ caseCategories, caseStudies, copy, onOpenCase }: CasesPageProps) {
  const [activeCategory, setActiveCategory] = useState<CategoryKey>("all");

  const visibleCases = useMemo(() => {
    if (activeCategory === "all") return caseStudies;
    return caseStudies.filter((item) => item.category === activeCategory);
  }, [activeCategory, caseStudies]);

  return (
    <>
      <section className="mx-auto max-w-7xl px-5 pb-6 pt-16 md:pb-8 md:pt-20">
        <p className="eyebrow">{copy.eyebrow}</p>
        <h1 className="page-title">{copy.title}</h1>
        <p className="page-copy">
          {copy.description}<br />{copy.contributionLine}
        </p>
      </section>

      <section className="mx-auto max-w-7xl px-5 pb-16 pt-8 md:pb-20 md:pt-10">
        <div className="mt-8 grid gap-8 lg:grid-cols-[260px_1fr]">
          <aside className="case-sidebar">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Filter className="h-4 w-4 text-cyanline" />
              {copy.filterTitle}
            </div>
            <div className="mt-5 grid gap-2">
              {caseCategories.map((category) => {
                const count =
                  category.key === "all"
                    ? caseStudies.length
                    : caseStudies.filter((item) => item.category === category.key).length;

                return (
                  <button
                    key={category.key}
                    type="button"
                    className={`case-filter ${activeCategory === category.key ? "case-filter-active" : ""}`}
                    onClick={() => setActiveCategory(category.key)}
                  >
                    <span>{category.label}</span>
                    <span>{count}</span>
                  </button>
                );
              })}
            </div>
            <div className="mt-6 rounded-lg border border-indigo-100 bg-indigo-50/70 p-4 text-ink">
              <Layers3 className="h-5 w-5 text-cyanline" />
              <p className="mt-2 text-xs leading-6 text-indigo-950/68">
                {copy.resourceNote}
              </p>
            </div>
          </aside>

          <div>
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {visibleCases.map((item) => (
                <CaseCard
                  key={item.slug}
                  comingSoonLabel={copy.comingSoonLabel}
                  item={item}
                  onOpenCase={onOpenCase}
                />
              ))}
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
