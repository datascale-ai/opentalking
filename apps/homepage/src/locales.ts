import {
  capabilities as zhCapabilities,
  caseCategories as zhCaseCategories,
  caseStudies as zhCaseStudies,
  contactChannels as zhContactChannels,
  deploymentRoutes as zhDeploymentRoutes,
  navItems as zhNavItems,
  productLinks,
  testimonials as zhTestimonials,
  type Capability,
  type CaseStudy,
  type DeploymentRoute,
  type NavItem,
  type Testimonial,
} from "./content";

export type Language = "zh" | "en";

type CaseCategory = {
  key: (typeof zhCaseCategories)[number]["key"];
  label: string;
};

export type SiteContent = {
  navItems: NavItem[];
  capabilities: Capability[];
  caseCategories: readonly CaseCategory[];
  caseStudies: CaseStudy[];
  deploymentRoutes: DeploymentRoute[];
  testimonials: Testimonial[];
  contactChannels: typeof zhContactChannels;
  docsHref: string;
  navbar: {
    tagline: string;
    languageLabel: string;
    menuOpen: string;
    menuClose: string;
  };
  home: {
    heroTitleTop: string;
    heroTitleAccent: string;
    heroDescription: string;
    demoCta: string;
    quickStartCta: string;
    capabilityEyebrow: string;
    capabilityTitle: string;
    capabilityDescription: string;
    showcaseEyebrow: string;
    showcaseTitle: string;
    showcaseDescription: string;
    allCasesCta: string;
    deploymentEyebrow: string;
    deploymentTitle: string;
    deploymentDescription: string;
    deploymentDocsCta: string;
    wordEyebrow: string;
    wordTitle: string;
    wordDescription: string;
    feedbackLabel: string;
    finalCtaTitle: string;
    finalCtaDescription: string;
    finalCasesCta: string;
    githubRepoCta: string;
  };
  heroStage: {
    sessionLabel: string;
    recordingLabel: string;
    portraitLabel: string;
    productPanelTitle: string;
    pipelineItems: Array<{
      label: string;
      value: string;
    }>;
    highlights: Array<{
      title: string;
      meta: string;
    }>;
  };
  showcase: {
    featuredLabel: string;
    openResourceCta: string;
    previousLabel: string;
    nextLabel: string;
  };
  deploymentCard: {
    outcomeLabel: string;
    modelsLabel: string;
    bestForLabel: string;
  };
  casesPage: {
    eyebrow: string;
    title: string;
    description: string;
    contributionLine: string;
    filterTitle: string;
    resourceNote: string;
    comingSoonLabel: string;
  };
  caseDetail: {
    backToLibrary: string;
    videoTitle: string;
    outcomesTitle: string;
    docsCta: string;
    relatedEyebrow: string;
    relatedTitle: string;
  };
  about: {
    contactEyebrow: string;
    titlePrefix: string;
    titleBrand: string;
    titleSuffix: string;
    intro: string;
    qqTitle: string;
    qqValue: string;
    qqDescription: string;
    collaborationEyebrow: string;
    collaborationTitle: string;
    collaborationDescription: string;
    cooperationAreas: Array<{
      title: string;
      copy: string;
    }>;
    communityEyebrow: string;
    communityTitle: string;
    communityDescription: string;
    githubCta: string;
    docsCta: string;
  };
  footer: {
    tagline: string;
    description: string;
    siteTitle: string;
    resourcesTitle: string;
    docsPrimary: string;
    docsSecondary: string;
    communityTitle: string;
    communityName: string;
    communityDescription: string;
  };
};

const enNavItems: NavItem[] = [
  { key: "home", label: "Home" },
  { key: "docs", label: "Docs" },
  { key: "cases", label: "Cases" },
  { key: "about", label: "About" },
];

const enCaseCategories = [
  { key: "all", label: "All" },
  { key: "livestream", label: "Live commerce" },
  { key: "media", label: "Media" },
  { key: "tourism", label: "Tourism" },
  { key: "healthcare", label: "Healthcare" },
  { key: "government", label: "Government services" },
  { key: "character", label: "Character content" },
  { key: "companion", label: "Companion" },
  { key: "experiment", label: "Creative demos" },
] as const;

