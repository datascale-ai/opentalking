import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Clapperboard,
  Download,
  FolderOpen,
  Home,
  Link2,
  MessageCircle,
  Mic2,
  MonitorPlay,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Server,
  Settings,
  SlidersHorizontal,
  Square,
  Terminal,
  Trash2,
  Upload,
  UserRound,
  Video,
  Volume2,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type {
  BackendMode,
  BackendProfile,
  DesktopStatus,
  InstalledModelPackage,
  SaveProfileInput,
} from "../shared/types";

type View =
  | "home"
  | "live"
  | "create"
  | "avatars"
  | "voices"
  | "packages"
  | "works"
  | "tools"
  | "settings"
  | "webui";
type Tone = "ok" | "warn" | "error" | "info" | "neutral";

const navItems: { id: View; label: string; subtitle: string; icon: LucideIcon; badge?: string }[] = [
  { id: "home", label: "首页", subtitle: "确认当前体验状态，选择下一步任务", icon: Home },
  { id: "live", label: "实时对话", subtitle: "三栏布局：准备、数字人舞台、对话消息", icon: MessageCircle },
  { id: "create", label: "生成视频", subtitle: "脚本输入、生成配置和任务记录", icon: Clapperboard },
  { id: "avatars", label: "数字人", subtitle: "管理可用于对话和视频生成的形象", icon: UserRound, badge: "3" },
  { id: "voices", label: "声音", subtitle: "试听、选择和复刻数字人声音", icon: Mic2, badge: "4" },
  { id: "packages", label: "模型包", subtitle: "导入、启动、停止、日志、诊断", icon: Download, badge: "P1" },
  { id: "works", label: "作品", subtitle: "统一管理视频、录制、字幕和音频", icon: FolderOpen, badge: "8" },
  { id: "tools", label: "工具", subtitle: "常用独立任务", icon: Wrench },
  { id: "settings", label: "设置与诊断", subtitle: "技术配置集中在这里", icon: Settings },
  { id: "webui", label: "兼容 WebUI", subtitle: "加载现有 apps/web/dist", icon: MonitorPlay },
];

const healthCopy: Record<DesktopStatus["health"], string> = {
  stopped: "未启动",
  starting: "启动中",
  ready: "可以使用",
  error: "需要处理",
};

const modeCopy: Record<BackendMode, string> = {
  "managed-mock": "Mock 基础体验",
  "managed-local": "本地托管后端",
  "managed-package": "模型启动包",
  remote: "远端 API",
};

const packageHealthCopy: Record<InstalledModelPackage["health"], string> = {
  missing: "缺失",
  compatible: "可导入",
  unsupported: "不支持",
  ready: "可启动",
  error: "异常",
};

const avatarOptions = [
  { id: "anchor", name: "新闻主播", tag: "默认", summary: "适合产品介绍、资讯口播和演示视频。", tone: "ok" as Tone },
  { id: "teacher", name: "课程老师", tag: "可用", summary: "适合知识讲解、课件录制和培训内容。", tone: "info" as Tone },
  { id: "support", name: "客服助理", tag: "示例", summary: "适合企业服务、直播问答和欢迎语。", tone: "neutral" as Tone },
];

const voiceOptions = [
  { id: "natural-female", name: "自然女声", tag: "默认", summary: "清晰、稳定，适合第一次体验。", tone: "ok" as Tone },
  { id: "steady-male", name: "稳重男声", tag: "可用", summary: "适合正式介绍、课程总结和产品说明。", tone: "info" as Tone },
  { id: "course", name: "课程讲解", tag: "可用", summary: "节奏更稳，适合长文本讲解。", tone: "neutral" as Tone },
  { id: "support", name: "客服亲和", tag: "可用", summary: "语气更轻松，适合欢迎语和客服问答。", tone: "neutral" as Tone },
];

const works = [
  { name: "课程开场口播", type: "视频", avatar: "课程老师", voice: "课程讲解", status: "已完成", tone: "ok" as Tone, time: "今天 10:22" },
  { name: "客服欢迎语", type: "音频", avatar: "客服助理", voice: "客服亲和", status: "已完成", tone: "ok" as Tone, time: "今天 09:48" },
  { name: "产品介绍字幕", type: "字幕", avatar: "新闻主播", voice: "自然女声", status: "已完成", tone: "ok" as Tone, time: "昨天 18:14" },
  { name: "直播录制 06-04", type: "录制", avatar: "新闻主播", voice: "自然女声", status: "处理中", tone: "warn" as Tone, time: "今天 12:30" },
  { name: "短视频测试 03", type: "视频", avatar: "客服助理", voice: "稳重男声", status: "失败", tone: "error" as Tone, time: "昨天 16:07" },
];

function defaultStatus(): DesktopStatus {
  return {
    platform: "darwin",
    profileId: null,
    profileName: null,
    packageId: null,
    packageName: null,
    mode: null,
    health: "stopped",
    apiBaseUrl: null,
    proxyBaseUrl: null,
    apiPort: null,
    pid: null,
    logPath: null,
    worksDir: "",
    homeDir: "",
    lastError: null,
    modelsReachable: false,
    checkedAt: new Date().toISOString(),
  };
}

function toneForHealth(health: DesktopStatus["health"]): Tone {
  if (health === "ready") return "ok";
  if (health === "starting") return "warn";
  if (health === "error") return "error";
  return "neutral";
}

function toneForPackageHealth(health: InstalledModelPackage["health"]): Tone {
  if (health === "ready" || health === "compatible") return "ok";
  if (health === "unsupported" || health === "missing") return "warn";
  if (health === "error") return "error";
  return "neutral";
}

