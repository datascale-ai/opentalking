import { ArrowUpRight, CheckCircle2, Copy, Terminal } from "lucide-react";
import { DeploymentRoute } from "../components/DeploymentRoute";
import { SectionHeader } from "../components/SectionHeader";
import { configItems, deploymentRoutes, docsGroups } from "../content";

export function DocsPage() {
  return (
    <>
      <section className="page-hero">
        <p className="eyebrow">Documentation</p>
        <h1 className="page-title">从 Mock 首跑到高质量部署的导航页</h1>
        <p className="page-copy">
          这里不是替代完整文档，而是把 OpenTalking 最关键的启动路径、配置项和部署路线放在一个更容易扫描的入口。
        </p>
      </section>

      <section className="section-container">
        <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="panel-card">
            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-ink text-white">
              <Terminal className="h-5 w-5" />
            </div>
            <h2 className="mt-6 text-2xl font-semibold tracking-normal text-ink">推荐第一步</h2>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              使用 Mock 模式验证前端、API、LLM、TTS、STT、字幕事件和 WebRTC 播放链路，不需要模型权重或视频推理后端。
            </p>
            <div className="code-block mt-6">
              <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
                <span>start mock mode</span>
                <Copy className="h-4 w-4 text-slate-400" />
              </div>
              <pre className="overflow-x-auto p-4 text-sm">
                <code>{`uv sync --extra dev --python 3.11
source .venv/bin/activate
cp .env.example .env
bash scripts/start_unified.sh --mock`}</code>
              </pre>
            </div>
          </div>

          <div className="grid gap-4">
            {configItems.map((item) => (
              <div key={item.key} className="flex gap-4 rounded-lg border border-slate-200 bg-white p-4">
                <CheckCircle2 className="mt-1 h-5 w-5 shrink-0 text-mintline" />
                <div>
                  <p className="code-font text-sm font-semibold text-ink">{item.key}</p>
                  <p className="mt-1 text-sm text-slate-600">{item.value}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section-container">
        <SectionHeader
          eyebrow="Deployment paths"
          title="选择适合你的部署路线"
          description="每条路线都对应不同的首次体验成本、推理质量和私有化能力。"
        />
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {deploymentRoutes.map((route, index) => (
            <DeploymentRoute key={route.name} route={route} index={index} />
          ))}
        </div>
      </section>

      <section className="section-container pb-20">
        <SectionHeader
          eyebrow="Docs links"
          title="继续深入现有文档"
          description="保留完整文档站和 GitHub 作为权威入口，官网负责把路径讲清楚。"
        />
        <div className="mt-10 grid gap-5 md:grid-cols-3">
          {docsGroups.map((group) => (
            <article key={group.title} className="panel-card">
              <h3 className="text-xl font-semibold tracking-normal text-ink">{group.title}</h3>
              <p className="mt-3 text-sm leading-7 text-slate-600">{group.description}</p>
              <div className="mt-6 grid gap-3">
                {group.links.map((link) => (
                  <a key={link.label} className="resource-link" href={link.href} target="_blank" rel="noreferrer">
                    {link.label}
                    <ArrowUpRight className="h-4 w-4" />
                  </a>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
