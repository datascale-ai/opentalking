import { ArrowUpRight, Github, MessageCircle } from "lucide-react";
import type { NavItem, PageKey } from "../content";
import { productLinks } from "../content";

type FooterProps = {
  navItems: NavItem[];
  onNavigate: (page: PageKey) => void;
};

export function Footer({ navItems, onNavigate }: FooterProps) {
  return (
    <footer className="border-t border-indigo-100 bg-white/75 backdrop-blur-xl">
      <div className="mx-auto grid max-w-7xl gap-8 px-5 py-12 lg:grid-cols-[1.12fr_0.72fr_0.72fr_0.9fr]">
        <div>
          <div className="flex items-center gap-3">
            <img
              src="/images/logo.png"
              alt="OpenTalking logo"
              className="h-12 w-12 rounded-lg border border-indigo-100 bg-white object-contain p-1 shadow-sm"
            />
            <div>
              <p className="font-semibold text-ink">OpenTalking</p>
              <p className="text-sm text-slate-500">开源实时数字人生成与对话框架</p>
            </div>
          </div>
          <p className="mt-5 max-w-md text-sm leading-7 text-slate-600">
            从 Demo、素材生产到私有化部署，帮助团队更快构建可落地的数字人应用。
          </p>
        </div>
        <div>
          <p className="text-sm font-semibold text-ink">站点</p>
          <div className="mt-4 grid gap-2">
            {navItems.map((item) => (
              <button
                key={item.key}
                type="button"
                className="focus-ring w-fit cursor-pointer rounded-lg text-sm text-slate-600 transition hover:text-ink"
                onClick={() => onNavigate(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-sm font-semibold text-ink">资源</p>
          <div className="mt-4 grid gap-2">
            <a className="footer-link" href={productLinks.docsZh} target="_blank" rel="noreferrer">
              中文文档 <ArrowUpRight className="h-3.5 w-3.5" />
            </a>
            <a className="footer-link" href={productLinks.docsEn} target="_blank" rel="noreferrer">
              English Docs <ArrowUpRight className="h-3.5 w-3.5" />
            </a>
            <a className="footer-link" href={productLinks.github} target="_blank" rel="noreferrer">
              GitHub <Github className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <MessageCircle className="h-4 w-4 text-cyanline" />
            加入交流群
          </div>
          <div className="mt-4 grid grid-cols-[96px_1fr] items-center gap-4">
            <img
              src="/images/qq_group_qrcode_cut.png"
              alt="AI 数字人交流群二维码"
              className="h-24 w-24 rounded-lg object-contain"
            />
            <div>
              <p className="text-sm font-semibold text-ink">AI 数字人交流群</p>
              <p className="code-font mt-1 text-sm text-indigo-700">1103327938</p>
              <p className="mt-2 text-xs leading-5 text-slate-500">讨论部署、模型接入、内容场景和二次开发。</p>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
