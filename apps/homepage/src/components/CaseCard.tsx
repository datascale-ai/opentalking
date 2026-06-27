import type { CaseStudy } from "../content";

type CaseCardProps = {
  comingSoonLabel?: string;
  item: CaseStudy;
  onOpenCase: (slug: string) => void;
};

export function CaseCard({ comingSoonLabel = "Coming soon", item, onOpenCase }: CaseCardProps) {
  const isComingSoon = item.comingSoon;
  const imagePosition = item.imagePosition ?? "center";

  const handleOpen = () => {
    const selectedText = window.getSelection()?.toString().trim();

    if (isComingSoon || selectedText) {
      return;
    }

    onOpenCase(item.slug);
  };

  return (
    <article
      className={`case-card case-card-${item.accent} ${isComingSoon ? "case-card-disabled" : ""}`}
      role={isComingSoon ? undefined : "button"}
      tabIndex={isComingSoon ? undefined : 0}
      aria-disabled={isComingSoon}
      onClick={handleOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleOpen();
        }
      }}
      aria-label={isComingSoon ? `${item.title} ${comingSoonLabel}` : item.title}
    >
      <div className="case-stage">
        <img
          src={item.image}
          alt={`${item.title} demo`}
          className="h-full w-full object-cover"
          style={{ objectPosition: imagePosition }}
        />
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,17,31,0.02),rgba(8,17,31,0.12))]" />
        <div className="absolute left-4 top-4 rounded-lg border border-white/30 bg-white/75 px-3 py-1 text-xs font-semibold text-ink shadow-sm backdrop-blur-xl">
          {item.categoryLabel}
        </div>
      </div>
      <div className="case-card-copy p-5">
        <h3 className="text-lg font-semibold tracking-normal text-ink">{item.title}</h3>
        <p className="mb-2 mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-cyanline">
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
        {isComingSoon ? (
          <span className="mt-5 inline-flex rounded-lg border border-indigo-100 bg-white px-3 py-1.5 text-xs font-semibold text-indigo-600">
            {comingSoonLabel}
          </span>
        ) : null}
      </div>
    </article>
  );
}