const enCapabilities: Capability[] = [
  {
    title: "Real-time Conversation Flow",
    description:
      "Tie together user input, session state, LLM responses, streaming voice, and WebRTC playback in one product-ready loop.",
    meta: "Session / LLM / WebRTC",
    icon: "radio",
  },
  {
    title: "Avatar and Voice Profiles",
    description:
      "Define characters, voices, TTS/STT providers, and model backends so teams can test different avatar experiences quickly.",
    meta: "Avatar / Voice / Provider",
    icon: "user",
  },
  {
    title: "Captions and Turn Control",
    description:
      "Surface caption events, speaking state, and interruption controls so real-time conversations stay visible and responsive.",
    meta: "Events / Turn-taking",
    icon: "captions",
  },
  {
    title: "Pluggable Model Backends",
    description:
      "Start with a lightweight demo, then move to higher-quality inference as your compute, latency, and visual requirements grow.",
    meta: "wav2lip / flashtalk",
    icon: "plug",
  },
];

const enCaseStudies: CaseStudy[] = [
  {
    slug: "ecommerce-livestream",
    title: "Live Commerce Host",
    eyebrow: "High-frequency interaction",
    category: "livestream",
    categoryLabel: "Live commerce",
    description:
      "Combine product narration, audience Q&A, captions, speech, and real-time avatar video in one live commerce workflow.",
    detailIntro:
      "Build an interactive AI host that can follow product scripts, answer audience questions, and present offers with synchronized voice and video.",
    route: "Two-view live commerce demo",
    features: ["Real-time Q&A", "Voice persona", "Caption sync"],
    image: "/images/cases/ecommerce-live-front-preview.png",
    accent: "amber",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/742bcb745001834809665869890/vkxsFysr5REA.mp4",
    videoVariants: [
      {
        title: "Front-facing livestream",
        description: "A direct host view for product explanation, offer highlights, and live commerce UI elements.",
        url: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/742bcb745001834809665869890/vkxsFysr5REA.mp4",
        embedUrl: "https://player.bilibili.com/player.html?bvid=BV1jhT76hENu&page=1&autoplay=0&high_quality=1&danmaku=0",
        poster: "/images/cases/ecommerce-live-front-preview.png",
        videoId: "case-ecommerce-livestream-front",
      },
      {
        title: "Angled selling setup",
        description: "A more realistic camera angle with visible products, presenter movement, and livestream staging.",
        url: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/cca683435001834809670031995/aswhi0HNmYkA.mp4",
        poster: "/images/cases/ecommerce-live-angle-preview.png",
        videoId: "case-ecommerce-livestream-angle",
      },
    ],
    sections: [
      {
        title: "Scenario Challenge",
        body: "Live commerce needs continuous narration, fast Q&A, and a steady speaking rhythm. A standalone avatar model is not enough to cover the full interaction loop.",
      },
      {
        title: "Extension Path",
        body: "Connect product knowledge, audience comments, promotion scripts, and multiple host profiles to turn the demo into a reusable live commerce template.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: OmniRT / FlashTalk. They provide steadier lip sync and visual quality for long-running livestreams, branded commerce, and client-facing demos.",
      },
    ],
    outcomes: ["Automated product narration", "Real-time audience response", "Synchronized captions and video"],
  },
  {
    slug: "huangshan-tour-guide",
    title: "Huangshan Tourism Guide",
    eyebrow: "Immersive narration",
    category: "tourism",
    categoryLabel: "Tourism",
    description:
      "Use an avatar guide to introduce scenic areas, travel routes, cultural highlights, and destination stories.",
    detailIntro:
      "This Huangshan example combines scenic footage, guide narration, and a digital presenter for visitor centers, city exhibitions, and online tourism campaigns.",
    route: "QuickTalk / FlashTalk",
    features: ["Scenic narration", "Immersive visuals", "Multilingual-ready"],
    image: "/images/cases/huangshan-guide-preview.png",
    accent: "mint",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/742bcf735001834809665869970/T9jkqMRNCacA.mp4",
    sections: [
      {
        title: "Scenario Challenge",
        body: "Tourism videos need clear destination storytelling, strong visuals, and a consistent narration rhythm, while updates can be costly with traditional shoots.",
      },
      {
        title: "Extension Path",
        body: "Connect destination knowledge, route recommendations, multilingual narration, and visitor Q&A to turn a video into an interactive digital guide.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: QuickTalk / FlashTalk. Start by validating narration and scene composition, then upgrade quality for exhibition screens or destination campaigns.",
      },
    ],
    outcomes: ["Turn scenic content into guided video", "Reuse destination scripts", "Extend to multilingual Q&A later"],
  },
  {
    slug: "medical-guide-assistant",
    title: "Medical Guidance Assistant",
    eyebrow: "Patient guidance",
    category: "healthcare",
    categoryLabel: "Healthcare",
    description:
      "Use an avatar assistant for hospital lobbies, online care entry points, department navigation, and patient service guidance.",
    detailIntro:
      "This medical guidance assistant combines avatar narration, patient flow guidance, department navigation, and multilingual support for hospital service desks, digital care portals, and health platforms.",
    route: "Chinese and English guidance demo",
    features: ["Patient guidance", "Department navigation", "Bilingual service"],
    image: "/images/cases/medical-guide-en-preview.png",
    accent: "cyan",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/82952c555001834809852510401/uTMRhy1wCnoA.mp4",
    videoVariants: [
      {
        title: "English medical guide",
        description: "Guide international patients through consultation entry points, department navigation, and examination support.",
        url: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/82952c555001834809852510401/uTMRhy1wCnoA.mp4",
        poster: "/images/cases/medical-guide-en-preview.png",
        videoId: "case-medical-guide-assistant-en",
      },
      {
        title: "Chinese guidance assistant",
        description: "Help Chinese-speaking patients understand registration, payment, clinic rooms, examination departments, and pharmacy routes.",
        url: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/9b52494c5001834809859448065/S7eTJ67rBLUA.mp4",
        poster: "/images/cases/medical-guide-zh-preview.png",
        videoId: "case-medical-guide-assistant-zh",
      },
    ],
    sections: [
      {
        title: "Scenario Challenge",
        body: "Patient guidance needs to explain procedures, locations, timing, and preparation notes clearly while keeping the service tone consistent.",
      },
      {
        title: "Extension Path",
        body: "Connect hospital knowledge bases, department maps, examination instructions, registration rules, and multilingual Q&A to handle frequent service questions.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: QuickTalk / FlashTalk. Validate scripts and service flows first, then upgrade quality for lobby screens, kiosks, or online care portals.",
      },
    ],
    outcomes: ["Automate frequent guidance questions", "Reduce repetitive front-desk workload", "Support bilingual patient service"],
  },
  {
    slug: "dual-news-anchor",
    title: "Two-Anchor News Broadcast",
    eyebrow: "Studio broadcast",
    category: "media",
    categoryLabel: "Media broadcast",
    description:
      "Create a two-anchor studio format for news programs, company updates, and topical briefings with richer visual rhythm.",
    detailIntro:
      "This two-anchor news broadcast shows how OpenTalking can turn scripts, presenter personas, and studio-style visuals into a more complete program format.",
    route: "FlashTalk / OmniRT",
    features: ["Two-anchor scene", "Program scripts", "Stable delivery"],
    image: "/images/cases/dual-news-anchor-preview.png",
    accent: "violet",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/d3cd4cf35001834810577009103/pSgQNxLh7R8A.mp4",
    sections: [
      {
        title: "Scenario Challenge",
        body: "News content needs more than clear speech and lip sync. A two-anchor setup supports openings, topic handoffs, and program-style delivery with a more natural studio rhythm.",
      },
      {
        title: "Extension Path",
        body: "Connect news scripts, program templates, multiple voice personas, and review workflows to turn a single demo into a repeatable broadcast production pipeline.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: FlashTalk / OmniRT. They are better suited for two-presenter visuals, long-form narration, and program-style output where visual consistency matters.",
      },
    ],
    outcomes: ["Richer broadcast visuals", "Program-ready content workflow", "Expandable roles and voices"],
  },
  {
    slug: "news-anchor",
    title: "Museum Artifact Guide",
    eyebrow: "Cultural guide",
    category: "tourism",
    categoryLabel: "Tourism",
    description:
      "Use an avatar guide for museums, exhibitions, and cultural spaces to explain artifact context, historical background, and curated highlights.",
    detailIntro:
      "This museum artifact guide combines exhibit knowledge, narration scripts, and avatar presentation so visitors can understand cultural stories with less friction.",
    route: "Knowledge base + FlashTalk",
    features: ["Artifact knowledge", "Exhibition narration", "Multilingual-ready"],
    image: "/images/cases/museum-artifact-guide-preview.png",
    accent: "mint",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/6e5ec39a5001834810745706622/JafPI96NJ3MA.mp4",
    sections: [
      {
        title: "Scenario Challenge",
        body: "Museum guidance needs accurate knowledge, a clear narrative rhythm, and an approachable tone. Traditional videos are slow to update and hard to adapt across themes or languages.",
      },
      {
        title: "Extension Path",
        body: "Connect artifact knowledge, curator scripts, retrieval-based Q&A, and multilingual voices so one digital guide can be reused across galleries and extended into interactive tours.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: FlashTalk / OmniRT. They are better suited for exhibition screens, cultural media, and high-quality guide videos where visual stability and voice quality matter.",
      },
    ],
    outcomes: ["Lower guide-video production cost", "Knowledge-base driven updates", "Useful for museums and online cultural media"],
  },
  {
    slug: "government-service-guide",
    title: "Government Service Guide",
    eyebrow: "Public service",
    category: "government",
    categoryLabel: "Government services",
    description:
      "Use an avatar assistant for service halls, online portals, and self-service kiosks to explain procedures, required materials, and service paths.",
    detailIntro:
      "This government service guide turns policy instructions, document checklists, service counters, and frequent questions into a clearer avatar-led experience.",
    route: "Knowledge base + private deployment",
    features: ["Procedure guidance", "Material checklist", "Policy Q&A"],
    image: "/images/cases/government-service-guide-preview.jpg",
    accent: "cyan",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/c6e8617c5001834810743173763/AyYa9BzYNj4A.mp4",
    sections: [
      {
        title: "Scenario Challenge",
        body: "Public-service questions are frequent and detail-heavy. Citizens often need repeated clarification on materials, counters, deadlines, and eligibility rules.",
      },
      {
        title: "Extension Path",
        body: "Connect policy knowledge, service procedures, form examples, and hall navigation so the avatar can handle frequent questions across online and offline touchpoints.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: QuickTalk / FlashTalk with private deployment. Validate the process and knowledge flow first, then choose a deployment route based on intranet, privacy, and terminal requirements.",
      },
    ],
    outcomes: ["Reduce repetitive service questions", "Make procedures easier to understand", "Ready for portals and service kiosks"],
  },
  {
    slug: "news-anchor",
    title: "News Anchor",
    eyebrow: "Stable narration",
    category: "media",
    categoryLabel: "Media broadcast",
    description:
      "For news updates, announcements, and branded programs that need stable avatars, clear speech, and predictable delivery.",
    detailIntro:
      "Organize scripts, anchor identity, voice, and real-time video output for company updates, market briefs, course news, and branded programming.",
    route: "QuickTalk / FlashTalk",
    features: ["High-quality avatar", "Long-form narration", "WebRTC playback"],
    image: "/images/cases/news-anchor.jpeg",
    accent: "cyan",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/1006e25f5001834806728756004/iscjqpxwBUAA.mp4",
    sections: [
      {
        title: "Scenario Challenge",
        body: "Broadcast content needs a consistent face, clear voice, and reliable long-form narration, while still allowing teams to switch languages, programs, and personas.",
      },
      {
        title: "Extension Path",
        body: "Connect a news CMS, script review, multilingual narration, and program templates to make writing, recording, and publishing easier to manage.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: QuickTalk / FlashTalk. QuickTalk works well for local validation, while FlashTalk is better for long-form narration and program-style output.",
      },
    ],
    outcomes: ["More stable long-form narration", "Switchable anchor identity", "Ready for program-style content"],
  },
  {
    slug: "companion-character",
    title: "Companion Character",
    eyebrow: "Natural dialogue",
    category: "companion",
    categoryLabel: "Companion",
    description:
      "For companion, coaching, and training products where interruption handling, response timing, captions, and session memory all matter.",
    detailIntro:
      "Combine persistent dialogue, lightweight guidance, voice input, and avatar feedback for companion and training prototypes.",
    route: "Local audio + QuickTalk",
    features: ["Multi-turn dialogue", "Voice input", "Interruption control"],
    image: "/images/cases/companion.jpeg",
    accent: "mint",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/7865fde85001834806726853449/Uxof3qJw9oMA.mp4",
    sections: [
      {
        title: "Scenario Challenge",
        body: "Companion products are sensitive to response timing, interruptions, and caption feedback, so session state and audiovisual output need to stay in sync.",
      },
      {
        title: "Extension Path",
        body: "Add long-term memory, private knowledge, safety boundaries, and dialogue policies so the companion experience feels continuous and controllable.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: QuickTalk with a local audio path. It keeps latency low and is a good first step for validating dialogue, interruption handling, and companion behavior.",
      },
    ],
    outcomes: ["More natural multi-turn dialogue", "Observable interruption and captions", "Private deployment friendly"],
  },
  {
    slug: "anime-talk-show",
    title: "Animated Talk Show",
    eyebrow: "Character content",
    category: "character",
    categoryLabel: "Character content",
    description:
      "Connect character settings, scripts, and real-time voice to validate interactive content formats quickly.",
    detailIntro:
      "Bring a character concept to life by combining persona design, scripts, voice style, and avatar video in an interactive show format.",
    route: "Mock first, then Local",
    features: ["Persona design", "Creative scripts", "Fast validation"],
    image: "/images/cases/anime-talk-show-preview.png",
    accent: "violet",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/53e1ae875001834806729384095/y2rxrMrkX9AA.mp4",
    sections: [
      {
        title: "Scenario Challenge",
        body: "Character content depends on fast iteration. Visual quality matters, but persona, line delivery, and real-time feedback often decide whether the format works.",
      },
      {
        title: "Extension Path",
        body: "Add multi-character switching, show scripts, audience interaction, and an asset library to build a repeatable character content workflow.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: Mock first, then QuickTalk. Validate persona and interaction rhythm at low cost before switching to a local or higher-quality backend.",
      },
    ],
    outcomes: ["Validate character persona quickly", "Lower content iteration cost", "Expandable multi-role interaction"],
  },
  {
    slug: "creative-performance",
    title: "Creative Singing / Imitation",
    eyebrow: "Creative experiment",
    category: "experiment",
    categoryLabel: "Creative demo",
    description:
      "Experiment with voice style, avatar performance, and interactive content using the same product shell and switchable model backends.",
    detailIntro:
      "A creative playground for comparing models, voices, scripts, and avatar performances without rebuilding the demo each time.",
    route: "Local or OmniRT",
    features: ["Voice style", "Character performance", "Backend switching"],
    image: "/images/cases/creative-performance-preview.png",
    accent: "rose",
    videoUrl: "https://1441945933.vod-qcloud.com/0b66444dvodcq1441945933/26e7d30f5001834806725677498/DDWi04ozqdsA.mp4",
    sections: [
      {
        title: "Scenario Challenge",
        body: "Creative concepts change quickly, and teams often need to compare voices, visuals, and scripts without rebuilding the demo system every time.",
      },
      {
        title: "Extension Path",
        body: "Add asset management, templates, and recording export so experiments can become reusable clips, livestream assets, or character performance material.",
      },
      {
        title: "Recommended Model",
        body: "Recommended: Local or OmniRT. Local backends are useful for fast iteration, while OmniRT is better when visual quality and delivery stability matter.",
      },
    ],
    outcomes: ["Compare model results quickly", "Good for content-team iteration", "Reusable demo templates"],
  },
  {
    slug: "mobile-recording",
    title: "More interesting video...",
    eyebrow: "Coming soon",
    category: "experiment",
    categoryLabel: "End-to-end demo",
    description: "Coming soon.",
    detailIntro: "This case is being prepared. We will add the mobile recording flow, demo media, and deployment notes later.",
    route: "Coming soon",
    features: ["Coming soon"],
    image: "/images/cases/coming-soon.svg",
    accent: "slate",
    comingSoon: true,
    sections: [
      {
        title: "Coming soon",
        body: "This scenario resource is being prepared.",
      },
      {
        title: "Coming soon",
        body: "We will add model suggestions, demo assets, and configuration notes later.",
      },
      {
        title: "Recommended Model",
        body: "Coming soon.",
      },
    ],
    outcomes: ["Case content coming soon", "Demo media in progress", "Detail page currently disabled"],
  },
];

