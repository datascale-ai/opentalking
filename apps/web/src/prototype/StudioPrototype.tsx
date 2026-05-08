import { useState } from "react";

const avatarPreviewUrl = new URL(
  "../../../../examples/avatars/flashtalk-demo/preview.png",
  import.meta.url,
).href;

type RightTab = "chat" | "events" | "exports" | "metrics";

const rightTabs: { id: RightTab; label: string }[] = [
  { id: "chat", label: "对话" },
  { id: "events", label: "事件" },
  { id: "exports", label: "导出" },
  { id: "metrics", label: "性能" },
];

const avatars = [
  { name: "灵眸主播", model: "FlashTalk", status: "已就绪", active: true },
  { name: "QuickTalk 助理", model: "QuickTalk", status: "可切换", active: false },
  { name: "MuseTalk Demo", model: "MuseTalk", status: "轻量演示", active: false },
];

const messages = [
  { role: "user", text: "帮我用直播口吻介绍一下这款新品。", time: "14:20" },
  {
    role: "assistant",
    text: "当然可以。我会用更自然的节奏突出卖点、适用场景和限时福利。",
    time: "14:20",
  },
  { role: "user", text: "语速稍微慢一点，像新闻主播。", time: "14:21" },
  {
    role: "assistant",
    text: "已切换为稳重播报风格，下一轮会降低语速并增强停顿。",
    time: "14:21",
  },
];

const events = [
  { type: "session.ready", desc: "Worker 已完成形象预热", tone: "ok" },
  { type: "speech.started", desc: "TTS 与口型合成开始", tone: "live" },
  { type: "subtitle.chunk", desc: "返回 18 字字幕片段", tone: "live" },
  { type: "webrtc.track", desc: "远端视频流已接入舞台", tone: "ok" },
  { type: "queue.idle", desc: "当前无排队任务", tone: "muted" },
];

const exportJobs = [
  { title: "直播介绍片段", meta: "00:42 · 1080p", status: "可下载", progress: 100 },
  { title: "离线整段导出", meta: "上传音频 demo.wav", status: "渲染中", progress: 64 },
  { title: "口型验证样片", meta: "00:12 · 竖屏", status: "已完成", progress: 100 },
];

const metrics = [
  { label: "首帧耗时", value: "1.8s", hint: "WebRTC media_started" },
  { label: "TTS 延迟", value: "420ms", hint: "DashScope realtime" },
  { label: "队列位置", value: "0", hint: "slot acquired" },
  { label: "输出帧率", value: "24fps", hint: "FlashTalk WS" },
];

