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
  category: "livestream" | "media" | "tourism" | "healthcare" | "character" | "companion" | "experiment";
  categoryLabel: string;
  description: string;
  detailIntro: string;
  route: string;
  features: string[];
  image: string;
  imagePosition?: string;
  accent: "cyan" | "mint" | "amber" | "violet" | "rose" | "slate";
  comingSoon?: boolean;
  videoUrl?: string;
  videoVariants?: Array<{
    title: string;
    description: string;
    url: string;
    embedUrl?: string;
    poster?: string;
    videoId?: string;
  }>;
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
  avatar: string;
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
  { key: "tourism", label: "文旅导览" },
  { key: "healthcare", label: "医疗服务" },
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
    route: "双机位直播带货演示",
    features: ["实时问答", "角色音色", "字幕同步"],
    image: "/images/cases/ecommerce-live-front-preview.png",
    accent: "amber",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/742bcb745001834809665869890/vkxsFysr5REA.mp4",
    videoVariants: [
      {
        title: "正视直播间",
        description: "正面机位展示商品讲解、优惠信息和直播间视觉元素，适合官网主案例展示。",
        url: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/742bcb745001834809665869890/vkxsFysr5REA.mp4",
        embedUrl: "https://player.bilibili.com/player.html?bvid=BV1jhT76hENu&page=1&autoplay=0&high_quality=1&danmaku=0",
        poster: "/images/cases/ecommerce-live-front-preview.png",
        videoId: "case-ecommerce-livestream-front",
      },
      {
        title: "斜视带货机位",
        description: "加入真实拍摄机位感，突出桌面商品、导购动作和直播场景的空间层次。",
        url: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/cca683435001834809670031995/aswhi0HNmYkA.mp4",
        poster: "/images/cases/ecommerce-live-angle-preview.png",
        videoId: "case-ecommerce-livestream-angle",
      },
    ],
    sections: [
      {
        title: "场景挑战",
        body: "直播带货需要连续讲解、即时答疑和稳定播报节奏，单一数字人模型无法覆盖完整互动链路。",
      },
      {
        title: "适合扩展",
        body: "可以接入商品知识库、评论流、促销脚本和多角色主播配置，把单次演示沉淀成可复用的直播间模板。",
      },
      {
        title: "推荐模型",
        body: "推荐 OmniRT / FlashTalk：口型和画面质量更稳定，适合长时段直播、品牌带货和面向客户展示的高质量效果。",
      },
    ],
    outcomes: ["商品讲解自动化", "评论问答实时响应", "字幕与视频同步展示"],
  },
  {
    slug: "huangshan-tour-guide",
    title: "黄山文旅导览",
    eyebrow: "沉浸讲解",
    category: "tourism",
    categoryLabel: "文旅导览",
    description:
      "面向景区、城市展馆和文旅宣传，用数字人讲解自然景观、路线亮点和地域文化。",
    detailIntro:
      "以黄山介绍为例，把景区画面、导览口播和数字讲解员结合起来，适合游客中心、城市展厅和线上文旅内容展示。",
    route: "QuickTalk / FlashTalk",
    features: ["景区讲解", "沉浸画面", "多语言扩展"],
    image: "/images/cases/huangshan-guide-preview.png",
    accent: "mint",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/742bcf735001834809665869970/T9jkqMRNCacA.mp4",
    sections: [
      {
        title: "场景挑战",
        body: "文旅内容既要讲清景点特色，也要保持画面感染力和讲解节奏，传统拍摄更新成本较高。",
      },
      {
        title: "适合扩展",
        body: "可以接入景区知识库、路线推荐、多语言导览和游客问答，把单条宣传片扩展成可互动的数字导览员。",
      },
      {
        title: "推荐模型",
        body: "推荐 QuickTalk / FlashTalk：先快速验证导览脚本和画面融合，再按展厅大屏或宣传片质量要求升级。",
      },
    ],
    outcomes: ["景区讲解视频化", "导览内容可复用", "支持后续多语言与问答扩展"],
  },
  {
    slug: "medical-guide-assistant",
    title: "医疗导诊助手",
    eyebrow: "智能导诊",
    category: "healthcare",
    categoryLabel: "医疗服务",
    description:
      "面向医院大厅、线上问诊入口和健康服务平台，用数字人完成就诊指引、科室导航和检查咨询。",
    detailIntro:
      "以医疗导诊助手为例，把数字人讲解、导诊流程、科室导航和多语言服务整合到同一产品体验中，适合医院服务台、互联网医院和健康管理平台。",
    route: "中英双语导诊演示",
    features: ["就诊指引", "科室导航", "双语服务"],
    image: "/images/cases/medical-guide-zh-preview.png",
    accent: "cyan",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/9b52494c5001834809859448065/S7eTJ67rBLUA.mp4",
    videoVariants: [
      {
        title: "中文导诊助手",
        description: "面向中文就诊用户，展示挂号缴费、门诊诊室、检查科室和药房等关键导诊路径。",
        url: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/9b52494c5001834809859448065/S7eTJ67rBLUA.mp4",
        poster: "/images/cases/medical-guide-zh-preview.png",
        videoId: "case-medical-guide-assistant-zh",
      },
      {
        title: "English medical guide",
        description: "为外籍患者或国际医疗服务场景提供英文导诊说明，覆盖问诊入口、科室导航和检查咨询。",
        url: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/82952c555001834809852510401/uTMRhy1wCnoA.mp4",
        poster: "/images/cases/medical-guide-en-preview.png",
        videoId: "case-medical-guide-assistant-en",
      },
    ],
    sections: [
      {
        title: "场景挑战",
        body: "医院导诊需要把流程、地点、时间和注意事项讲清楚，同时保持服务语气稳定，避免用户在复杂流程里反复询问。",
      },
      {
        title: "适合扩展",
        body: "可以接入医院知识库、科室导航、检查须知、挂号规则和多语言问答，让数字人承担高频咨询和基础分诊前置服务。",
      },
      {
        title: "推荐模型",
        body: "推荐 QuickTalk / FlashTalk：先快速验证导诊脚本和服务流程，再根据大厅屏幕、服务终端或线上入口的画质要求升级。",
      },
    ],
    outcomes: ["高频导诊问题自动化", "减少服务台重复咨询", "支持中英文患者服务"],
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
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/1006e25f5001834806728756004/iscjqpxwBUAA.mp4",
    sections: [
      {
        title: "场景挑战",
        body: "播报类内容需要稳定形象、清晰声音和长文本输出能力，还要便于切换语言、栏目和人物设定。",
      },
      {
        title: "适合扩展",
        body: "可以接入新闻 CMS、脚本审核、多语言播报和栏目模板，把文本生成、播报和录制拆成更稳定的生产流程。",
      },
      {
        title: "推荐模型",
        body: "推荐 QuickTalk / FlashTalk：前者适合本地快速验证，后者更适合长文本播报、稳定口型和栏目化内容输出。",
      },
    ],
    outcomes: ["长文本播报更稳定", "主播形象可切换", "适合栏目化内容生产"],
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
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/7865fde85001834806726853449/Uxof3qJw9oMA.mp4",
    sections: [
      {
        title: "场景挑战",
        body: "陪伴类产品对回复节奏、打断体验和字幕反馈要求更高，需要保证会话状态与音视频输出一致。",
      },
      {
        title: "适合扩展",
        body: "可以接入长期记忆、私有知识库、角色安全边界和多轮对话策略，让陪伴体验更连续、更可控。",
      },
      {
        title: "推荐模型",
        body: "推荐 QuickTalk + 本地音频链路：响应快、部署轻，适合先验证多轮对话、打断控制和角色陪伴体验。",
      },
    ],
    outcomes: ["多轮会话更自然", "打断和字幕可观察", "便于私有化验证"],
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
    image: "/images/cases/anime-talk-show-preview.png",
    accent: "violet",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/53e1ae875001834806729384095/y2rxrMrkX9AA.mp4",
    sections: [
      {
        title: "场景挑战",
        body: "角色内容经常需要快速试错，重点不只是画质，还包括人设、台词节奏和实时互动反馈。",
      },
      {
        title: "适合扩展",
        body: "可以加入多角色切换、节目脚本、弹幕互动和内容素材库，让角色 IP 从 Demo 走向持续内容生产。",
      },
      {
        title: "推荐模型",
        body: "推荐 Mock 首跑 + QuickTalk：先低成本验证人设和互动节奏，再按画质需求切换本地或高质量后端。",
      },
    ],
    outcomes: ["快速验证角色人设", "降低内容试错成本", "后续可扩展多角色互动"],
  },
  {
    slug: "creative-performance",
    title: "创意演唱 / 模仿秀",
    eyebrow: "创意实验",
    category: "experiment",
    categoryLabel: "创意实验",
    description:
      "适合验证声音风格、形象表演和创意互动内容，用同一产品壳快速切换模型后端。",
    detailIntro:
      "用于声音、形象和表演内容的实验场，让团队快速比较不同模型、音色和脚本组合的表现。",
    route: "Local 或 OmniRT",
    features: ["声音风格", "角色演绎", "后端切换"],
    image: "/images/cases/creative-performance-preview.png",
    accent: "rose",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/26e7d30f5001834806725677498/DDWi04ozqdsA.mp4",
    sections: [
      {
        title: "场景挑战",
        body: "创意内容变化快，常常需要比较不同声音、画面和脚本，不适合每次都重搭一套演示系统。",
      },
      {
        title: "适合扩展",
        body: "可以加入素材管理、内容模板和录制导出，把实验结果沉淀成短视频、直播切片或角色表演素材。",
      },
      {
        title: "推荐模型",
        body: "推荐 Local / OmniRT：本地路线适合快速试错，OmniRT 更适合对画质、表演稳定性和最终交付效果要求更高的内容。",
      },
    ],
    outcomes: ["快速比较模型效果", "适合内容团队试错", "可沉淀演示模板"],
  },
  {
    slug: "mobile-recording",
    title: "更多有趣视频制作中...",
    eyebrow: "Coming soon",
    category: "experiment",
    categoryLabel: "端到端演示",
    description: "Coming soon",
    detailIntro: "案例内容正在整理中",
    route: "Coming soon",
    features: ["Coming soon"],
    image: "/images/cases/coming-soon.svg",
    accent: "slate",
    comingSoon: true,
    sections: [
      {
        title: "Coming soon",
        body: "该场景资源正在整理中。",
      },
      {
        title: "Coming soon",
        body: "后续会补充可用模型、演示素材和配置建议。",
      },
      {
        title: "推荐模型",
        body: "Coming soon。",
      },
    ],
    outcomes: ["案例内容即将补充", "演示视频整理中", "暂不开放详情页"],
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
    outcome: "10 分钟内看到可演示的原型",
  },
  {
    name: "本地离线与私有化验证",
    badge: "Local GPU",
    description:
      "在自己的GPU机器或工作站上运行实时数字人渲染模型，支持素材、音频和会话等各样功能。",
    models: "QuickTalk / Wav2Lip / MuseTalk 本地后端",
    bestFor: "内容团队、私有化验证、需要离线运行和自定义形象的项目",
    outcome: "单机环境里生成真实数字人渲染",
  },
  {
    name: "高质量生产与交付",
    badge: "Inference Serer",
    description:
      "部署分离数字服务和模型推理服务，获取更高质量的数字人渲染效果，适合企业交付、多卡推理和长期服务。",
    models: "FlashTalk / FlashHead",
    bestFor: "画质要求高、并发更高、需要稳定服务边界的团队",
    outcome: "高质量、生产级数字人效果",
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
      "我们先用 Mock 模式确认交互和脚本，再切到本地模型验证画面效果，整条链路很适合做数字人产品原型。",
    name: "内容创作团队",
    role: "短视频与直播场景",
    avatar: "/images/avatars/content-team.svg",
  },
  {
    quote:
      "OpenTalking 把 LLM、语音、字幕和 WebRTC 播放整理得比较清楚，做私有化演示和客户交付时沟通成本低了很多。",
    name: "企业交付团队",
    role: "本地部署与方案验证",
    avatar: "/images/avatars/delivery-team.svg",
  },
  {
    quote:
      "后端模型可以替换，前端事件也足够透明，我们能在现有工程里快速接入自己的数字人模型和业务流程。",
    name: "社区开发者",
    role: "模型适配与二次开发",
    avatar: "/images/avatars/developer.svg",
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
    value: "opentalking-ai@outlook.com",
    href: "mailto:opentalking-ai@outlook.com",
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
