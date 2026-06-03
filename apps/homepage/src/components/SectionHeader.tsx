import type { ReactNode } from "react";

type SectionHeaderProps = {
  eyebrow: string;
  title: string;
  description?: ReactNode;
  align?: "left" | "center";
};

export function SectionHeader({
  eyebrow,
  title,
  description,
  align = "left",
}: SectionHeaderProps) {
  return (
    <div className={align === "center" ? "mx-auto max-w-3xl text-center" : "max-w-3xl"}>
      <p className="eyebrow">{eyebrow}</p>
      <h2 className="mt-3 text-3xl font-semibold tracking-normal text-ink md:text-4xl">
        {title}
      </h2>
      {description ? (
        <p className="mt-4 text-base leading-8 text-slate-600 md:text-lg">{description}</p>
      ) : null}
    </div>
  );
}
