import { Footer } from "./components/Footer";
import { Navbar } from "./components/Navbar";
import type { PageKey } from "./content";
import { siteContent, type Language } from "./locales";
import { AboutPage } from "./pages/AboutPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { CasesPage } from "./pages/CasesPage";
import { HomePage } from "./pages/HomePage";
import { useState } from "react";

function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const content = siteContent[language];
  const [currentPage, setCurrentPage] = useState<PageKey>("home");
  const [selectedCaseSlug, setSelectedCaseSlug] = useState(content.caseStudies[0].slug);

  const handleNavigate = (page: PageKey) => {
    if (page === "docs") {
      window.open(content.docsHref, "_blank", "noopener,noreferrer");
      return;
    }

    setCurrentPage(page);
    if (page !== "caseDetail") {
      setSelectedCaseSlug(content.caseStudies[0].slug);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleOpenCase = (slug: string) => {
    const targetCase = content.caseStudies.find((item) => item.slug === slug);

    if (targetCase?.comingSoon) {
      return;
    }

    setSelectedCaseSlug(slug);
    setCurrentPage("caseDetail");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const selectedCase =
    content.caseStudies.find((item) => item.slug === selectedCaseSlug) ?? content.caseStudies[0];

  return (
    <div className="min-h-screen bg-mist text-ink">
      <Navbar
        currentPage={currentPage}
        language={language}
        navItems={content.navItems}
        onLanguageChange={setLanguage}
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
      <Footer copy={content.footer} navItems={content.navItems} onNavigate={handleNavigate} />
    </div>
  );
}

export default App;
