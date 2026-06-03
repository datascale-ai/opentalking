export type PageKey = "home" | "docs" | "cases" | "about" | "caseDetail";

export type NavItem = {
  key: PageKey;
  label: string;
};

export type Capability = {
  title: string;
  description: string;
  meta: string;
  icon: "radio" | "user" | "captions" | "plug";
};

export type CaseStudy = {
  slug: string;
  title: string;
  eyebrow: string;
  category: "livestream" | "media" | "character" | "companion" | "experiment";
  categoryLabel: string;
  description: string;
  detailIntro: string;
  route: string;
  features: string[];
  image: string;
  accent: "cyan" | "mint" | "amber" | "violet" | "rose" | "slate";
  videoUrl?: string;
  sections: Array<{
    title: string;
    body: string;
  }>;
  outcomes: string[];
};

export type DeploymentRoute = {
  name: string;
  badge: string;
  description: string;
  models: string;
  bestFor: string;
  outcome: string;
};

export type Testimonial = {
  quote: string;
  name: string;
  role: string;
};

export type DocsGroup = {
  title: string;
  description: string;
  links: Array<{
    label: string;
    href: string;
  }>;
};

export const navItems: NavItem[] = [
  { key: "home", label: "首页" },
  { key: "docs", label: "文档" },
  { key: "cases", label: "案例" },
  { key: "about", label: "关于我们" },
];

export const productLinks = {
  docsZh: "https://datascale-ai.github.io/opentalking/",
  docsEn: "https://datascale-ai.github.io/opentalking/en/",
  github: "https://github.com/datascale-ai/opentalking",
};

export const liveSignals = [
  "字幕事件",
  "打断控制",
  "记忆系统",
  "角色音色",
];

export const caseCategories = [
  { key: "all", label: "全部场景" },
  { key: "livestream", label: "直播带货" },
  { key: "media", label: "媒体播报" },
  { key: "character", label: "角色内容" },
  { key: "companion", label: "陪伴互动" },
  { key: "experiment", label: "创意实验" },
] as const;

export const capabilities: Capability[] = [
  {
    title: "实时对话编排",
    description:
      "把前端交互、会话状态、LLM 回复、流式语音和 WebRTC 播放组织成稳定的产品链路。",
    meta: "Session / LLM / WebRTC",
    icon: "radio",
  },
  {
    title: "角色与音色配置",
    description:
      "支持选择或创建数字人物，配置声音、TTS、STT 与驱动模型，适合多角色产品验证。",
    meta: "Avatar / Voice / Provider",
    icon: "user",
  },
  {
    title: "字幕与打断控制",
    description:
      "面向真实对话体验，保留字幕事件、语音播放状态和用户打断控制等关键产品细节。",
    meta: "Events / Interruptions",
    icon: "captions",
  },
  {
    title: "可插拔模型后端",
    description:
      "从本地快速启动，到远端高质量模型推理部署，按算力和质量需求渐进部署。",
    meta: "wav2lip / flashtalk",
    icon: "plug",
  },
];

