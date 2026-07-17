import { ArrowUpRight, GitFork, Github, Star, X } from "lucide-react";
import { useEffect, useState } from "react";
import { productLinks } from "../content";
import type { Language } from "../locales";

type GitHubRepoStats = {
  stars: number | null;
  forks: number | null;
  loading: boolean;
};

const githubApiUrl = "https://api.github.com/repos/datascale-ai/opentalking";
const githubApiProxyPath = "/github-api/repos/datascale-ai/opentalking";

const formatCount = (value: number | null) => {
  if (value === null) return null;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
};

const getGitHubStatsUrl = () => {
  const cacheBuster = `t=${Date.now()}`;
  const isLocalPreview = ["localhost", "127.0.0.1"].includes(window.location.hostname);

  return isLocalPreview
    ? `${githubApiUrl}?${cacheBuster}`
    : `${githubApiProxyPath}?${cacheBuster}`;
};

type GitHubStatsProps = {
  language: Language;
};

const starNudgeCopy = {
  zh: {
    dialogLabel: "GitHub Star 引导",
    closeLabel: "关闭 GitHub Star 引导",
    message: (
      <>
        如果你也喜欢这个项目
        <br />
        来 GitHub 点个🌟吧(=w=)
      </>
    ),
    cta: "打开 GitHub 仓库",
  },
  en: {
    dialogLabel: "GitHub Star prompt",
    closeLabel: "Close GitHub Star prompt",
    message: (
      <>
        If OpenTalking helps you,
        <br />
        give us a star on GitHub 🌟
      </>
    ),
    cta: "Open GitHub repo",
  },
} satisfies Record<Language, {
  dialogLabel: string;
  closeLabel: string;
  message: JSX.Element;
  cta: string;
}>;

export function GitHubStats({ language }: GitHubStatsProps) {
  const [stats, setStats] = useState<GitHubRepoStats>({
    stars: null,
    forks: null,
    loading: true,
  });
  const [showStarNudge, setShowStarNudge] = useState(false);
  const copy = starNudgeCopy[language];

  useEffect(() => {
    let isMounted = true;

    const loadGitHubStats = async () => {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 10000);

      try {
        const response = await fetch(getGitHubStatsUrl(), {
          cache: "no-store",
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error("GitHub stats unavailable");
        }

        const repo = (await response.json()) as {
          stargazers_count: number;
          forks_count: number;
        };

        if (!isMounted) return;

        const nextStats = {
          stars: repo.stargazers_count,
          forks: repo.forks_count,
        };

        setStats({
          ...nextStats,
          loading: false,
        });
      } catch {
        if (!isMounted) return;

        setStats({
          stars: null,
          forks: null,
          loading: false,
        });
      } finally {
        window.clearTimeout(timeout);
      }
    };

    void loadGitHubStats();

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <div className="relative">
      <button
        type="button"
        className="github-stats"
        aria-label="OpenTalking GitHub repository"
        aria-expanded={showStarNudge}
        aria-controls="github-star-nudge"
        onClick={() => setShowStarNudge((value) => !value)}
      >
        <span className="flex items-center gap-2 font-semibold">
          <Github className="h-4 w-4" />
          GitHub
        </span>
        <span className="github-stat-pill">
          <Star className="h-3.5 w-3.5" />
          {stats.loading ? "..." : (formatCount(stats.stars) ?? "null")}
        </span>
        <span className="github-stat-pill">
          <GitFork className="h-3.5 w-3.5" />
          {stats.loading ? "..." : (formatCount(stats.forks) ?? "null")}
        </span>
      </button>
      {showStarNudge ? (
        <div id="github-star-nudge" className="github-star-nudge" role="dialog" aria-label={copy.dialogLabel}>
          <button
            type="button"
            className="focus-ring absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-ink"
            aria-label={copy.closeLabel}
            onClick={() => setShowStarNudge(false)}
          >
            <X className="h-4 w-4" />
          </button>
          <p className="pr-7 text-sm font-semibold text-ink">{copy.message}</p>
          <p className="mt-2 text-xs leading-5 text-indigo-950/64">
          </p>
          <a
            className="btn-primary mt-3 h-10 w-full"
            href={productLinks.github}
            target="_blank"
            rel="noreferrer"
            onClick={() => setShowStarNudge(false)}
          >
            {copy.cta}
            <ArrowUpRight className="h-4 w-4" />
          </a>
        </div>
      ) : null}
    </div>
  );
}