function platformCopy(platform: DesktopStatus["platform"]) {
  if (platform === "darwin") return "macOS";
  if (platform === "win32") return "Windows";
  return "Linux";
}

function Tag({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return <span className={`tag tag-${tone}`}>{children}</span>;
}

function Dot({ tone = "neutral" }: { tone?: Tone }) {
  return <span className={`dot dot-${tone}`} />;
}

function IconText({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <>
      <Icon className="button-icon" aria-hidden="true" />
      <span>{children}</span>
    </>
  );
}

function Panel({
  title,
  subtitle,
  action,
  className,
  children,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`panel ${className ?? ""}`}>
      <div className="panel-head">
        <div className="panel-title">
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {action}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

function SummaryRow({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="summary-row">
      <div>
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      {right}
    </div>
  );
}

function AvatarFigure({ large = false }: { large?: boolean }) {
  return (
    <div className={`avatar-figure ${large ? "large" : ""}`} aria-hidden="true">
      <div className="avatar-head" />
      <div className="avatar-body" />
    </div>
  );
}

function ActionCard({
  icon: Icon,
  tone,
  label,
  title,
  text,
  action,
}: {
  icon: LucideIcon;
  tone: Tone;
  label: string;
  title: string;
  text: string;
  action: React.ReactNode;
}) {
  return (
    <article className="action-card">
      <div>
        <Tag tone={tone}>{label}</Tag>
        <Icon className="card-icon" aria-hidden="true" />
        <h3>{title}</h3>
        <p>{text}</p>
      </div>
      {action}
    </article>
  );
}

function AssetCard({
  selected,
  name,
  tag,
  tone,
  summary,
  onSelect,
  icon: Icon,
}: {
  selected: boolean;
  name: string;
  tag: string;
  tone: Tone;
  summary: string;
  onSelect: () => void;
  icon: LucideIcon;
}) {
  return (
    <article className={`asset-card ${selected ? "selected" : ""}`}>
      <div className="asset-thumb">
        <Icon aria-hidden="true" />
      </div>
      <div className="asset-body">
        <div className="item-title">
          <strong>{name}</strong>
          <Tag tone={tone}>{tag}</Tag>
        </div>
        <p>{summary}</p>
        <button className={selected ? "primary" : ""} onClick={onSelect}>
          <IconText icon={selected ? CheckCircle2 : Play}>{selected ? "正在使用" : "使用"}</IconText>
        </button>
      </div>
    </article>
  );
}

function VoiceCard({
  selected,
  name,
  tag,
  tone,
  summary,
  onSelect,
}: {
  selected: boolean;
  name: string;
  tag: string;
  tone: Tone;
  summary: string;
  onSelect: () => void;
}) {
  return (
    <article className={`voice-card ${selected ? "selected" : ""}`}>
      <div className="voice-head">
        <div>
          <strong>{name}</strong>
          <span>{summary}</span>
        </div>
        <Tag tone={tone}>{tag}</Tag>
      </div>
      <div className="wave" aria-hidden="true">
        <i /><i /><i /><i /><i /><i /><i />
      </div>
      <div className="button-row">
        <button>
          <IconText icon={Volume2}>试听</IconText>
        </button>
        <button className={selected ? "primary" : ""} onClick={onSelect}>
          <IconText icon={selected ? CheckCircle2 : Play}>{selected ? "正在使用" : "使用"}</IconText>
        </button>
      </div>
    </article>
  );
}

function StatusRows({ status }: { status: DesktopStatus }) {
  return (
    <div className="status-rows">
      <div><span>当前 Profile</span><strong>{status.profileName ?? "未选择"}</strong></div>
      <div><span>运行模式</span><strong>{status.mode ? modeCopy[status.mode] : "未配置"}</strong></div>
      <div><span>API 地址</span><strong>{status.apiBaseUrl ?? "未连接"}</strong></div>
      <div><span>代理地址</span><strong>{status.proxyBaseUrl ?? "未启动"}</strong></div>
    </div>
  );
}

function PackageCard({
  pkg,
  selected,
  active,
  busy,
  onSelect,
  onStart,
  onStop,
  onLogs,
  onDelete,
}: {
  pkg: InstalledModelPackage;
  selected: boolean;
  active: boolean;
  busy: boolean;
  onSelect: () => void;
  onStart: () => void;
  onStop: () => void;
  onLogs: () => void;
  onDelete: () => void;
}) {
  const tone = active ? "ok" : toneForPackageHealth(pkg.health);
  return (
    <article className={`package-card ${selected ? "selected" : ""}`} onClick={onSelect}>
      <div className="package-head">
        <div className="package-icon">{pkg.model.slice(0, 2).toUpperCase()}</div>
        <div>
          <h3>{pkg.title}</h3>
          <p>{pkg.id} · v{pkg.version}</p>
        </div>
        <Tag tone={tone}>{active ? "运行中" : packageHealthCopy[pkg.health]}</Tag>
      </div>
      <div className="tag-list">
        <Tag tone="ok">实时对话</Tag>
        <Tag tone="info">视频生成</Tag>
        <Tag tone="neutral">{pkg.backend}</Tag>
      </div>
      <div className="compat-list">
        <span className={pkg.manifest.platforms.some((item) => item.os === "darwin" && item.supported !== false) ? "ok" : "warn"}>macOS</span>
        <span className={pkg.manifest.platforms.some((item) => item.os === "win32" && item.supported !== false) ? "ok" : "warn"}>Windows WSL2</span>
        <span className={pkg.manifest.platforms.some((item) => item.os === "linux" && item.supported !== false) ? "ok" : "warn"}>Linux CUDA</span>
      </div>
      <p>{pkg.healthReason ?? `启动入口：${pkg.manifest.entry.start}`}</p>
      <div className="button-row" onClick={(event) => event.stopPropagation()}>
        <button className="primary" onClick={onStart} disabled={busy || pkg.health === "unsupported" || active}>
          <IconText icon={Play}>启动</IconText>
        </button>
        <button onClick={onStop} disabled={busy || !active}>
          <IconText icon={Square}>停止</IconText>
        </button>
        <button onClick={onLogs}>
          <IconText icon={Terminal}>日志</IconText>
        </button>
        <button onClick={onDelete} disabled={busy}>
          <IconText icon={Trash2}>删除</IconText>
        </button>
      </div>
    </article>
  );
}

export function App() {
  const [view, setView] = useState<View>("home");
  const [status, setStatus] = useState<DesktopStatus>(defaultStatus());
  const [profiles, setProfiles] = useState<BackendProfile[]>([]);
  const [packages, setPackages] = useState<InstalledModelPackage[]>([]);
  const [logs, setLogs] = useState("");
  const [busy, setBusy] = useState(false);
  const [remoteName, setRemoteName] = useState("远端 OpenTalking API");
  const [remoteUrl, setRemoteUrl] = useState("http://127.0.0.1:8010");
  const [packageImportPath, setPackageImportPath] = useState("");
  const [selectedPackageId, setSelectedPackageId] = useState<string | null>(null);
  const [selectedAvatar, setSelectedAvatar] = useState(avatarOptions[0].id);
  const [selectedVoice, setSelectedVoice] = useState(voiceOptions[0].id);
  const [createMode, setCreateMode] = useState<"script" | "lip" | "record">("script");
  const [generationState, setGenerationState] = useState("等待开始");
  const [generationProgress, setGenerationProgress] = useState(0);
  const [stageCaption, setStageCaption] = useState("你好，我是 OpenTalking 数字人。输入一句话，我会同步生成语音和画面。");
  const [chatText, setChatText] = useState("继续介绍本地模型包的作用");
  const [messages, setMessages] = useState([
    { role: "assistant", text: "准备好了。你可以输入问题，也可以让数字人介绍产品。" },
    { role: "user", text: "请用 30 秒介绍 OpenTalking。" },
    { role: "assistant", text: "OpenTalking 是可私有化部署的实时数字人对话平台，适合客服、课程和内容生产。" },
  ]);

  const activeNav = navItems.find((item) => item.id === view) ?? navItems[0];
  const avatar = avatarOptions.find((item) => item.id === selectedAvatar) ?? avatarOptions[0];
  const voice = voiceOptions.find((item) => item.id === selectedVoice) ?? voiceOptions[0];
  const currentPackage = selectedPackageId
    ? packages.find((item) => item.id === selectedPackageId) ?? packages[0] ?? null
    : packages[0] ?? null;
  const webUiUrl = useMemo(() => status.proxyBaseUrl?.replace(/\/api$/, "/webui/") ?? null, [status.proxyBaseUrl]);
  const healthTone = toneForHealth(status.health);
  const combination = `${avatar.name} + ${voice.name}`;
  const packageRunning = status.mode === "managed-package" && status.health === "ready";
  const backendSummary = status.modelsReachable
    ? `${status.mode ? modeCopy[status.mode] : "后端"}可用`
    : status.health === "starting"
      ? "后端启动中"
      : status.health === "error"
        ? "连接需要处理"
        : "后端未启动";
  const backendTone: Tone = status.modelsReachable ? "ok" : status.health === "error" ? "error" : status.health === "starting" ? "warn" : "neutral";
  const packageSummary =
    packageRunning
      ? status.packageName ?? "模型包运行中"
      : packages.length > 0
        ? `${packages.length} 个启动包`
        : status.platform === "darwin"
          ? "可导入检查兼容性"
          : "未导入启动包";
  const nextStepTitle = status.modelsReachable
    ? "现在可以开始对话"
    : status.health === "starting"
      ? "后端正在启动"
      : status.health === "error"
        ? "连接需要处理"
        : "先启动基础体验";
  const nextStepText = status.modelsReachable
    ? `使用 ${combination} 进入实时对话，或直接生成口播视频。`
    : status.health === "starting"
      ? "稍等片刻，准备完成后会自动更新状态。"
      : status.health === "error"
        ? "打开设置与诊断可以查看原因、日志和连接配置。"
        : "启动 Mock 基础体验即可先跑通流程，后续再切换远端 API 或模型启动包。";

  async function refresh() {
    const [nextStatus, nextProfiles, nextPackages] = await Promise.all([
      window.openTalkingDesktop.getStatus(),
      window.openTalkingDesktop.listProfiles(),
      window.openTalkingDesktop.listPackages(),
    ]);
    setStatus(nextStatus);
    setProfiles(nextProfiles);
    setPackages(nextPackages);
    if (nextPackages.length > 0 && selectedPackageId && !nextPackages.some((item) => item.id === selectedPackageId)) {
      setSelectedPackageId(null);
    }
  }

  useEffect(() => {
    refresh().catch(console.error);
    return window.openTalkingDesktop.onStatusChanged((next) => setStatus(next));
  }, []);

  async function runAction(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function saveRemoteProfile() {
    const profile: SaveProfileInput = {
      name: remoteName.trim() || "远端 OpenTalking API",
      mode: "remote",
      apiBaseUrl: remoteUrl.trim(),
    };
    await runAction(async () => {
      const saved = await window.openTalkingDesktop.saveProfile(profile);
      await window.openTalkingDesktop.activateProfile(saved.id);
    });
  }

  async function showLogs(packageId?: string) {
    if (packageId) {
      setSelectedPackageId(packageId);
      setLogs(await window.openTalkingDesktop.tailPackageLogs(packageId, 160));
      return;
    }
    if (currentPackage) {
      setLogs(await window.openTalkingDesktop.tailPackageLogs(currentPackage.id, 160));
      return;
    }
    setLogs(await window.openTalkingDesktop.tailLogs(160));
  }

  async function importPackage() {
    await runAction(async () => {
      const imported = await window.openTalkingDesktop.importPackage(packageImportPath.trim() || undefined);
      setSelectedPackageId(imported.id);
    });
  }

  async function startPackage(pkg: InstalledModelPackage) {
    setSelectedPackageId(pkg.id);
    await runAction(() => window.openTalkingDesktop.startPackageBackend(pkg.id));
  }

  async function stopPackage(pkg: InstalledModelPackage) {
    setSelectedPackageId(pkg.id);
    await runAction(() => window.openTalkingDesktop.stopPackageBackend(pkg.id));
  }

  async function deletePackage(pkg: InstalledModelPackage) {
    await runAction(() => window.openTalkingDesktop.deletePackage(pkg.id));
    if (selectedPackageId === pkg.id) setSelectedPackageId(null);
  }

  function simulateGenerate(label: string) {
    let value = 0;
    setGenerationState(`${label}生成中`);
    setGenerationProgress(0);
    const timer = window.setInterval(() => {
      value += 16;
      setGenerationProgress(Math.min(value, 100));
      if (value >= 100) {
        window.clearInterval(timer);
        setGenerationState(`${label}已完成，作品已保存`);
      }
    }, 170);
  }

  function sendMessage() {
    const text = chatText.trim() || "继续介绍 OpenTalking";
    const assistant = "收到。我会用当前数字人和声音回复，并把结果同步到舞台字幕。";
    setMessages((items) => [...items, { role: "user", text }, { role: "assistant", text: assistant }]);
    setStageCaption(assistant);
  }

  return (
    <div className="desktop-shell">
      <header className="topbar">
        <div className="brand">
          <div className="logo">OT</div>
          <div>
            <strong>OpenTalking</strong>
            <span>Desktop Workbench</span>
          </div>
        </div>
        <div className="top-main">
          <div className="title-block">
            <h1>{activeNav.label}</h1>
            <p>{activeNav.subtitle}</p>
          </div>
          <div className="top-status">
            <span className="pill"><Dot tone={healthTone} />{healthCopy[status.health]}</span>
            <span className="pill"><Dot tone={packageRunning ? "ok" : "warn"} />{packageRunning ? "模型包运行中" : "QuickTalk 未启动"}</span>
            <span className="pill combo-pill">当前组合：<b>{combination}</b></span>
          </div>
        </div>
        <div className="top-actions">
          <button onClick={refresh} disabled={busy}>
            <IconText icon={RefreshCw}>状态检查</IconText>
          </button>
          <button className="primary" onClick={() => runAction(() => window.openTalkingDesktop.startBackend())} disabled={busy || status.health === "starting"}>
            <IconText icon={Play}>{busy ? "处理中" : "启动基础体验"}</IconText>
          </button>
        </div>
      </header>

      <aside className="sidebar">
        <nav aria-label="主导航">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}>
                <span className="nav-icon"><Icon aria-hidden="true" /></span>
                <span>{item.label}</span>
                {item.badge ? <span className="nav-badge">{item.badge}</span> : <span />}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-card">
          <span>当前工作组合</span>
          <strong>{combination}</strong>
          <div className="mini-list">
            <div><span>后端</span><b>{status.mode ? modeCopy[status.mode] : "未配置"}</b></div>
            <div><span>模型包</span><b>{packageSummary}</b></div>
            <div><span>作品</span><b>{works.length} 个</b></div>
          </div>
        </div>
      </aside>

      <main className="main">
        <section className="content">
          {view === "home" ? (
            <div className="page-stack wide">
              <div className="home-grid">
                <section className="home-workbench">
                  <div className="home-copy">
                    <div>
                      <Tag tone={backendTone}>{backendSummary}</Tag>
                      <h2>先选好数字人和声音，再开始对话或生成视频</h2>
                      <p>OpenTalking 桌面端把普通用户的主流程收敛成三步：准备形象和声音，确认模型服务可用，进入实时对话或视频生成。</p>
                    </div>
                    <div className="ready-list">
                      <div><span>数字人</span><Dot tone="ok" /><strong>{avatar.name}</strong><small>可用于实时对话</small></div>
                      <div><span>声音</span><Dot tone="ok" /><strong>{voice.name}</strong><small>支持试听和生成</small></div>
                      <div><span>后端</span><Dot tone={backendTone} /><strong>{backendSummary}</strong><small>{status.apiBaseUrl ?? "等待连接"}</small></div>
                      <div><span>模型包</span><Dot tone={packageRunning ? "ok" : "warn"} /><strong>{packageSummary}</strong><small>可导入 QuickTalk</small></div>
                    </div>
                    <div className="button-row">
                      <button className="primary" onClick={() => status.modelsReachable ? setView("live") : runAction(() => window.openTalkingDesktop.startBackend())} disabled={busy || status.health === "starting"}>
                        <IconText icon={status.modelsReachable ? MessageCircle : Play}>{status.modelsReachable ? "进入实时对话" : "启动基础体验"}</IconText>
                      </button>
                      <button onClick={() => setView("create")}><IconText icon={Clapperboard}>生成口播视频</IconText></button>
                      <button onClick={() => setView("packages")}><IconText icon={Download}>管理模型包</IconText></button>
                    </div>
                  </div>
                  <div className="avatar-preview">
                    <AvatarFigure />
                    <div className="preview-caption">
                      <strong>{combination}</strong>
                      <span>当前组合会同步到实时对话和生成视频</span>
                    </div>
                  </div>
                </section>

                <div className="status-stack">
                  <Panel title="下一步" subtitle="首页只保留最清晰的入口">
                    <SummaryRow title="基础体验" subtitle="无需模型包，适合先熟悉流程" right={<button className="primary" onClick={() => setView("live")}>开始</button>} />
                    <SummaryRow title="本地高质量模式" subtitle="导入 QuickTalk .otpkg 后启动" right={<button onClick={() => setView("packages")}>导入</button>} />
                    <SummaryRow title="远端 API" subtitle="连接已有 OpenTalking 服务" right={<button onClick={() => setView("settings")}>配置</button>} />
                  </Panel>
                  <Panel title="最近任务" subtitle="任务完成后统一进入作品" action={<button onClick={() => setView("works")}>查看全部</button>}>
                    {works.slice(0, 3).map((work) => (
                      <SummaryRow
                        key={work.name}
                        title={work.name}
                        subtitle={`${work.type} · ${work.status}`}
                        right={<Tag tone={work.tone}>{work.status}</Tag>}
                      />
                    ))}
                  </Panel>
                </div>
              </div>

              <div className="action-grid">
                <ActionCard
                  icon={MessageCircle}
                  tone="ok"
                  label="实时"
                  title="数字人对话"
                  text="左侧准备形象和声音，中间是数字人舞台，右侧输入文字或语音。"
                  action={<button className="primary" onClick={() => setView("live")}>开始对话</button>}
                />
                <ActionCard
                  icon={Video}
                  tone="info"
                  label="任务"
                  title="生成视频"
                  text="输入脚本，选择数字人和声音，生成结果自动沉淀到作品。"
                  action={<button onClick={() => setView("create")}>创建视频</button>}
                />
                <ActionCard
                  icon={Download}
                  tone="warn"
                  label="模型"
                  title="QuickTalk 本地包"
                  text="像 AIGCPanel 一样导入、启动、看日志、做诊断。"
                  action={<button onClick={() => setView("packages")}>打开模型包</button>}
                />
              </div>
            </div>
          ) : null}

          {view === "live" ? (
            <div className="live-grid">
              <div className="stack">
                <Panel title="对话前准备" subtitle="先确认形象、声音和后端">
                  <label>
                    数字人
                    <select value={selectedAvatar} onChange={(event) => setSelectedAvatar(event.target.value)}>
                      {avatarOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                  </label>
                  <label>
                    声音
                    <select value={selectedVoice} onChange={(event) => setSelectedVoice(event.target.value)}>
                      {voiceOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                  </label>
                  <div className="choice-list">
                    <button className="choice selected"><strong>文字输入</strong><span>稳定、适合演示和客服脚本</span></button>
                    <button className="choice"><strong>麦克风对话</strong><span>需要系统麦克风权限</span></button>
                  </div>
                </Panel>
                <Panel title="运行状态" subtitle="普通用户只看可用性">
                  <SummaryRow title="OpenTalking API" subtitle={status.apiBaseUrl ?? "未连接"} right={<Tag tone={backendTone}>{backendSummary}</Tag>} />
                  <SummaryRow title="QuickTalk" subtitle={packageRunning ? "QuickTalk Local 已连接" : "未启动"} right={<Tag tone={packageRunning ? "ok" : "warn"}>{packageRunning ? "运行中" : "未运行"}</Tag>} />
                  <button onClick={() => setView("packages")}><IconText icon={Download}>打开模型包</IconText></button>
                </Panel>
              </div>

              <section className="stage">
                <div className="stage-top">
                  <div className="button-row">
                    <span className="pill">{avatar.name}</span>
                    <span className="pill">{voice.name}</span>
                  </div>
                  <span className="pill"><Dot tone={status.modelsReachable ? "ok" : "warn"} />{status.modelsReachable ? "已连接" : "未连接"}</span>
                </div>
                <div className="stage-scene">
                  <AvatarFigure large />
                  <div className="subtitle-box">{stageCaption}</div>
                </div>
                <div className="stage-bottom">
                  <div className="button-row">
                    <button className="primary" onClick={() => setStageCaption(`当前使用 ${combination}，可以开始实时对话。`)}>
                      <IconText icon={Play}>开始</IconText>
                    </button>
                    <button><IconText icon={Square}>打断</IconText></button>
                    <button><IconText icon={Radio}>录制</IconText></button>
                  </div>
                  <div className="button-row">
                    <span className="pill">延迟 180ms</span>
                    <span className="pill">字幕开启</span>
                  </div>
                </div>
              </section>

              <Panel title="对话消息" subtitle="消息、字幕和语音同步" className="chat-panel">
                <div className="messages">
                  {messages.map((message, index) => (
                    <div key={`${message.role}-${index}`} className={`bubble ${message.role}`}>{message.text}</div>
                  ))}
                </div>
                <textarea value={chatText} onChange={(event) => setChatText(event.target.value)} placeholder="输入要让数字人说的话" />
                <div className="button-row">
                  <button className="primary" onClick={sendMessage}><IconText icon={MessageCircle}>发送</IconText></button>
                  <button><IconText icon={Mic2}>麦克风</IconText></button>
                  <button onClick={() => setMessages([])}>清空</button>
                </div>
              </Panel>
            </div>
          ) : null}

          {view === "create" ? (
            <div className="page-stack wide">
              <div className="create-grid">
                <Panel title="创建视频任务" subtitle="生成后自动进入作品列表" action={
                  <div className="mode-tabs">
                    <button className={createMode === "script" ? "active" : ""} onClick={() => setCreateMode("script")}>脚本口播</button>
                    <button className={createMode === "lip" ? "active" : ""} onClick={() => setCreateMode("lip")}>对口型</button>
                    <button className={createMode === "record" ? "active" : ""} onClick={() => setCreateMode("record")}>实时录制</button>
                  </div>
                }>
                  {createMode === "script" ? (
                    <div className="form-grid">
                      <label>数字人<input value={avatar.name} readOnly /></label>
                      <label>声音<input value={voice.name} readOnly /></label>
                      <label className="full">脚本文案<textarea className="tall" defaultValue="大家好，今天用一分钟介绍 OpenTalking。它可以把数字人实时对话、声音合成和视频生成放到一个桌面工作台里，适合课程、客服、直播助理和产品演示。" /></label>
                      <label>画面比例<select defaultValue="16:9"><option>16:9</option><option>9:16</option><option>1:1</option></select></label>
                      <label>字幕<select defaultValue="自动字幕"><option>自动字幕</option><option>不显示字幕</option><option>仅导出 SRT</option></select></label>
                      <div className="button-row full">
                        <button className="primary" onClick={() => simulateGenerate("视频")}><IconText icon={Clapperboard}>生成视频</IconText></button>
                        <button>保存草稿</button>
                      </div>
                    </div>
                  ) : null}
                  {createMode === "lip" ? (
                    <div className="form-grid">
                      <label className="full">上传视频<input value="选择一个人像视频文件" readOnly /></label>
                      <label className="full">音频或文本<textarea defaultValue="上传音频，或输入要生成的口播文本。" /></label>
                      <button className="primary" onClick={() => simulateGenerate("对口型")}><IconText icon={Video}>生成对口型视频</IconText></button>
                    </div>
                  ) : null}
                  {createMode === "record" ? (
                    <SummaryRow title="从实时对话录制" subtitle="进入对话页后打开录制，结束后保存视频、音频和字幕。" right={<button className="primary" onClick={() => setView("live")}>进入实时对话</button>} />
                  ) : null}
                </Panel>

                <div className="stack">
                  <div className="preview-box">
                    <div className="preview-scene"><AvatarFigure /></div>
                    <div className="preview-info">
                      <strong>{combination}</strong>
                      <span>{packageRunning ? "QuickTalk Local 本地高质量模式" : "Mock API 可生成基础预览"}</span>
                    </div>
                  </div>
                  <Panel title="生成状态" subtitle={generationState}>
                    <div className="progress"><span style={{ width: `${generationProgress}%` }} /></div>
                    <SummaryRow title="当前模型" subtitle={packageRunning ? "QuickTalk Local" : "Mock 基础体验"} right={<button onClick={() => setView("packages")}>切换</button>} />
                  </Panel>
                </div>
              </div>

              <Panel title="视频任务" subtitle="生成、失败、重试都有明确状态" action={<button onClick={() => setView("works")}>打开作品</button>}>
                <table className="data-table">
                  <thead><tr><th>任务</th><th>类型</th><th>组合</th><th>状态</th><th>操作</th></tr></thead>
                  <tbody>
                    {works.filter((work) => work.type === "视频" || work.type === "录制").map((work) => (
                      <tr key={work.name}>
                        <td>{work.name}</td>
                        <td>{work.type}</td>
                        <td>{work.avatar} / {work.voice}</td>
                        <td><Tag tone={work.tone}>{work.status}</Tag></td>
                        <td><button>{work.status === "失败" ? "重试" : "预览"}</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </div>
          ) : null}

          {view === "avatars" ? (
            <Panel title="数字人形象" subtitle="选择一个默认形象，后续任务自动带入" action={<button className="primary"><IconText icon={Plus}>创建数字人</IconText></button>}>
              <div className="asset-grid">
                {avatarOptions.map((item) => (
                  <AssetCard key={item.id} {...item} icon={UserRound} selected={item.id === selectedAvatar} onSelect={() => setSelectedAvatar(item.id)} />
                ))}
              </div>
            </Panel>
          ) : null}

          {view === "voices" ? (
            <div className="page-stack">
              <Panel title="声音库" subtitle="声音选择会同步到实时对话和生成视频" action={<button className="primary"><IconText icon={Plus}>复刻声音</IconText></button>}>
                <div className="voice-grid">
                  {voiceOptions.map((item) => (
                    <VoiceCard key={item.id} {...item} selected={item.id === selectedVoice} onSelect={() => setSelectedVoice(item.id)} />
                  ))}
                </div>
              </Panel>
              <Panel title="声音试听" subtitle="快速确认当前声音是否合适">
                <textarea defaultValue="你好，这是一段 OpenTalking 桌面端声音试听。" />
                <button className="primary"><IconText icon={Volume2}>试听当前声音</IconText></button>
              </Panel>
            </div>
          ) : null}

          {view === "packages" ? (
            <div className="packages-layout">
              <Panel title="模型启动包" subtitle=".otpkg 导入后进入用户数据目录，Windows 通过 WSL2 托管本地后端" action={
                <div className="toolbar">
                  <button className="primary" onClick={importPackage} disabled={busy}><IconText icon={Download}>导入 .otpkg</IconText></button>
                  <button onClick={() => window.openTalkingDesktop.openPath("home")}><IconText icon={FolderOpen}>打开目录</IconText></button>
                  <button onClick={refresh}><IconText icon={RefreshCw}>刷新</IconText></button>
                </div>
              }>
                <label>
                  启动包路径
                  <input
                    value={packageImportPath}
                    onChange={(event) => setPackageImportPath(event.target.value)}
                    placeholder="/path/to/opentalking-quicktalk-local.otpkg"
                  />
                </label>
                <div className="package-grid">
                  {packages.length === 0 ? (
                    <article className="package-card placeholder">
                      <div className="package-head">
                        <div className="package-icon">QT</div>
                        <div>
                          <h3>QuickTalk Local</h3>
                          <p>opentalking-quicktalk-local · 等待导入</p>
                        </div>
                        <Tag tone="warn">未导入</Tag>
                      </div>
                      <div className="tag-list">
                        <Tag tone="ok">实时对话</Tag>
                        <Tag tone="info">视频生成</Tag>
                        <Tag tone="neutral">本地高质量</Tag>
                      </div>
                      <div className="compat-list">
                        <span className="warn">macOS 仅远端 API</span>
                        <span className="ok">Windows WSL2</span>
                        <span className="ok">Linux CUDA</span>
                      </div>
                      <p>导入 QuickTalk .otpkg 后，可在 Windows WSL2 中一键启动本地后端。</p>
                      <button className="primary" onClick={importPackage} disabled={busy}><IconText icon={Upload}>选择 .otpkg 文件</IconText></button>
                    </article>
                  ) : null}
                  {packages.map((pkg) => (
                    <PackageCard
                      key={pkg.id}
                      pkg={pkg}
                      selected={currentPackage?.id === pkg.id}
                      active={status.packageId === pkg.id && status.health === "ready"}
                      busy={busy}
                      onSelect={() => setSelectedPackageId(pkg.id)}
                      onStart={() => startPackage(pkg)}
                      onStop={() => stopPackage(pkg)}
                      onLogs={() => showLogs(pkg.id)}
                      onDelete={() => deletePackage(pkg)}
                    />
                  ))}
                  <article className="package-card">
                    <div className="package-head">
                      <div className="package-icon">MK</div>
                      <div>
                        <h3>Mock 基础体验</h3>
                        <p>内置测试服务 · 无需权重</p>
                      </div>
                      <Tag tone={status.mode === "managed-mock" && status.health === "ready" ? "ok" : "neutral"}>
                        {status.mode === "managed-mock" && status.health === "ready" ? "运行中" : "可启动"}
                      </Tag>
                    </div>
                    <div className="tag-list"><Tag tone="ok">演示流程</Tag><Tag tone="info">接口联调</Tag></div>
                    <div className="compat-list"><span className="ok">macOS</span><span className="ok">Windows</span><span className="ok">Linux</span></div>
                    <button onClick={() => runAction(() => window.openTalkingDesktop.startBackend())} disabled={busy}><IconText icon={Play}>启动基础体验</IconText></button>
                  </article>
                  <article className="package-card">
                    <div className="package-head">
                      <div className="package-icon">API</div>
                      <div>
                        <h3>远端 OpenTalking API</h3>
                        <p>连接团队已有服务，不加载远端 UI</p>
                      </div>
                      <Tag tone="info">可配置</Tag>
                    </div>
                    <SummaryRow title="API Base URL" subtitle={remoteUrl} right={<button onClick={() => setView("settings")}>编辑</button>} />
                  </article>
                </div>
              </Panel>

              <div className="stack">
                <Panel title="服务日志" subtitle={currentPackage?.title ?? "QuickTalk Local"}>
                  <pre className="log-box">{logs || "选择模型包后点击“日志”，这里会显示最近运行日志。"}</pre>
                </Panel>
                <Panel title="普通用户提示" subtitle="技术细节留在模型包页和诊断页">
                  <SummaryRow title="Windows" subtitle="导入 QuickTalk 包后可一键启动 WSL2 后端" right={<Tag tone="ok">P1</Tag>} />
                  <SummaryRow title="macOS" subtitle="首轮使用 Mock 或远端 API，本地 QuickTalk 后置" right={<Tag tone="warn">限制</Tag>} />
                  <SummaryRow title="当前系统" subtitle={platformCopy(status.platform)} right={<Tag tone="info">{status.platform}</Tag>} />
                </Panel>
              </div>
            </div>
          ) : null}

          {view === "works" ? (
            <Panel title="作品与任务记录" subtitle="预览、下载、重试、删除都在这里完成" action={
              <div className="toolbar">
                <div className="search-box"><Search aria-hidden="true" /><input defaultValue="搜索作品名称" /></div>
                <button onClick={() => window.openTalkingDesktop.openPath("works")}><IconText icon={FolderOpen}>打开作品目录</IconText></button>
              </div>
            }>
              <table className="data-table">
                <thead><tr><th>名称</th><th>类型</th><th>数字人 / 声音</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
                <tbody>
                  {works.map((work) => (
                    <tr key={work.name}>
                      <td>{work.name}</td>
                      <td>{work.type}</td>
                      <td>{work.avatar} / {work.voice}</td>
                      <td><Tag tone={work.tone}>{work.status}</Tag></td>
                      <td>{work.time}</td>
                      <td className="table-actions"><button>{work.status === "失败" ? "重试" : "预览"}</button><button>下载</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          ) : null}

          {view === "tools" ? (
            <div className="tools-grid">
              <ActionCard icon={Volume2} tone="ok" label="声音" title="文本转语音" text="快速生成一段音频，保存到作品。" action={<button onClick={() => setView("voices")}>打开</button>} />
              <ActionCard icon={BookOpen} tone="info" label="字幕" title="字幕生成" text="从视频或音频提取字幕，支持导出 SRT。" action={<button onClick={() => setView("works")}>打开</button>} />
              <ActionCard icon={Video} tone="neutral" label="对口型" title="对口型工具" text="上传图片或视频，输入台词生成对口型。" action={<button onClick={() => { setCreateMode("lip"); setView("create"); }}>打开</button>} />
              <ActionCard icon={Terminal} tone="warn" label="诊断" title="环境检查" text="检查 API、模型包、WSL2、ffmpeg 和日志目录。" action={<button onClick={() => setView("settings")}>检查</button>} />
            </div>
          ) : null}

          {view === "settings" ? (
            <div className="settings-grid">
              <Panel title="连接配置" subtitle="支持 Mock、本地托管、模型包和远端 API" action={<button className="primary" onClick={saveRemoteProfile} disabled={busy}>保存</button>}>
                <div className="form-grid">
                  <label>后端模式<select value={status.mode ?? "managed-mock"} disabled><option>managed-mock</option><option>managed-package</option><option>remote</option><option>managed-local</option></select></label>
                  <label>API Base URL<input value={remoteUrl} onChange={(event) => setRemoteUrl(event.target.value)} /></label>
                  <label>名称<input value={remoteName} onChange={(event) => setRemoteName(event.target.value)} /></label>
                  <label>默认端口<input value={status.apiPort ?? 8010} readOnly /></label>
                </div>
                <StatusRows status={status} />
                {status.lastError ? <div className="error-box"><AlertCircle aria-hidden="true" />{status.lastError}</div> : null}
                <div className="button-row">
                  <button className="primary" onClick={() => runAction(() => window.openTalkingDesktop.startBackend())} disabled={busy}><IconText icon={Play}>启动</IconText></button>
                  <button onClick={() => runAction(() => window.openTalkingDesktop.stopBackend())} disabled={busy}><IconText icon={Square}>停止</IconText></button>
                  <button onClick={() => showLogs()}><IconText icon={Terminal}>查看日志</IconText></button>
                  <button onClick={() => setView("packages")}><IconText icon={Download}>模型包</IconText></button>
                </div>
              </Panel>

              <div className="stack">
                <Panel title="Profiles" subtitle="macOS 管理本地脚本；Windows 管理 WSL2 后端；远端只做连接检查">
                  <div className="profile-list">
                    {profiles.length === 0 ? <span className="muted">暂无 Profile，可先保存一个远端 API。</span> : null}
                    {profiles.map((profile) => (
                      <button
                        key={profile.id}
                        className={profile.id === status.profileId ? "selected" : ""}
                        onClick={() => runAction(() => window.openTalkingDesktop.activateProfile(profile.id))}
                      >
                        <strong>{profile.name}</strong>
                        <span>{modeCopy[profile.mode]}</span>
                      </button>
                    ))}
                  </div>
                </Panel>
                <Panel title="诊断摘要" subtitle="失败时给出明确下一步">
                  <SummaryRow title="端口" subtitle={status.apiPort ? `${status.apiPort}` : "未分配"} right={<Tag tone={status.apiPort ? "ok" : "neutral"}>{status.apiPort ? "正常" : "待检查"}</Tag>} />
                  <SummaryRow title="远端 API" subtitle={status.checkedAt ? `上次检查：${new Date(status.checkedAt).toLocaleString()}` : "未检查"} right={<Tag tone={backendTone}>{healthCopy[status.health]}</Tag>} />
                  <SummaryRow title="模型包" subtitle={packageSummary} right={<button onClick={() => setView("packages")}>管理</button>} />
                  <div className="button-row">
                    <button onClick={() => window.openTalkingDesktop.openPath("logs")}><IconText icon={FolderOpen}>日志目录</IconText></button>
                    <button onClick={() => window.openTalkingDesktop.openPath("home")}><IconText icon={FolderOpen}>数据目录</IconText></button>
                  </div>
                </Panel>
              </div>

              <Panel title="诊断日志" subtitle="需要排查时复制给开发者" className="full-span">
                <pre className="log-box">{logs || "点击“查看日志”后显示最近日志。"}</pre>
              </Panel>
            </div>
          ) : null}

          {view === "webui" ? (
            <Panel title="兼容 WebUI" subtitle="加载 apps/web/dist，并通过 Electron proxy 访问当前后端">
              {webUiUrl ? (
                <iframe className="webui-frame" title="OpenTalking WebUI" src={webUiUrl} />
              ) : (
                <div className="webui-box">
                  <h2>兼容 WebUI 入口</h2>
                  <p>桌面新版 UI 默认面向普通用户；现有 WebUI 保留给熟悉旧流程的用户和开发调试场景。</p>
                  <div className="button-row center">
                    <button className="primary" onClick={() => runAction(() => window.openTalkingDesktop.startBackend())}><IconText icon={Play}>启动后端</IconText></button>
                    <button onClick={() => setView("home")}>返回首页</button>
                  </div>
                </div>
              )}
            </Panel>
          ) : null}
        </section>
      </main>
    </div>
  );
}
