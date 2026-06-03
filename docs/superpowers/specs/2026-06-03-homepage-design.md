# OpenTalking Homepage Design

Date: 2026-06-03
Status: Approved for implementation planning

## Goal

Create a standalone product website for OpenTalking in `apps/homepage` without changing the existing `apps/web` application.

The site should feel close to MinerU's clean, credible, open-source technology style, but lean more strongly toward product presentation. It should help visitors quickly understand that OpenTalking is an open-source real-time digital-human conversation pipeline that can move from demo validation to private deployment.

## Audience

- Product and solution evaluators who need to see what OpenTalking can do.
- Developers who need clear docs, deployment routes, and GitHub access.
- Teams evaluating local, remote, or private digital-human infrastructure.

## Visual Direction

Use a bright, product-led technology aesthetic:

- Mostly white and very light cool backgrounds.
- Sky blue and cyan/green accents for real-time AI and WebRTC signals.
- A small amount of warm CTA color for primary conversion moments.
- Clean spacing, restrained shadows, and cards with small radii around 8px.
- Product panels, demo stages, status chips, subtitle overlays, and architecture strips instead of decorative blobs.
- Typography should feel technical and approachable, using a sans font for content and a mono font for code/config snippets.

Avoid:

- A pure developer documentation landing page.
- A dark cinematic concept-site feeling as the default.
- Heavy gradients, decorative orb backgrounds, or oversized marketing cards.
- A single-hue blue-only palette.

## Information Architecture

The site contains four top-level pages:

1. Home
2. Docs
3. Cases
4. About

Navigation should be persistent across pages. Primary actions should include "Watch Demo" or "Experience Demo", "Get Started", "Documentation", and "GitHub". Links can point to the existing public docs site, GitHub repository, or local anchors where appropriate.

## Home Page

The home page should combine product proof and technical trust.

Sections:

1. Hero
   - Headline: OpenTalking as an open real-time digital-human product foundation.
   - Supporting copy: LLM, STT, TTS, WebRTC, avatar voices, interruption control, subtitles, and pluggable model backends.
   - CTAs: experience/watch demo, quick start/docs, GitHub.
   - Visual: product demo stage with an avatar/video area, live subtitles, latency/model-status chips, and a compact pipeline panel.

2. Product Capabilities
   - Real-time conversation orchestration.
   - Avatar and voice configuration.
   - Subtitle events and interruption control.
   - Local or remote synthesis backends.

3. Demo and Scenario Showcase
   - Reuse README scenario themes: real-time mobile recording, anime talk show, e-commerce livestream, news anchor, creative singing/impression, companion character.
   - Each card should explain the use case and the relevant pipeline strengths.

4. Deployment Routes
   - Mock mode for first validation.
   - Local consumer-GPU route with Wav2Lip, MuseTalk, or QuickTalk.
   - OmniRT/FlashTalk route for high-quality remote or private inference.

5. Architecture Overview
   - A simple flow from browser interaction to API/session state, LLM, STT/TTS, synthesis backend, subtitles, and WebRTC playback.

6. Open Source Trust
   - Apache 2.0, Python 3.10+, React, FastAPI, WebRTC.
   - GitHub and docs entry points.

7. Final CTA
   - Product-oriented copy with quick-start and documentation links.

## Docs Page

The docs page should act as a guided starting point, not a complete docs replacement.

Sections:

1. Start Here
   - Mock mode as the recommended first path.
   - Requirements: Python, Node.js, FFmpeg, optional GPU.

2. Deployment Paths
   - Mock.
   - Local model route.
   - OmniRT high-quality route.
   - Private/local audio route.

3. Configuration Map
   - LLM, STT, TTS, synthesis backend, WebRTC.
   - Use compact code/config blocks.

4. Documentation Links
   - Existing Chinese and English docs.
   - README, model deployment docs, API references where available.

## Cases Page

The cases page should make OpenTalking understandable as a product toolkit.

Case cards:

- E-commerce livestream.
- News anchor.
- Anime talk show.
- Companion character.
- Creative singing or impression.
- Real-time mobile recording.

Each case should include:

- Scenario description.
- Why OpenTalking fits.
- Pipeline capabilities involved.
- Suggested deployment path.

## About Page

The about page should express the project mission and community orientation.

Sections:

1. Mission
   - Make real-time digital-human products easier to build, test, and deploy.

2. What OpenTalking Focuses On
   - Orchestration rather than a single monolithic model.
   - Pluggable providers and synthesis backends.
   - Practical deployment progression.

3. Roadmap
   - Better model support.
   - Better local/private deployment.
   - More demo scenarios.
   - Community contributions.

4. Community CTA
   - GitHub, docs, issues, contributions.

## Technical Design

Create a new standalone frontend app in `apps/homepage`.

Recommended stack:

- React 18.
- Vite.
- TypeScript.
- Tailwind CSS.
- `lucide-react` for icons if dependencies are available or can be added.

The implementation should be independent from `apps/web`. Shared files should not be imported from `apps/web` unless explicitly required later.

Suggested structure:

```text
apps/homepage/
  package.json
  index.html
  vite.config.ts
  tsconfig.json
  postcss.config.js
  tailwind.config.js
  src/
    App.tsx
    main.tsx
    index.css
    data/
      content.ts
    components/
      Navbar.tsx
      Footer.tsx
      HeroStage.tsx
      SectionHeader.tsx
      CapabilityCard.tsx
      CaseCard.tsx
      DeploymentRoute.tsx
      ArchitectureFlow.tsx
    pages/
      HomePage.tsx
      DocsPage.tsx
      CasesPage.tsx
      AboutPage.tsx
```

Routing can be lightweight state-based navigation inside the app, or `react-router-dom` if dependencies are added. For this static homepage, state-based navigation is sufficient.

## Interaction And Responsive Behavior

- Navigation should work on desktop and mobile.
- Mobile should use a compact menu or stacked navigation.
- CTA buttons must have visible hover and focus states.
- Layout should be checked at approximately 375px, 768px, 1024px, and 1440px.
- The hero stage and card grids must avoid text overlap and maintain stable dimensions.
- Motion should be subtle and respect `prefers-reduced-motion`.

## Content Source

Content should be drawn from the current README and README.en:

- Positioning: open-source real-time digital-human pipeline.
- Core components: LLM, TTS, STT, WebRTC, voice selection, interruption control, subtitle events, pluggable backends.
- Deployment routes: mock, local, OmniRT, FlashTalk, QuickTalk, Wav2Lip, MuseTalk.
- Demo scenarios: mobile recording, anime talk show, e-commerce livestream, news anchor, creative singing/impression, companion character.

## Testing And Verification

Run at least:

- Package install if needed.
- Typecheck or build for `apps/homepage`.
- Local dev server preview.
- Browser verification for desktop and mobile widths.
- Screenshot/visual check that the hero, navigation, and all four pages render without overlap.

## Non-Goals

- Do not modify `apps/web`.
- Do not connect the homepage to backend APIs.
- Do not replace the existing documentation site.
- Do not create a marketing-only landing page without functional docs/cases/about navigation.
