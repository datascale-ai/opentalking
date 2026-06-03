import { Footer } from "./components/Footer";
import { Navbar } from "./components/Navbar";
import { caseStudies, navItems, productLinks, type PageKey } from "./content";
import { AboutPage } from "./pages/AboutPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { CasesPage } from "./pages/CasesPage";
import { HomePage } from "./pages/HomePage";
import { useState } from "react";

function App() {
  const [currentPage, setCurrentPage] = useState<PageKey>("home");
  const [selectedCaseSlug, setSelectedCaseSlug] = useState(caseStudies[0].slug);

  const handleNavigate = (page: PageKey) => {
    if (page === "docs") {
      window.open(productLinks.docsZh, "_blank", "noopener,noreferrer");
      return;
    }

    setCurrentPage(page);
    if (page !== "caseDetail") {
      setSelectedCaseSlug(caseStudies[0].slug);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleOpenCase = (slug: string) => {
    setSelectedCaseSlug(slug);
    setCurrentPage("caseDetail");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const selectedCase =
    caseStudies.find((item) => item.slug === selectedCaseSlug) ?? caseStudies[0];

  return (
    <div className="min-h-screen bg-mist text-ink">
      <Navbar currentPage={currentPage} navItems={navItems} onNavigate={handleNavigate} />
      <main>
        {currentPage === "home" ? (
          <HomePage onNavigate={handleNavigate} onOpenCase={handleOpenCase} />
        ) : null}
        {currentPage === "cases" ? <CasesPage onOpenCase={handleOpenCase} /> : null}
        {currentPage === "caseDetail" ? (
          <CaseDetailPage
            item={selectedCase}
            relatedCases={caseStudies.filter((item) => item.slug !== selectedCase.slug).slice(0, 3)}
            onBack={() => handleNavigate("cases")}
            onOpenCase={handleOpenCase}
          />
        ) : null}
        {currentPage === "about" ? <AboutPage /> : null}
      </main>
      <Footer navItems={navItems} onNavigate={handleNavigate} />
    </div>
  );
}

export default App;