export const caseStudies: CaseStudy[] = [
  {
    slug: "ecommerce-livestream",
    title: "电商带货",
    eyebrow: "高频互动",
    category: "livestream",
    categoryLabel: "直播带货",
    description:
      "面向商品讲解、评论问答和直播间陪跑，把语音回复、字幕和实时视频渲染整合到同一链路。",
    detailIntro:
      "用 OpenTalking 搭建一个可互动的数字人直播间，让商品介绍、用户问题和优惠转化都能通过实时语音和画面完成。",
    route: "Local GPU 或 OmniRT 高质量路线",
    features: ["实时问答", "角色音色", "字幕同步"],
    image: "/images/cases/live-sales.jpeg",
    accent: "amber",
    videoUrl: "https://github.com/user-attachments/assets/826c777b-a9d2-49be-a1a0-b295c8a4b498",
    sections: [
      {
        title: "场景挑战",
        body: "直播带货需要连续讲解、即时答疑和稳定播报节奏，单一数字人模型无法覆盖完整互动链路。",
      },
      {
        title: "OpenTalking 方案",
        body: "先用 Mock 模式验证会话、字幕和 WebRTC，再切到本地 GPU 或 OmniRT 后端，保留统一的前端和 API 编排。",
      },
      {
        title: "适合扩展",
        body: "后续可以加入商品知识库、评论接入、促销脚本和多角色主播配置，形成可复用直播模板。",
      },
    ],
    outcomes: ["商品讲解自动化", "评论问答实时响应", "字幕与视频同步展示"],
  },
  {
    slug: "news-anchor",
    title: "新闻主播",
    eyebrow: "稳定播报",
    category: "media",
    categoryLabel: "媒体播报",
    description:
      "适合新闻播报、公告解读和品牌内容栏目，口型同步、稳定输出和可控形象。",
    detailIntro:
      "把新闻文本、主播角色和实时视频输出组织起来，适合企业公告、财经播报、课程资讯和品牌栏目。",
    route: "QuickTalk / FlashTalk",
    features: ["高质量形象", "长文本播报", "WebRTC 播放"],
    image: "/images/cases/news-anchor.jpeg",
    accent: "cyan",
    videoUrl: "https://github.com/user-attachments/assets/34a282da-84cb-4134-bc4b-644356ac4f6f",
    sections: [
      {
        title: "场景挑战",
        body: "播报类内容需要稳定形象、清晰声音和长文本输出能力，还要便于切换语言、栏目和人物设定。",
      },
      {
        title: "OpenTalking 方案",
        body: "通过角色配置、TTS 提供商和合成后端组合，统一管理主播形象、音色、字幕事件与浏览器播放。",
      },
      {
        title: "内容生产",
        body: "可以把文本生成、审核、播报和录制流程拆开，逐步接入已有 CMS 或脚本生产系统。",
      },
    ],
    outcomes: ["长文本播报更稳定", "主播形象可切换", "适合栏目化内容生产"],
  },
  {
    slug: "anime-talk-show",
    title: "动漫脱口秀",
    eyebrow: "角色内容",
    category: "character",
    categoryLabel: "角色内容",
    description:
      "把二次元角色、文本创作和实时语音连接起来，快速验证内容 IP 的互动表达。",
    detailIntro:
      "用角色设定驱动内容表达，把文本创作、语音风格和数字人画面组合成可互动的角色栏目。",
    route: "Mock 验证后切 Local",
    features: ["角色设定", "创意台词", "低门槛验证"],
    image: "/images/webui.png",
    accent: "violet",
    videoUrl: "https://github.com/user-attachments/assets/b3743604-7f50-40d1-9248-f2df80ea7308",
    sections: [
      {
        title: "场景挑战",
        body: "角色内容经常需要快速试错，重点不只是画质，还包括人设、台词节奏和实时互动反馈。",
      },
      {
        title: "OpenTalking 方案",
        body: "通过 Mock 首跑快速验证角色设定和对话节奏，再按效果需求切换本地模型或远端高质量后端。",
      },
      {
        title: "内容扩展",
        body: "后续可以加入多角色切换、节目脚本、弹幕互动和内容素材库，形成角色 IP 生产流程。",
      },
    ],
    outcomes: ["快速验证角色人设", "降低内容试错成本", "后续可扩展多角色互动"],
  },
  {
    slug: "companion-character",
    title: "陪伴类角色",
    eyebrow: "自然对话",
    category: "companion",
    categoryLabel: "陪伴互动",
    description:
      "面向陪伴、咨询和训练类场景，适合打断、回复、字幕反馈和持续会话状态。",
    detailIntro:
      "把持续会话、轻量建议、语音输入和数字人反馈组合起来，适合陪伴、训练和咨询类原型验证。",
    route: "本地音频 + QuickTalk",
    features: ["多轮会话", "语音输入", "打断控制"],
    image: "/images/cases/companion.jpeg",
    accent: "mint",
    videoUrl: "https://github.com/user-attachments/assets/44bbf1d9-75b1-4b0a-9704-c7f81c39446e",
    sections: [
      {
        title: "场景挑战",
        body: "陪伴类产品对回复节奏、打断体验和字幕反馈要求更高，需要保证会话状态与音视频输出一致。",
      },
      {
        title: "OpenTalking 方案",
        body: "通过会话状态、语音输入、TTS 和 WebRTC 编排，先验证自然对话体验，再接入本地模型或专用知识库。",
      },
      {
        title: "体验边界",
        body: "适合做产品陪伴和轻量互动，不应替代专业医疗、法律或高风险咨询服务。",
      },
    ],
    outcomes: ["多轮会话更自然", "打断和字幕可观察", "便于私有化验证"],
  },
  {
    slug: "creative-performance",
    title: "创意演唱 / 模仿秀",
    eyebrow: "内容实验",
    category: "experiment",
    categoryLabel: "创意实验",
    description:
      "适合验证声音风格、形象表演和创意互动内容，用同一产品壳快速切换模型后端。",
    detailIntro:
      "用于声音、形象和表演内容的实验场，让团队快速比较不同模型、音色和脚本组合的表现。",
    route: "Local 或 OmniRT",
    features: ["声音风格", "角色演绎", "后端切换"],
    image: "/images/webui.png",
    accent: "rose",
    videoUrl: "https://github.com/user-attachments/assets/98e813c2-f170-4cc8-b934-a77a72061d2e",
    sections: [
      {
        title: "场景挑战",
        body: "创意内容变化快，常常需要比较不同声音、画面和脚本，不适合每次都重搭一套演示系统。",
      },
      {
        title: "OpenTalking 方案",
        body: "保留统一 WebUI 和 API 编排，通过配置切换模型、声音和角色，让创意验证成本更低。",
      },
      {
        title: "扩展方式",
        body: "可以加入素材管理、内容模板和录制导出，把实验结果沉淀成可复用资产。",
      },
    ],
    outcomes: ["快速比较模型效果", "适合内容团队试错", "可沉淀演示模板"],
  },
  {
    slug: "mobile-recording",
    title: "实时手机录制",
    eyebrow: "端到端演示",
    category: "experiment",
    categoryLabel: "端到端演示",
    description:
      "展示从输入到 API、模型服务、字幕事件和 WebRTC 画面播放的完整体验。",
    detailIntro:
      "用一个最小闭环证明 OpenTalking 的实时链路可以跑通，适合作为团队评估和部署前检查入口。",
    route: "Mock 首跑 + GPU 升级",
    features: ["端到端链路", "快速演示", "部署校验"],
    image: "/images/webui.png",
    accent: "slate",
    videoUrl: "https://github.com/user-attachments/assets/a3abce76-12c0-4b8b-844f-bbc5c3227dc7",
    sections: [
      {
        title: "场景挑战",
        body: "团队第一次评估数字人链路时，最容易被模型权重、推理服务和浏览器播放问题同时阻塞。",
      },
      {
        title: "OpenTalking 方案",
        body: "Mock 模式保留 API、TTS、字幕和 WebRTC 关键路径，让团队先确认产品链路，再升级真实视频推理。",
      },
      {
        title: "验证价值",
        body: "适合作为安装、配置、网络和播放能力的健康检查，也能作为对外演示的最小版本。",
      },
    ],
    outcomes: ["快速确认环境", "定位链路瓶颈", "为真实模型部署打基础"],
  },
];

