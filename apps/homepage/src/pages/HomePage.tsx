import { ArrowRight, BookOpen, Github, PlayCircle, Quote } from "lucide-react";
import { CapabilityCard } from "../components/CapabilityCard";
import { DeploymentRoute } from "../components/DeploymentRoute";
import { HeroStage } from "../components/HeroStage";
import { SectionHeader } from "../components/SectionHeader";
import { ShowcaseCarousel } from "../components/ShowcaseCarousel";
import {
  capabilities,
  caseStudies,
  deploymentRoutes,
  productLinks,
  testimonials,
  type PageKey,
} from "../content";

type HomePageProps = {
  onNavigate: (page: PageKey) => void;
  onOpenCase: (slug: string) => void;
};

export function HomePage({ onNavigate, onOpenCase }: HomePageProps) {
  return (
    <>
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(99,102,241,0.13),rgba(255,255,255,0)_36%),linear-gradient(260deg,rgba(251,113,133,0.12),rgba(255,255,255,0)_34%)]" />
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(99,102,241,0.36),rgba(251,113,133,0.28),transparent)]" />
        <div className="section-container relative grid items-center gap-12 pt-14 lg:grid-cols-[0.88fr_1.12fr] lg:pt-20">
        <div className="animate-[reveal-up_620ms_ease_both]">
          <h1 className="max-w-4xl text-4xl font-semibold leading-[1.08] tracking-normal text-ink min-[420px]:text-5xl md:text-6xl">
            开源实时数字人
            <span className="gradient-text">生成与对话框架</span>
          </h1>
          <p className="mt-8 max-w-2xl text-lg leading-8 text-slate-600 md:mt-10">
            从文本、语音到数字人视频，OpenTalking 帮你快速搭建可本地运行、可二次开发、可私有化部署的数字人应用。
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <button type="button" className="btn-primary h-12 px-5" onClick={() => onNavigate("cases")}>
              <PlayCircle className="h-4 w-4" />
              看看 Demo
            </button>
            <button type="button" className="btn-ghost h-12 px-5" onClick={() => onNavigate("docs")}>
              <BookOpen className="h-4 w-4" />
              快速开始
            </button>
            <a className="btn-ghost h-12 px-5" href={productLinks.github} target="_blank" rel="noreferrer">
              <Github className="h-4 w-4" />
              GitHub
            </a>
          </div>
        </div>
        <HeroStage />
        </div>
      </section>

      <section className="section-container">
        <SectionHeader
          eyebrow="Product capability"
          title="从对话到画面，核心链路一次跑通"
          description="OpenTalking 把会话、语音、字幕、播放和模型服务串成完整的数字人产品链路。"
        />
        <div className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
          {capabilities.map((capability) => (
            <CapabilityCard key={capability.title} capability={capability} />
          ))}
        </div>
      </section>

      <section className="relative overflow-hidden bg-white/60">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(8,17,31,0.12),transparent)]" />
        <div className="section-container">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <SectionHeader
            eyebrow="Showcase"
            title="真实产品场景，为数字人服务而生"
            description="用同一套编排层覆盖直播、播报、陪伴、角色内容和端到端演示。"
          />
          <button type="button" className="btn-ghost w-fit" onClick={() => onNavigate("cases")}>
            全部案例
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-10">
          <ShowcaseCarousel items={caseStudies} onOpenCase={onOpenCase} />
        </div>
        </div>
      </section>

      <section className="section-container">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <SectionHeader
            eyebrow="Deployment"
            title="按你的需求匹配不同部署方式"
            description="从快速演示、本地离线到高质量交付，沿着同一套链路逐步升级。"
          />
          <a className="btn-ghost w-fit" href={productLinks.docsZh} target="_blank" rel="noreferrer">
            查看部署文档
            <ArrowRight className="h-4 w-4" />
          </a>
        </div>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {deploymentRoutes.map((route, index) => (
            <DeploymentRoute key={route.name} route={route} index={index} />
          ))}
        </div>
      </section>

      <section className="section-container">
        <SectionHeader eyebrow="Word of mouth" title="看看用户们的口碑～" description="谁在使用它？" />
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {testimonials.map((item) => (
            <article key={item.name} className="testimonial-card">
              <Quote className="h-8 w-8 text-mintline" />
              <p className="mt-5 text-base leading-8 text-indigo-950/76">"{item.quote}"</p>
              <div className="mt-6 border-t border-indigo-100 pt-5">
                <p className="font-semibold text-ink">{item.name}</p>
                <p className="mt-1 text-sm text-slate-500">{item.role}</p>
              </div>
            </article>
          ))}
        </div>
        <div className="mt-10 rounded-lg border border-indigo-100 bg-white/80 p-5 shadow-sm backdrop-blur-xl md:flex md:items-center md:justify-between">
          <div>
            <p className="text-lg font-semibold text-ink">也想试试自己的数字人应用？</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">先跑通 Demo，再把模型、音色和业务场景换成你的方案。</p>
          </div>
          <div className="mt-5 flex flex-col gap-3 sm:flex-row md:mt-0">
            <button type="button" className="btn-primary" onClick={() => onNavigate("cases")}>
              查看案例
              <ArrowRight className="h-4 w-4" />
            </button>
            <a className="btn-ghost" href={productLinks.github} target="_blank" rel="noreferrer">
              GitHub 仓库
              <Github className="h-4 w-4" />
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
