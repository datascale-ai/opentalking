import unittest
from pathlib import Path


HOMEPAGE_ROOT = Path(__file__).resolve().parents[1]


class StudioCtaTests(unittest.TestCase):
    def test_homepage_exposes_localized_studio_cta(self):
        content = (HOMEPAGE_ROOT / "src/content.ts").read_text(encoding="utf-8")
        locales = (HOMEPAGE_ROOT / "src/locales.ts").read_text(encoding="utf-8")
        homepage = (HOMEPAGE_ROOT / "src/pages/HomePage.tsx").read_text(encoding="utf-8")

        self.assertIn('studio: "https://studio.opentalking.net/"', content)
        self.assertIn('quickStartCta: "立即体验"', locales)
        self.assertIn('quickStartCta: "Try Studio"', locales)
        self.assertIn('href={productLinks.studio}', homepage)
        self.assertIn('target="_blank"', homepage)
        self.assertIn('rel="noreferrer"', homepage)
        self.assertIn('className="btn-studio', homepage)
        self.assertNotIn('className="btn-studio-sheen"', homepage)
        self.assertIn("ArrowUpRight", homepage)

    def test_studio_cta_has_interval_pulse_and_hover_feedback(self):
        stylesheet = (HOMEPAGE_ROOT / "src/index.css").read_text(encoding="utf-8")

        self.assertIn(".btn-studio", stylesheet)
        self.assertIn("bg-indigo-50", stylesheet)
        self.assertIn("text-indigo-700", stylesheet)
        self.assertIn("hover:border-indigo-500", stylesheet)
        self.assertIn("@keyframes studio-cta-pulse", stylesheet)
        self.assertIn(
            "animation: studio-cta-pulse 4s ease-in-out infinite;",
            stylesheet,
        )
        self.assertIn("45%,", stylesheet)
        self.assertNotIn("studio-cta-sheen", stylesheet)
        self.assertIn("@media (prefers-reduced-motion: reduce)", stylesheet)


if __name__ == "__main__":
    unittest.main()
