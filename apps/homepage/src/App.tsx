import { Footer } from "./components/Footer";
import { Navbar } from "./components/Navbar";
import { trackAnalyticsEvent } from "./analytics";
import type { PageKey } from "./content";
import { siteContent, type Language } from "./locales";
import { AboutPage } from "./pages/AboutPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { CasesPage } from "./pages/CasesPage";
import { HomePage } from "./pages/HomePage";
import { useEffect, useMemo, useState } from "react";

type RouteState = {
  language: Language;
  page: PageKey;
  caseSlug?: string;
};

const trimTrailingSlash = (path: string) => {
  if (path === "/") return path;
  return path.replace(/\/+$/, "");
};

const readRouteFromLocation = (): RouteState => {
  const path = trimTrailingSlash(window.location.pathname);
  const language: Language = path === "/en" || path.startsWith("/en/") ? "en" : "zh";
  const routePath = language === "en" ? trimTrailingSlash(path.replace(/^\/en(?=\/|$)/, "") || "/") : path;

  if (routePath === "/" || routePath === "") {
    return { language, page: "home" };
  }

  if (routePath === "/cases") {
    return { language, page: "cases" };
  }

  if (routePath === "/about") {
    return { language, page: "about" };
  }

  const caseMatch = routePath.match(/^\/cases\/([^/]+)$/);

  if (caseMatch?.[1]) {
    return {
      language,
      page: "caseDetail",
      caseSlug: decodeURIComponent(caseMatch[1]),
    };
  }

  return { language, page: "home" };
};

const getRoutePath = (route: RouteState) => {
  const prefix = route.language === "en" ? "/en" : "";

  if (route.page === "cases") return `${prefix}/cases`;
  if (route.page === "about") return `${prefix}/about`;
  if (route.page === "caseDetail" && route.caseSlug) {
    return `${prefix}/cases/${encodeURIComponent(route.caseSlug)}`;
  }

  return route.language === "en" ? "/en" : "/";
};

function App() {
  const [route, setRoute] = useState<RouteState>(() => readRouteFromLocation());
  const language = route.language;
  const content = siteContent[language];

  const currentPage = route.page;

  useEffect(() => {
    const handlePopState = () => {
      setRoute(readRouteFromLocation());
      window.scrollTo({ top: 0 });
    };

    window.addEventListener("popstate", handlePopState);

    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (currentPage !== "caseDetail") return;

    const targetCase = content.caseStudies.find((item) => item.slug === route.caseSlug);

    if (targetCase && !targetCase.comingSoon) return;

    const fallbackRoute: RouteState = { language, page: "cases" };
    window.history.replaceState(null, "", getRoutePath(fallbackRoute));
    setRoute(fallbackRoute);
  }, [content.caseStudies, currentPage, language, route.caseSlug]);

  useEffect(() => {
    trackAnalyticsEvent({
      eventName: "page_view",
      path: window.location.pathname,
      language,
      page: currentPage,
      caseSlug: route.caseSlug,
    });
  }, [currentPage, language, route.caseSlug]);

  const pushRoute = (nextRoute: RouteState) => {
    const nextPath = getRoutePath(nextRoute);

    if (window.location.pathname !== nextPath) {
      window.history.pushState(null, "", nextPath);
    }

    setRoute(nextRoute);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleNavigate = (page: PageKey) => {
    if (page === "docs") {
      window.open(content.docsHref, "_blank", "noopener,noreferrer");
      return;
    }

    pushRoute({ language, page });
  };

  const handleLanguageChange = (nextLanguage: Language) => {
    pushRoute({ ...route, language: nextLanguage });
  };

  const handleOpenCase = (slug: string) => {
    const targetCase = content.caseStudies.find((item) => item.slug === slug);

    if (targetCase?.comingSoon) {
      return;
    }

    pushRoute({ language, page: "caseDetail", caseSlug: slug });
  };

  const selectedCase = useMemo(
    () => content.caseStudies.find((item) => item.slug === route.caseSlug) ?? content.caseStudies[0],
    [content.caseStudies, route.caseSlug],
  );

  return (
    <div className="min-h-screen bg-mist text-ink">
      <Navbar
        currentPage={currentPage}
        language={language}
        navItems={content.navItems}
        onLanguageChange={handleLanguageChange}
        onNavigate={handleNavigate}
        copy={content.navbar}
      />
      <main>
        {currentPage === "home" ? (
          <HomePage content={content} onNavigate={handleNavigate} onOpenCase={handleOpenCase} />
        ) : null}
        {currentPage === "cases" ? (
          <CasesPage
            caseCategories={content.caseCategories}
            caseStudies={content.caseStudies}
            copy={content.casesPage}
            onOpenCase={handleOpenCase}
          />
        ) : null}
        {currentPage === "caseDetail" ? (
          <CaseDetailPage
            copy={content.caseDetail}
            item={selectedCase}
            relatedCases={content.caseStudies.filter((item) => item.slug !== selectedCase.slug).slice(0, 3)}
            onBack={() => handleNavigate("cases")}
            onOpenCase={handleOpenCase}
          />
        ) : null}
        {currentPage === "about" ? (
          <AboutPage contactChannels={content.contactChannels} copy={content.about} docsHref={content.docsHref} />
        ) : null}
      </main>
      <Footer copy={content.footer} language={language} navItems={content.navItems} onNavigate={handleNavigate} />
    </div>
  );
}

export default App;
