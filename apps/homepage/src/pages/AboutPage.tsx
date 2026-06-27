import {
  ArrowUpRight,
  Code2,
  Github,
  MessageCircle,
  ServerCog,
  Sparkles,
  Video,
  Mail,
} from "lucide-react";
import { productLinks } from "../content";
import type { SiteContent } from "../locales";

const cooperationIcons = [ServerCog, Sparkles, Video, Code2];

type AboutPageProps = {
  contactChannels: SiteContent["contactChannels"];
  copy: SiteContent["about"];
  docsHref: string;
};

export function AboutPage({ contactChannels, copy, docsHref }: AboutPageProps) {
  return (
    <>
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(99,102,241,0.13),rgba(255,255,255,0)_38%),linear-gradient(260deg,rgba(251,113,133,0.12),rgba(255,255,255,0)_34%)]" />
        <div className="section-container relative pb-10 md:pb-12">
          <div>
            <p className="eyebrow">{copy.contactEyebrow}</p>
            <h1 className="mt-5 flex flex-wrap items-baseline gap-x-4 gap-y-2 text-[clamp(1.85rem,6.8vw,4.35rem)] font-semibold leading-[1.14] tracking-normal text-ink md:flex-nowrap md:gap-x-6 lg:gap-x-8">
              <span>{copy.titlePrefix}</span>
              <span className="relative inline-block bg-gradient-to-r from-cyanline via-violet-500 to-mintline bg-clip-text text-transparent drop-shadow-[0_18px_28px_rgba(99,102,241,0.16)]">
                {copy.titleBrand}
              </span>
              <span>{copy.titleSuffix}</span>
            </h1>
            <p className="mt-9 max-w-2xl text-lg leading-8 text-indigo-950/72 md:mt-10">
              {copy.intro}
            </p>
          </div>

          <div className="mt-9 grid gap-4 md:grid-cols-3">
            <article className="contact-feature-card contact-compact-card flex h-full min-h-40 items-center gap-4">
              <div className="min-w-0 flex-1">
                <MessageCircle className="h-5 w-5 text-cyanline" />
                <h2 className="mt-4 text-base font-semibold tracking-normal text-ink">
                  {copy.qqTitle}
                </h2>
                <p className="code-font mt-2 w-fit max-w-full rounded-md border border-indigo-100 bg-indigo-50/80 px-2.5 py-1.5 text-xs font-semibold text-indigo-700">
                  {copy.qqValue}
                </p>
                <p className="mt-3 text-sm leading-6 text-indigo-950/66">
                  {copy.qqDescription}
                </p>
              </div>
              <img
                src="/images/qq_group_qrcode_cut.png"
                alt="OpenTalking QQ 交流群二维码"
                className="h-24 w-24 shrink-0 rounded-lg object-contain shadow-sm"
              />
            </article>

            {contactChannels
              .filter((channel) => channel.kind !== "qq")
              .map((channel) => {
                const Icon =
                  channel.kind === "email"
                    ? Mail
                    : Github;
                const card = (
                  <article className="contact-feature-card contact-compact-card flex h-full min-h-40 flex-col">
                    <Icon className="h-5 w-5 text-cyanline" />
                    <h2 className="mt-4 text-base font-semibold tracking-normal text-ink">
                      {channel.title}
                    </h2>
                    {channel.value ? (
                      <p className="code-font mt-2 w-fit max-w-full rounded-md border border-indigo-100 bg-indigo-50/80 px-2.5 py-1.5 text-xs font-semibold text-indigo-700">
                        <span className="block break-words">{channel.value}</span>
                      </p>
                    ) : null}
                    <p className="mt-3 text-sm leading-6 text-indigo-950/66">
                      {channel.description}
                    </p>
                  </article>
                );

                return channel.href ? (
                  <a
                    key={channel.title}
                    href={channel.href}
                    target="_blank"
                    rel="noreferrer"
                    className="block h-full"
                  >
                    {card}
                  </a>
                ) : (
                  <div key={channel.title} className="h-full">
                    {card}
                  </div>
                );
              })}
          </div>
        </div>
      </section>

      <section className="section-container pt-8 md:pt-10">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div>
            <p className="eyebrow">{copy.collaborationEyebrow}</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-normal text-ink md:text-4xl">
              {copy.collaborationTitle}
            </h2>
            <p className="mt-4 max-w-2xl text-base leading-8 text-indigo-950/70">
              {copy.collaborationDescription}
            </p>
          </div>
        </div>
        <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
          {copy.cooperationAreas.map((area, index) => {
            const Icon = cooperationIcons[index] ?? Code2;

            return (
            <article key={area.title} className="contact-feature-card">
              <Icon className="h-6 w-6 text-cyanline" />
              <h3 className="mt-5 text-lg font-semibold tracking-normal text-ink">{area.title}</h3>
              <p className="mt-3 text-sm leading-7 text-indigo-950/66">{area.copy}</p>
            </article>
            );
          })}
        </div>
      </section>

      <section className="section-container pt-0">
        <div className="fresh-band p-6 md:grid md:grid-cols-[1fr_auto] md:items-center md:gap-8 md:p-8">
          <div>
            <p className="eyebrow">{copy.communityEyebrow}</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-normal text-ink md:text-4xl">
              {copy.communityTitle}
            </h2>
            <p className="mt-4 max-w-2xl text-base leading-8 text-indigo-950/70">
              {copy.communityDescription}
            </p>
          </div>
          <div className="mt-6 flex flex-col gap-3 sm:flex-row md:mt-0 md:flex-col">
            <a className="btn-ghost" href={productLinks.github} target="_blank" rel="noreferrer">
              {copy.githubCta}
              <ArrowUpRight className="h-4 w-4" />
            </a>
            <a className="btn-ghost" href={docsHref} target="_blank" rel="noreferrer">
              {copy.docsCta}
              <ArrowUpRight className="h-4 w-4" />
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
