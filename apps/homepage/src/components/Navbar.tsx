import { Languages, Menu, PlayCircle, X } from "lucide-react";
import { useState } from "react";
import type { NavItem, PageKey } from "../content";
import type { Language, SiteContent } from "../locales";
import { GitHubStats } from "./GitHubStats";

type NavbarProps = {
  copy: SiteContent["navbar"];
  currentPage: PageKey;
  language: Language;
  navItems: NavItem[];
  onLanguageChange: (language: Language) => void;
  onNavigate: (page: PageKey) => void;
};

export function Navbar({
  copy,
  currentPage,
  language,
  navItems,
  onLanguageChange,
  onNavigate,
}: NavbarProps) {
  const [isOpen, setIsOpen] = useState(false);

  const handleNavigate = (page: PageKey) => {
    onNavigate(page);
    setIsOpen(false);
  };

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/90 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4">
        <button
          type="button"
          className="focus-ring flex cursor-pointer items-center gap-3 rounded-lg text-left"
          onClick={() => handleNavigate("home")}
        >
          <img
            src="/images/logo.png"
            alt="OpenTalking logo"
            className="h-10 w-10 rounded-lg border border-indigo-100 bg-white object-contain p-1 shadow-sm"
          />
          <span>
            <span className="block text-sm font-semibold tracking-normal text-ink">
              OpenTalking
            </span>
            <span className="hidden text-xs text-slate-500 sm:block">
              {copy.tagline}
            </span>
          </span>
        </button>

        <nav className="hidden items-center gap-1 md:flex">
          {navItems.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`focus-ring cursor-pointer rounded-lg px-4 py-2 text-sm font-medium transition ${
                currentPage === item.key || (currentPage === "caseDetail" && item.key === "cases")
                  ? "bg-ink text-white"
                  : "text-slate-600 hover:bg-slate-100 hover:text-ink"
              }`}
              onClick={() => handleNavigate(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="hidden items-center gap-2 lg:flex">
          <button
            type="button"
            className="language-toggle"
            aria-label={copy.languageLabel}
            onClick={() => onLanguageChange(language === "zh" ? "en" : "zh")}
          >
            <Languages className="h-4 w-4 text-cyanline" />
            <span className={language === "zh" ? "language-toggle-active" : ""}>中</span>
            <span className={language === "en" ? "language-toggle-active" : ""}>EN</span>
          </button>
          <GitHubStats />
        </div>

        <button
          type="button"
          className="focus-ring inline-flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg border border-slate-200 bg-white text-ink md:hidden"
          aria-label={isOpen ? copy.menuClose : copy.menuOpen}
          onClick={() => setIsOpen((value) => !value)}
        >
          {isOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {isOpen ? (
        <div className="border-t border-slate-200 bg-white px-5 py-4 md:hidden">
          <div className="grid gap-2">
            <button
              type="button"
              className="language-toggle mb-2 w-fit"
              aria-label={copy.languageLabel}
              onClick={() => onLanguageChange(language === "zh" ? "en" : "zh")}
            >
              <Languages className="h-4 w-4 text-cyanline" />
              <span className={language === "zh" ? "language-toggle-active" : ""}>中</span>
              <span className={language === "en" ? "language-toggle-active" : ""}>EN</span>
            </button>
            {navItems.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`focus-ring flex cursor-pointer items-center justify-between rounded-lg px-4 py-3 text-left text-sm font-medium ${
                  currentPage === item.key || (currentPage === "caseDetail" && item.key === "cases")
                    ? "bg-ink text-white"
                    : "bg-slate-50 text-slate-700"
                }`}
                onClick={() => handleNavigate(item.key)}
              >
                {item.label}
                {item.key === "home" ? <PlayCircle className="h-4 w-4" /> : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </header>
  );
}
