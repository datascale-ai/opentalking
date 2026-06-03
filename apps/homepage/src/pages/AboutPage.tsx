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
import { contactChannels, productLinks } from "../content";

const cooperationAreas = [
  {
    icon: ServerCog,
    title: "私有化部署与本地离线方案",
    copy: "围绕企业数据边界、GPU 资源和模型服务形态，评估从 Demo 到本地交付的部署路径。",
  },
  {
    icon: Sparkles,
    title: "数字人模型、音色与形象接入",
    copy: "接入不同数字人驱动模型、TTS 音色和角色资产，让 OpenTalking 适配更多内容生产流程。",
  },
  {
    icon: Video,
    title: "直播、短视频、课程与播报场景共创",
    copy: "把行业脚本、素材管理、演示视频和交互能力沉淀为可复用的数字人解决方案。",
  },
  {
    icon: Code2,
    title: "开源二次开发与技术支持",
    copy: "面向产品团队和开发者，支持 API 集成、模型适配、部署经验和文档改进。",
  },
];

export function AboutPage() {
  return (
    <>
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(99,102,241,0.13),rgba(255,255,255,0)_38%),linear-gradient(260deg,rgba(251,113,133,0.12),rgba(255,255,255,0)_34%)]" />
        <div className="section-container relative pb-10 md:pb-12">
          <div>
            <p className="eyebrow">Contact</p>
            <h1 className="mt-5 flex flex-wrap items-baseline gap-x-4 gap-y-2 text-[clamp(1.85rem,6.8vw,4.35rem)] font-semibold leading-[1.14] tracking-normal text-ink md:flex-nowrap md:gap-x-6 lg:gap-x-8">
              <span>联系</span>
              <span className="relative inline-block bg-gradient-to-r from-cyanline via-violet-500 to-mintline bg-clip-text text-transparent drop-shadow-[0_18px_28px_rgba(99,102,241,0.16)]">
                OpenTalking
              </span>
              <span>团队</span>
            </h1>
            <p className="mt-9 max-w-2xl text-lg leading-8 text-indigo-950/72 md:mt-10">
              无论是开源交流、私有化部署、模型接入还是场景共创，通过下面方式联系我们。
            </p>
          </div>

          <div className="mt-10 grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-stretch">
            <div className="grid h-full gap-4 md:grid-cols-3">
              {contactChannels.map((channel) => {
                const Icon =
                  channel.kind === "qq"
                    ? MessageCircle
                    : channel.kind === "email"
                      ? Mail
                      : Github;
                const card = (
                  <article className="contact-feature-card flex h-full min-h-64 flex-col">
                    <Icon className="h-6 w-6 text-cyanline" />
                    <h2 className="mt-5 text-lg font-semibold tracking-normal text-ink">
                      {channel.title}
                    </h2>
                    <p className="mt-3 text-sm leading-7 text-indigo-950/66">
                      {channel.description}
                    </p>
                    <p className="code-font mt-auto break-words pt-5 text-sm font-semibold text-indigo-700">
                      {channel.value}
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

            <aside className="contact-feature-card flex h-full min-h-64 items-center justify-center gap-5 text-left">
              <img
                src="/images/qq_group_qrcode_cut.png"
                alt="OpenTalking QQ 交流群二维码"
                className="h-32 w-32 shrink-0 rounded-lg object-contain shadow-sm"
              />
              <div className="min-w-0 max-w-[11rem]">
                <p className="text-base font-semibold text-ink">AI 数字人交流群</p>
                <p className="code-font mt-1 text-sm text-indigo-700">QQ: 1103327938</p>
                <p className="mt-3 text-sm leading-6 text-slate-600">
                  讨论模型部署、产品场景、内容案例和二次开发经验。
                </p>
              </div>
            </aside>
          </div>
        </div>
      </section>

      <section className="section-container pt-8 md:pt-10">
        <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div>
            <p className="eyebrow">Collaboration</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-normal text-ink md:text-4xl">
              聊聊合作？
            </h2>
            <p className="mt-4 max-w-2xl text-base leading-8 text-indigo-950/70">
              如果你正在评估实时数字人产品、内容生产工具或私有化部署路线，可以找我们沟通合作。
            </p>
          </div>
        </div>
        <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
          {cooperationAreas.map((area) => (
            <article key={area.title} className="contact-feature-card">
              <area.icon className="h-6 w-6 text-cyanline" />
              <h3 className="mt-5 text-lg font-semibold tracking-normal text-ink">{area.title}</h3>
              <p className="mt-3 text-sm leading-7 text-indigo-950/66">{area.copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section-container pt-0">
        <div className="fresh-band p-6 md:grid md:grid-cols-[1fr_auto] md:items-center md:gap-8 md:p-8">
          <div>
            <p className="eyebrow">Open source community</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-normal text-ink md:text-4xl">
              实时数字人开源生态贡献
            </h2>
            <p className="mt-4 max-w-2xl text-base leading-8 text-indigo-950/70">
              如果你对数字人的应用也感兴趣，欢迎提交模型适配、部署经验、行业案例和文档改进，也欢迎把你基于 OpenTalking 做出的产品形态分享给社区。
            </p>
          </div>
          <div className="mt-6 flex flex-col gap-3 sm:flex-row md:mt-0 md:flex-col">
            <a className="btn-ghost" href={productLinks.github} target="_blank" rel="noreferrer">
              GitHub 仓库
              <ArrowUpRight className="h-4 w-4" />
            </a>
            <a className="btn-ghost" href={productLinks.docsZh} target="_blank" rel="noreferrer">
              阅读文档
              <ArrowUpRight className="h-4 w-4" />
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