const enDeploymentRoutes: DeploymentRoute[] = [
  {
    name: "Fast Trial and Demo",
    badge: "No GPU",
    description:
      "Run the conversation, speech, captions, and browser playback experience before preparing model weights or inference services.",
    models: "Static avatar image + real LLM/TTS/WebRTC path",
    bestFor: "Product teams, solution demos, and first-time OpenTalking evaluations",
    outcome: "Get a demo-ready prototype running in minutes",
  },
  {
    name: "Local Offline Validation",
    badge: "Local GPU",
    description:
      "Run real-time avatar rendering on your own GPU workstation or server while keeping assets, audio, and sessions local.",
    models: "QuickTalk / Wav2Lip / MuseTalk local backends",
    bestFor: "Content teams, offline workflows, private validation, and custom avatar projects",
    outcome: "Generate avatar video in a controlled local environment",
  },
  {
    name: "Production Delivery",
    badge: "Inference Server",
    description:
      "Separate the product layer from model inference for better visual quality, multi-GPU scaling, and stable long-running service.",
    models: "FlashTalk / FlashHead",
    bestFor: "Teams that need higher visual quality, concurrency, and clearer service boundaries",
    outcome: "Production-ready AI avatar output",
  },
];

const enTestimonials: Testimonial[] = [
  {
    quote:
      "We validated scripts and interaction in Mock mode first, then switched to a local model for visual quality checks. That loop is exactly what early avatar prototyping needs.",
    name: "Content Team",
    role: "Short video and livestream",
    avatar: "/images/avatars/content-team.svg",
  },
  {
    quote:
      "OpenTalking makes the LLM, voice, captions, and WebRTC flow easy to explain, which helped us align quickly on private demos and client delivery.",
    name: "Delivery Team",
    role: "Private deployment",
    avatar: "/images/avatars/delivery-team.svg",
  },
  {
    quote:
      "The model backend is replaceable, and the frontend events are clear enough for us to connect our own avatar model and business workflow quickly.",
    name: "Community Developer",
    role: "Model adaptation",
    avatar: "/images/avatars/developer.svg",
  },
];