function Icon({ name }: { name: "play" | "mic" | "upload" | "stop" | "send" | "spark" }) {
  const path = {
    play: "M8 5v14l11-7L8 5Z",
    mic: "M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z",
    upload: "M11 16h2V8.83l2.59 2.58L17 10l-5-5-5 5 1.41 1.41L11 8.83V16Zm-5 2h12v2H6v-2Z",
    stop: "M7 7h10v10H7V7Z",
    send: "M4 12 20 4l-5 16-3.2-6.8L4 12Zm7.1-.6 2.2 4.7 2.9-8.6-5.1 3.9Z",
    spark: "M12 2l1.7 5.3L19 9l-5.3 1.7L12 16l-1.7-5.3L5 9l5.3-1.7L12 2Zm6 12 1 3 3 1-3 1-1 3-1-3-3-1 3-1 1-3Z",
  }[name];

  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden>
      <path d={path} />
    </svg>
  );
}

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {action ? <button className="text-xs font-medium text-cyan-700">{action}</button> : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function StatusPill({ label, tone = "ok" }: { label: string; tone?: "ok" | "live" | "warn" | "muted" }) {
  const toneClass = {
    ok: "border-emerald-200 bg-emerald-50 text-emerald-700",
    live: "border-cyan-200 bg-cyan-50 text-cyan-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    muted: "border-slate-200 bg-slate-50 text-slate-600",
  }[tone];

  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${toneClass}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}

function ConfigSidebar() {
  return (
    <aside className="min-h-0 overflow-y-auto border-r border-slate-200 bg-slate-50/80 p-4 lg:w-[280px] lg:shrink-0">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500">当前工作流</p>
          <h1 className="text-lg font-semibold text-slate-950">实时对话</h1>
        </div>
        <StatusPill label="Live" tone="live" />
      </div>

      <div className="space-y-4">
        <Section title="数字人形象" action="资产库">
          <div className="space-y-2">
            {avatars.map((avatar) => (
              <button
                key={avatar.name}
                className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition ${
                  avatar.active
                    ? "border-cyan-300 bg-cyan-50 shadow-sm"
                    : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-xs font-semibold text-white">
                  {avatar.name.slice(0, 1)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-slate-900">{avatar.name}</span>
                  <span className="block truncate text-xs text-slate-500">{avatar.model} · {avatar.status}</span>
                </span>
              </button>
            ))}
          </div>
        </Section>

        <Section title="驱动模型">
          <div className="grid grid-cols-2 gap-2 text-xs">
            {["FlashTalk", "FlashHead", "QuickTalk", "MuseTalk"].map((model, index) => (
              <button
                key={model}
                className={`rounded-lg border px-3 py-2 font-medium ${
                  index === 0
                    ? "border-cyan-300 bg-cyan-50 text-cyan-800"
                    : "border-slate-200 bg-white text-slate-600"
                }`}
              >
                {model}
              </button>
            ))}
          </div>
        </Section>

        <Section title="声音与角色" action="复刻音色">
          <div className="space-y-3">
            <div>
              <p className="text-xs text-slate-500">合成线路</p>
              <p className="mt-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800">
                百炼 Qwen-TTS Realtime
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">朗读音色</p>
              <p className="mt-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800">
                Lingmou Anchor CN
              </p>
            </div>
            <div className="rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-200">
              你是一个专业数字人主播，语气自然、表达清晰，适合产品讲解和实时问答。
            </div>
          </div>
        </Section>

        <Section title="参考图">
          <div className="flex items-center gap-3">
            <div className="h-14 w-14 overflow-hidden rounded-lg bg-slate-200">
              <img src={avatarPreviewUrl} alt="数字人参考图" className="h-full w-full object-cover" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-900">flashtalk-demo</p>
              <p className="text-xs text-slate-500">1024x1024 · 已应用</p>
            </div>
          </div>
        </Section>
      </div>
    </aside>
  );
}

function Stage() {
  return (
    <main className="order-1 flex min-h-0 flex-1 flex-col bg-slate-100 lg:order-none">
      <div className="flex min-h-0 flex-1 flex-col p-4">
        <div className="relative min-h-[360px] flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70 lg:min-h-[420px]">
          <div className="absolute inset-0 bg-slate-50" />
          <div className="absolute inset-3 rounded-lg border border-slate-200 bg-white shadow-inner shadow-slate-200/60" />
          <div className="absolute left-4 right-4 top-4 z-10 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex min-w-0 flex-wrap gap-2">
              <StatusPill label="已连接" tone="ok" />
              <StatusPill label="WebRTC 24fps" tone="live" />
              <StatusPill label="低延迟模式" tone="muted" />
            </div>
            <div className="flex shrink-0 justify-end gap-2">
              <button className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50">
                重启会话
              </button>
              <button className="rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-400">
                开始录制
              </button>
            </div>
          </div>

          <div className="relative z-[1] flex h-full min-h-[360px] items-center justify-center px-4 pt-16 pb-24 lg:min-h-[420px] lg:px-8">
            <div className="relative flex aspect-[9/16] h-[min(62vh,620px)] max-h-full min-h-[260px] items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl shadow-slate-200/80 lg:min-h-[330px]">
              <img src={avatarPreviewUrl} alt="数字人舞台预览" className="h-full w-full object-cover" />
              <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-white/90 to-transparent" />
              <div className="absolute bottom-4 left-4 right-4 rounded-lg border border-slate-200 bg-white/95 px-4 py-3 text-center text-sm leading-relaxed text-slate-900 shadow-lg shadow-slate-300/50 backdrop-blur">
                欢迎来到 OpenTalking Studio，我可以实时回答问题，也可以生成适合直播和短视频的数字人内容。
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-end">
            <button className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50" title="上传音频">
              <Icon name="upload" />
            </button>
            <div className="min-w-0 flex-1">
              <p className="mb-1 text-xs font-medium text-slate-500">实时输入</p>
              <textarea
                className="h-11 w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-cyan-300 focus:bg-white"
                value="请用更专业的主播口吻介绍 OpenTalking 的实时数字人能力。"
                readOnly
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="flex h-11 w-11 items-center justify-center rounded-lg bg-emerald-600 text-white hover:bg-emerald-500" title="连续语音">
                <Icon name="mic" />
              </button>
              <button className="flex h-11 w-11 items-center justify-center rounded-lg bg-rose-600 text-white hover:bg-rose-500" title="打断">
                <Icon name="stop" />
              </button>
              <button className="flex h-11 min-w-24 items-center justify-center gap-2 rounded-lg bg-cyan-600 px-4 text-sm font-semibold text-white hover:bg-cyan-500">
                <Icon name="send" />
                发送
              </button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

function RightPanel({ activeTab, onTabChange }: { activeTab: RightTab; onTabChange: (tab: RightTab) => void }) {
  return (
    <aside className="min-h-0 overflow-hidden border-l border-slate-200 bg-white lg:w-[360px] lg:shrink-0">
      <div className="border-b border-slate-200 px-4 pt-4">
        <p className="text-xs font-medium text-slate-500">会话面板</p>
        <div className="mt-3 grid grid-cols-4 gap-1 rounded-lg bg-slate-100 p-1">
          {rightTabs.map((tab) => (
            <button
              key={tab.id}
              className={`rounded-md px-2 py-1.5 text-xs font-medium transition ${
                activeTab === tab.id ? "bg-white text-cyan-700 shadow-sm" : "text-slate-500 hover:text-slate-800"
              }`}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      <div className="h-[calc(100%-5.75rem)] overflow-y-auto p-4">
        {activeTab === "chat" ? <ChatPanel /> : null}
        {activeTab === "events" ? <EventsPanel /> : null}
        {activeTab === "exports" ? <ExportsPanel /> : null}
        {activeTab === "metrics" ? <MetricsPanel /> : null}
      </div>
    </aside>
  );
}

function ChatPanel() {
  return (
    <div className="space-y-3">
      {messages.map((message) => {
        const isUser = message.role === "user";
        return (
          <div key={`${message.time}-${message.text}`} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[86%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
                isUser ? "bg-cyan-600 text-white" : "bg-slate-100 text-slate-800"
              }`}
            >
              <p>{message.text}</p>
              <p className={`mt-1 text-[10px] ${isUser ? "text-cyan-100" : "text-slate-400"}`}>{message.time}</p>
            </div>
          </div>
        );
      })}
      <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-xs leading-relaxed text-cyan-800">
        连续语音已开启，静音自动断句；播报时可以直接抢话或点击停止按钮打断。
      </div>
    </div>
  );
}

function EventsPanel() {
  return (
    <div className="space-y-2">
      {events.map((event) => (
        <div key={event.type} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center justify-between gap-3">
            <code className="text-xs font-semibold text-slate-900">{event.type}</code>
            <StatusPill label={event.tone === "live" ? "流式" : event.tone === "ok" ? "正常" : "记录"} tone={event.tone as "ok" | "live" | "muted"} />
          </div>
          <p className="mt-2 text-xs text-slate-500">{event.desc}</p>
        </div>
      ))}
    </div>
  );
}

function ExportsPanel() {
  return (
    <div className="space-y-3">
      {exportJobs.map((job) => (
        <div key={job.title} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900">{job.title}</p>
              <p className="mt-1 text-xs text-slate-500">{job.meta}</p>
            </div>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">{job.status}</span>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-cyan-500" style={{ width: `${job.progress}%` }} />
          </div>
        </div>
      ))}
      <button className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-cyan-300 bg-cyan-50 py-3 text-sm font-semibold text-cyan-700 hover:bg-cyan-100">
        <Icon name="play" />
        新建视频创作任务
      </button>
    </div>
  );
}

function MetricsPanel() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-1">
      {metrics.map((metric) => (
        <div key={metric.label} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-medium text-slate-500">{metric.label}</p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{metric.value}</p>
          <p className="mt-1 text-xs text-slate-500">{metric.hint}</p>
        </div>
      ))}
    </div>
  );
}

function Header() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-cyan-300">
          <Icon name="spark" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-950">OpenTalking Studio</p>
          <p className="truncate text-xs text-slate-500">实时数字人工作台原型</p>
        </div>
      </div>

      <nav className="hidden items-center gap-1 rounded-lg bg-slate-100 p-1 md:flex">
        {["实时对话", "视频创作", "资产库", "运行监控"].map((item, index) => (
          <button
            key={item}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              index === 0 ? "bg-white text-cyan-700 shadow-sm" : "text-slate-500 hover:text-slate-800"
            }`}
          >
            {item}
          </button>
        ))}
      </nav>

      <div className="flex items-center gap-2">
        <StatusPill label="session_8f42" tone="muted" />
        <button className="hidden rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 sm:block">
          保存配置
        </button>
        <button className="rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800">
          发布演示
        </button>
      </div>
    </header>
  );
}

export function StudioPrototype() {
  const [activeTab, setActiveTab] = useState<RightTab>("chat");

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:h-screen lg:overflow-hidden">
      <Header />
      <div className="flex min-h-0 flex-col lg:h-[calc(100vh-3.5rem)] lg:flex-row">
        <div className="order-2 lg:order-none lg:max-h-none">
          <ConfigSidebar />
        </div>
        <Stage />
        <div className="order-3 lg:order-none lg:max-h-none">
          <RightPanel activeTab={activeTab} onTabChange={setActiveTab} />
        </div>
      </div>
    </div>
  );
}