export const deploymentRoutes: DeploymentRoute[] = [
  {
    name: "快速试用与方案演示",
    badge: "No GPU",
    description:
      "不准备模型权重和推理服务，也能先跑通对话、语音、字幕和浏览器播放，适合快速确认产品方向。",
    models: "静态数字人画面 + 真实 LLM/TTS/WebRTC 链路",
    bestFor: "产品经理、售前演示、第一次评估 OpenTalking 的团队",
    outcome: "10 分钟内看到可演示的最小圆形",
  },
  {
    name: "本地离线与私有化验证",
    badge: "Local GPU",
    description:
      "在自己的GPU机器或工作站上运行实时数字人渲染模型，支持素材、音频和会话等各样功能。",
    models: "QuickTalk / Wav2Lip / MuseTalk 本地后端",
    bestFor: "内容团队、私有化验证、需要离线运行和自定义形象的项目",
    outcome: "在成本可控的单机环境里生成真实数字人效果",
  },
  {
    name: "高质量生产与交付",
    badge: "Inference Serer",
    description:
      "部署分离数字服务和模型推理服务，获取更高质量的数字人渲染效果，适合企业交付、多卡推理和长期服务。",
    models: "FlashTalk / FlashHead",
    bestFor: "画质要求高、并发更高、需要稳定服务边界的团队",
    outcome: "从演示升级到可维护的生产级数字人链路",
  },
];