const enContactChannels: typeof zhContactChannels = [
  {
    title: "QQ Community",
    description: "Discuss real-time avatars, FlashTalk, OmniRT, model deployment, and product scenarios.",
    value: "",
    href: "",
    kind: "qq",
  },
  {
    title: "Partnership",
    description: "Private deployment, scenario co-creation, model integration, and enterprise partnerships.",
    value: "opentalking-ai@outlook.com",
    href: "mailto:opentalking-ai@outlook.com",
    kind: "email",
  },
  {
    title: "GitHub",
    description: "Open issues, submit PRs, share scenarios, and help improve the docs.",
    value: "datascale-ai/opentalking",
    href: productLinks.github,
    kind: "github",
  },
];

export const siteContent: Record<Language, SiteContent> = {
  zh: {
    navItems: zhNavItems,
    capabilities: zhCapabilities,
    caseCategories: zhCaseCategories,
    caseStudies: zhCaseStudies,
    deploymentRoutes: zhDeploymentRoutes,
    testimonials: zhTestimonials,
    contactChannels: zhContactChannels,
    docsHref: productLinks.docsZh,
    navbar: {
      tagline: "Real-time avatar platform",
      languageLabel: "切换语言",
      menuOpen: "打开导航",
      menuClose: "关闭导航",
    },
    home: {
      heroTitleTop: "开源实时数字人",
      heroTitleAccent: "生成与对话框架",
      heroDescription:
        "从文本、语音到数字人视频，OpenTalking 帮你快速搭建可本地运行、可二次开发、可私有化部署的数字人应用。",
      demoCta: "看看 Demo",
      quickStartCta: "快速开始",
      capabilityEyebrow: "Product capability",
      capabilityTitle: "从对话到画面，核心链路一次跑通",
      capabilityDescription: "OpenTalking 把会话、语音、字幕、播放和模型服务串成完整的数字人产品链路。",
      showcaseEyebrow: "Showcase",
      showcaseTitle: "真实产品场景，为数字人服务而生",
      showcaseDescription: "用同一套编排层覆盖直播、文旅导览、医疗导诊、播报、陪伴、角色内容和端到端演示。",
      allCasesCta: "全部案例",
      deploymentEyebrow: "Deployment",
      deploymentTitle: "按你的需求匹配不同部署方式",
      deploymentDescription: "从快速演示、本地离线到高质量交付，沿着同一套链路逐步升级。",
      deploymentDocsCta: "查看部署文档",
      wordEyebrow: "Word of mouth",
      wordTitle: "看看用户们的口碑",
      wordDescription: "谁在使用它？",
      feedbackLabel: "使用反馈",
      finalCtaTitle: "也想试试自己的数字人应用？",
      finalCtaDescription: "来试试Demo，再选择模型、音色和业务场景定制你的角色。",
      finalCasesCta: "查看案例",
      githubRepoCta: "GitHub 仓库",
    },
    heroStage: {
      sessionLabel: "live-session: 24fps",
      recordingLabel: "实时录制演示",
      portraitLabel: "竖屏素材",
      productPanelTitle: "产品链路",
      pipelineItems: [
        { label: "LLM大脑", value: "Qwen / DeepSeek / GPT" },
        { label: "声音与字幕", value: "TTS / STT / 多音色 / 音色克隆" },
        { label: "数字人驱动", value: "QuickTalk / Wav2Lip / FlashTalk" },
        { label: "实时播放", value: "WebRTC audio/video" },
      ],
      highlights: [
        { title: "角色定制", meta: "Persona" },
        { title: "音色模仿", meta: "Voice clone" },
        { title: "记忆系统", meta: "Memory" },
        { title: "知识装载", meta: "Knowledge" },
      ],
    },
    showcase: {
      featuredLabel: "Featured scenario",
      openResourceCta: "查看资源页",
      previousLabel: "上一个案例",
      nextLabel: "下一个案例",
    },
    deploymentCard: {
      outcomeLabel: "预期效果",
      modelsLabel: "模型：",
      bestForLabel: "适合：",
    },
    casesPage: {
      eyebrow: "Customer stories",
      title: "行业场景与案例",
      description: "OpenTalking 在直播、播报、陪伴互动和内容生产中的应用落地。",
      contributionLine: "欢迎发现有趣的应用落地贡献给我们！",
      filterTitle: "场景分类",
      resourceNote: "每个案例沉淀业务背景、演示视频、实施方案与预期收益，便于快速判断是否适合你的场景。",
      comingSoonLabel: "Coming soon",
    },
    caseDetail: {
      backToLibrary: "返回案例库",
      videoTitle: "案例视频",
      outcomesTitle: "预期收益",
      docsCta: "查看部署文档",
      relatedEyebrow: "Related stories",
      relatedTitle: "继续查看相关场景",
    },
    about: {
      contactEyebrow: "Contact",
      titlePrefix: "联系",
      titleBrand: "OpenTalking",
      titleSuffix: "团队",
      intro: "无论是开源交流、私有化部署、模型接入还是场景共创，通过下面方式联系我们。",
      qqTitle: "QQ 交流群",
      qqValue: "QQ: 1103327938",
      qqDescription: "讨论部署、模型、产品场景和二次开发。",
      collaborationEyebrow: "Collaboration",
      collaborationTitle: "聊聊合作？",
      collaborationDescription: "如果你正在评估实时数字人产品、内容生产工具或私有化部署路线，欢迎找我们沟通合作。",
      cooperationAreas: [
        { title: "私有化部署与本地离线方案", copy: "围绕企业数据边界、GPU 资源和模型服务形态，评估从 Demo 到本地交付的部署路径。" },
        { title: "数字人模型、音色与形象接入", copy: "接入不同数字人驱动模型、TTS 音色和角色资产，让 OpenTalking 适配更多内容生产流程。" },
        { title: "直播、短视频、课程场景共创", copy: "把行业脚本、素材管理、演示视频和交互能力沉淀为可复用的数字人解决方案。" },
        { title: "开源二次开发与技术支持", copy: "面向产品团队和开发者，支持 API 集成、模型适配、部署经验和文档改进。" },
      ],
      communityEyebrow: "Open source community",
      communityTitle: "来与我们一起开源共建吧！",
      communityDescription: "如果你对数字人的应用也感兴趣，欢迎提交模型适配、部署经验、行业案例和文档改进，也欢迎把你基于 OpenTalking 做出的产品形态分享给社区。",
      githubCta: "GitHub 仓库",
      docsCta: "阅读文档",
    },
    footer: {
      tagline: "开源实时数字人生成与对话框架",
      description: "从 Demo、素材生产到私有化部署，帮助团队更快构建可落地的数字人应用。",
      siteTitle: "站点",
      resourcesTitle: "资源",
      docsPrimary: "中文文档",
      docsSecondary: "English Docs",
      communityTitle: "加入交流群",
      communityName: "AI 数字人交流群",
      communityDescription: "讨论部署、模型接入、内容场景和二次开发。",
    },
  },
  en: {
    navItems: enNavItems,
    capabilities: enCapabilities,
    caseCategories: enCaseCategories,
    caseStudies: enCaseStudies,
    deploymentRoutes: enDeploymentRoutes,
    testimonials: enTestimonials,
    contactChannels: enContactChannels,
    docsHref: productLinks.docsEn,
    navbar: {
      tagline: "Real-time avatar platform",
      languageLabel: "Switch language",
      menuOpen: "Open menu",
      menuClose: "Close menu",
    },
    home: {
      heroTitleTop: "Real-time",
      heroTitleAccent: "Avatar Platform",
      heroDescription:
        "OpenTalking helps teams build local, extensible, privately deployable avatar apps from text and voice to real-time video.",
      demoCta: "View demos",
      quickStartCta: "Quick start",
      capabilityEyebrow: "Product capability",
      capabilityTitle: "From conversation to video, in one flow",
      capabilityDescription: "OpenTalking connects dialogue, voice, captions, playback, and model services into a complete AI avatar workflow.",
      showcaseEyebrow: "Showcase",
      showcaseTitle: "Built for real avatar use cases",
      showcaseDescription: "Use the same orchestration layer for livestreaming, tourism guides, healthcare guidance, broadcast, companion experiences, character content, and end-to-end demos.",
      allCasesCta: "All cases",
      deploymentEyebrow: "Deployment",
      deploymentTitle: "Pick the right path for your stage",
      deploymentDescription: "Start with a quick demo, move to local offline validation, and upgrade to higher-quality delivery on the same architecture.",
      deploymentDocsCta: "Deployment docs",
      wordEyebrow: "Community voices",
      wordTitle: "What builders are saying",
      wordDescription: "Teams are using OpenTalking to prototype, customize, and ship AI avatar experiences.",
      feedbackLabel: "OpenTalking feedback",
      finalCtaTitle: "Ready to prototype your own avatar app?",
      finalCtaDescription: "Start from the demo, then bring in your model, voice, persona, and product workflow.",
      finalCasesCta: "View cases",
      githubRepoCta: "GitHub repo",
    },
    heroStage: {
      sessionLabel: "live-session: 24fps",
      recordingLabel: "Real-time Demo",
      portraitLabel: "Portrait asset",
      productPanelTitle: "Product pipeline",
      pipelineItems: [
        { label: "LLM Brain", value: "Qwen / DeepSeek / GPT" },
        { label: "Voice and Captions", value: "TTS / STT / Voice clone" },
        { label: "Avatar Driver", value: "QuickTalk / Wav2Lip / FlashTalk" },
        { label: "Real-time Playback", value: "WebRTC audio/video" },
      ],
      highlights: [
        { title: "Persona", meta: "Character" },
        { title: "Voice Clone", meta: "Voice" },
        { title: "Memory layer", meta: "Memory" },
        { title: "Knowledge Base", meta: "Context" },
      ],
    },
    showcase: {
      featuredLabel: "Featured scenario",
      openResourceCta: "Open resource",
      previousLabel: "Previous case",
      nextLabel: "Next case",
    },
    deploymentCard: {
      outcomeLabel: "Expected outcome",
      modelsLabel: "Models: ",
      bestForLabel: "Best for: ",
    },
    casesPage: {
      eyebrow: "Customer stories",
      title: "Use Cases and Stories",
      description: "Explore OpenTalking in livestreaming, broadcast, companion, and content production.",
      contributionLine: "Built something interesting with OpenTalking? We would love to feature it.",
      filterTitle: "Browse by scenario",
      resourceNote: "Each story captures the business context, demo media, implementation approach, and expected value so teams can evaluate fit quickly.",
      comingSoonLabel: "Coming soon",
    },
    caseDetail: {
      backToLibrary: "Back to cases",
      videoTitle: "Case video",
      outcomesTitle: "Expected outcomes",
      docsCta: "Deployment docs",
      relatedEyebrow: "Related stories",
      relatedTitle: "Explore related scenarios",
    },
    about: {
      contactEyebrow: "Contact",
      titlePrefix: "Contact the",
      titleBrand: "OpenTalking",
      titleSuffix: "Team",
      intro: "Reach out for open-source collaboration, private deployment, model integration, or new AI avatar scenarios.",
      qqTitle: "QQ Community",
      qqValue: "QQ: 1103327938",
      qqDescription: "Discuss deployment, models, product scenarios, and custom development.",
      collaborationEyebrow: "Collaboration",
      collaborationTitle: "Build together",
      collaborationDescription: "If your team is evaluating real-time avatar products, content workflows, or private deployment, we would be glad to talk.",
      cooperationAreas: [
        { title: "Private deployment and offline setup", copy: "Map the path from demo to local delivery around data boundaries, GPU resources, and model service architecture." },
        { title: "Avatar models, voices, and identity", copy: "Integrate avatar drivers, TTS voices, and character assets so OpenTalking fits more content workflows." },
        { title: "Livestream, short video, and learning scenarios", copy: "Turn scripts, asset management, demo videos, and interaction patterns into reusable AI avatar solutions." },
        { title: "Open-source development support", copy: "Work with teams and developers on API integration, model adaptation, deployment notes, and documentation improvements." },
      ],
      communityEyebrow: "Open source community",
      communityTitle: "Contribute to community",
      communityDescription: "Contribute model adapters, deployment guides, scenario demos, documentation improvements, or applications to OpenTalking!",
      githubCta: "GitHub repo",
      docsCta: "Read docs",
    },
    footer: {
      tagline: "Real-time AI avatar platform",
      description: "From demos and content production to private deployment, OpenTalking helps teams build shippable avatar applications faster.",
      siteTitle: "Site",
      resourcesTitle: "Resources",
      docsPrimary: "Chinese Docs",
      docsSecondary: "English Docs",
      communityTitle: "Join community",
      communityName: "AI Avatar QQ Group",
      communityDescription: "Discuss deployment, model integration, content scenarios, and custom development.",
    },
  },
};