export const architectureNodes = [
  { label: "Browser", description: "输入、字幕、音视频播放" },
  { label: "API / Session", description: "会话状态与事件编排" },
  { label: "LLM / STT / TTS", description: "理解、回复与语音合成" },
  { label: "Synthesis", description: "Mock、Local 或 OmniRT" },
  { label: "WebRTC", description: "实时音视频回传" },
];

export const docsGroups: DocsGroup[] = [
  {
    title: "快速开始",
    description:
      "从 Mock 模式开始，不需要模型权重，先验证前端、API、LLM、TTS、STT 和 WebRTC。",
    links: [
      { label: "中文快速开始", href: productLinks.docsZh },
      { label: "English Quickstart", href: productLinks.docsEn },
    ],
  },
  {
    title: "部署路线",
    description:
      "按算力和质量需求选择 Mock、本地模型、全本地音频或 OmniRT 高质量远端推理。",
    links: [
      {
        label: "模型部署文档",
        href: `${productLinks.docsZh}zh/model-deployment/local-quicktalk-audio/`,
      },
      { label: "GitHub README", href: productLinks.github },
    ],
  },
  {
    title: "开发者入口",
    description:
      "查看 API、配置文件、脚本和社区贡献方式，把 OpenTalking 集成进自己的数字人产品。",
    links: [
      { label: "GitHub 仓库", href: productLinks.github },
      { label: "英文文档", href: productLinks.docsEn },
    ],
  },
];

export const configItems = [
  { key: "LLM", value: "OpenAI-compatible endpoint" },
  { key: "STT", value: "DashScope or local SenseVoice" },
  { key: "TTS", value: "Edge, DashScope, CosyVoice" },
  { key: "Backend", value: "mock, local, omnirt, direct_ws" },
];

export const roadmapItems = [
  "更丰富的数字人驱动模型接入",
  "更顺滑的本地与私有化部署体验",
  "更多可复用的产品场景 Demo",
  "更完善的社区文档、示例和贡献流程",
];

export const trustBadges = ["Python 3.10+", "React 18", "FastAPI", "WebRTC"];

export const testimonials: Testimonial[] = [
  {
    quote:
      "这个软件简直帮助我生成了很多数字人的素材，很方便的进行二次创作，并且可以全部离线本地使用。",
    name: "李明",
    role: "视觉设计师",
  },
  {
    quote:
      "这个项目很棒，让我很方便的帮助客户生成很多短视频数字人项目，免费降低了成本，非常好用。",
    name: "张晓Y",
    role: "虚拟人项目经理",
  },
  {
    quote:
      "开源的设计让我感到很惊喜，我们根据团队需求轻松进行了二次开发。非常贴合行业的痛点，给我们带来了很多便利。",
    name: "王强",
    role: "AI开发工程师",
  },
];

export const contactChannels = [
  {
    title: "QQ 交流群",
    description: "讨论实时数字人、FlashTalk、OmniRT、模型部署和产品场景。",
    value: "",
    href: "",
    kind: "qq",
  },
  {
    title: "交流合作",
    description: "私有化部署、场景共创、模型接入和企业合作咨询。",
    value: "contact@datascale-ai.com",
    href: "mailto:contact@datascale-ai.com",
    kind: "email",
  },
  {
    title: "GitHub",
    description: "提交 issue、PR、场景建议和文档反馈。",
    value: "datascale-ai/opentalking",
    href: productLinks.github,
    kind: "github",
  },
];
