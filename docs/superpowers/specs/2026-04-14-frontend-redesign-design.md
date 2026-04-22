# OpenTalking Frontend Redesign — Immersive Chat UI

> Archived design note.
> This file documents the intent behind the frontend redesign, not the exact current implementation.
> For runtime behavior and startup details, prefer `docs/quickstart.md`, `docs/local-dev.md`, and the code under `apps/web/`.

**Date:** 2026-04-14
**Status:** Approved

## Goal

Redesign the OpenTalking web frontend from a developer console layout to an immersive, conversation-first experience. The digital avatar video fills the viewport; all UI floats on top as translucent glass layers.

## Design Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Product form | Conversational chat | Natural dialogue experience, like Character.ai video mode |
| Video size | Full-viewport background | Maximum immersion, avatar feels life-size |
| Config access | Hidden behind settings icon | Keep main screen minimal, settings rarely changed |
| Color scheme | Dark glassmorphism | Best contrast against video, industry standard for video products |
| Design approach | Approach A: Full immersive | Video as background, gradient overlay, floating chat bubbles |

## Layout

```
┌─────────────────────────────────────────────┐
│  ┌─logo─┐                    ● status  ⚙   │  TopBar (glass)
│  └──────┘                                   │
│                                             │
│                                             │
│              VIDEO (full viewport)           │
│              position: fixed                 │
│              object-fit: cover               │
│                                             │
│                                             │
│         ── subtitle overlay ──               │
│                                             │
│  ┌─ 🤖 assistant bubble ───────────────┐    │  GradientOverlay
│  └──────────────────────────────────────┘    │  (transparent → black 0.75)
│  ┌───────────────── 👤 user bubble ────┐    │
│  └──────────────────────────────────────┘    │
│                                             │
│  ┌──────────────────────────────── ▶ ──┐    │  ChatInput (glass)
│  │  Type a message...                   │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

- Video `<video>` is `position: fixed; inset: 0; object-fit: cover; z-index: 0`
- All UI elements float above with `z-index: 1+`
- Bottom 45vh has a gradient overlay from transparent to `rgba(0,0,0,0.75)` with `pointer-events: none`

## Component Tree

```
App
├── VideoBackground          # Full-screen video, fixed position
├── TopBar                   # Floating glass top bar
│   ├── Logo                 # "OpenTalking" text
│   ├── ConnectionDot        # green=live, yellow=connecting, gray=idle, red=error
│   └── SettingsButton       # Gear icon → opens SettingsPanel
├── SettingsPanel            # Right slide-in modal (glass)
│   ├── AvatarSelector       # Avatar grid/list
│   └── ModelSelector        # Model dropdown
├── StartOverlay             # Welcome screen (before connection)
│   ├── Avatar preview       # Static avatar image
│   ├── Avatar name          # e.g. "Demo Avatar"
│   └── "Start" button       # Creates session + WebRTC
├── SubtitleOverlay          # Floating subtitle bar, mid-lower area of video
├── GradientOverlay          # Bottom gradient (pointer-events: none)
├── ChatMessages             # Scrollable chat bubble area (above input)
│   └── ChatBubble           # Single message (user=right/blue, assistant=left/white)
└── ChatInput                # Glass input bar at bottom
    ├── Text input            # Capsule-shaped
    └── Send/Stop button      # Send (cyan) or Stop (red square) when speaking
```

## Visual Style

### Glass Layer (shared)

```css
.glass {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
```

### Colors

| Purpose | Value | Tailwind |
|---------|-------|----------|
| Glass background | `rgba(0,0,0,0.5)` + blur(16px) | custom |
| Gradient overlay | `transparent → rgba(0,0,0,0.75)` | custom |
| User bubble | `rgba(59,130,246,0.8)` | blue-500/80 |
| Assistant bubble | `rgba(255,255,255,0.1)` | white/10 |
| Primary text | `#f1f5f9` | slate-100 |
| Secondary text | `#94a3b8` | slate-400 |
| Accent / send | `#06b6d4` | cyan-500 |
| Danger / stop | `#ef4444` | red-500 |
| Success / live | `#22c55e` | green-500 |
| Warning / connecting | `#eab308` | yellow-500 |

### Typography & Spacing

- Font: `system-ui, -apple-system, sans-serif`
- Bubble border-radius: `16px`
- Input border-radius: `24px` (capsule)
- Bubble gap: `8px`
- Bubble padding: `12px 16px`
- Input padding: `12px 20px`

### Animations

| Element | Animation | Duration |
|---------|-----------|----------|
| StartOverlay exit | opacity 1→0, scale 1→0.95 | 0.5s ease-out |
| Chat bubble enter | translateY(20px)→0, opacity 0→1 | 0.3s ease-out |
| Settings panel enter | translateX(100%)→0 | 0.3s ease-out |
| Connection dot (connecting) | pulse keyframe | 1.5s infinite |
| Subtitle | opacity fade in/out | 0.2s |

## Interaction Flows

### 1. First Visit → Start Session

1. Page loads → fetch `GET /avatars` and `GET /models`
2. Show StartOverlay: avatar preview image + name + "开始对话" button
3. User clicks "开始对话"
4. Button shows spinner, `connection = 'connecting'`
5. `POST /sessions` → get `sessionId`
6. WebRTC offer/answer → video stream attached
7. `connection = 'live'`, StartOverlay fades out
8. SSE connection established to `/sessions/{id}/events`

### 2. Send Message

1. User types text, presses Enter or clicks send
2. `messages.push({ role: 'user', text })` → blue bubble appears instantly
3. `POST /sessions/{id}/speak { text }`
4. `isSpeaking = true` → send button changes to red stop icon
5. SSE `subtitle.chunk` events → `currentSubtitle` updates in real time
6. SSE `speech.ended` → accumulate subtitle into `messages.push({ role: 'assistant', text })`
7. `isSpeaking = false`, `currentSubtitle = ''`

### 3. Interrupt

1. User clicks stop button (visible only when `isSpeaking`)
2. `POST /sessions/{id}/interrupt`
3. `isSpeaking = false`
4. Partial subtitle saved as assistant message (with truncation indicator)

### 4. Change Avatar (Settings)

1. User opens settings panel (gear icon)
2. Selects different avatar
3. Close old WebRTC peer connection
4. `DELETE /sessions/{id}` (if endpoint exists) or let it expire
5. Recreate session + WebRTC with new avatar
6. Settings panel auto-closes

## State

```typescript
type ConnectionStatus = 'idle' | 'connecting' | 'live' | 'error'

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  timestamp: number
}

interface AppState {
  // Connection
  connection: ConnectionStatus
  sessionId: string | null

  // Config
  avatarId: string
  model: string
  avatars: AvatarSummary[]
  models: string[]

  // Chat
  messages: Message[]
  currentSubtitle: string   // real-time subtitle during speech

  // UI
  settingsOpen: boolean
  isSpeaking: boolean
}
```

## Mobile Adaptation

- Video still full-viewport cover
- Chat area occupies bottom 50%
- Input bar uses `padding-bottom: env(safe-area-inset-bottom)` for notch devices
- Settings panel slides from bottom (sheet) instead of right
- Bubbles have smaller padding and font size

## Backend Compatibility

No backend changes required. All existing endpoints are sufficient:

- `GET /avatars` — avatar list
- `GET /models` — model list
- `POST /sessions` — create session
- `POST /sessions/{id}/speak` — send text
- `POST /sessions/{id}/interrupt` — interrupt speech
- `GET /sessions/{id}/events` — SSE event stream
- `POST /sessions/{id}/webrtc/offer` — WebRTC negotiation

## Files to Change

All changes are within `apps/web/src/`. No new dependencies needed (Tailwind already supports backdrop-blur, animations via utilities).

| Action | File | Description |
|--------|------|-------------|
| Rewrite | `App.tsx` | New layout, state management with messages array |
| Create | `components/VideoBackground.tsx` | Full-screen fixed video |
| Create | `components/TopBar.tsx` | Glass top bar with logo, status dot, settings button |
| Create | `components/ConnectionDot.tsx` | Animated status indicator |
| Create | `components/SettingsPanel.tsx` | Right slide-in glass panel |
| Create | `components/StartOverlay.tsx` | Welcome screen with start button |
| Create | `components/ChatMessages.tsx` | Scrollable chat bubble container |
| Create | `components/ChatBubble.tsx` | Single chat message bubble |
| Create | `components/ChatInput.tsx` | Glass capsule input + send/stop button |
| Rewrite | `components/SubtitleOverlay.tsx` | Repositioned for video overlay |
| Delete | `components/TextInput.tsx` | Replaced by ChatInput |
| Delete | `components/StatusBar.tsx` | Replaced by TopBar + ConnectionDot |
| Delete | `components/VideoPlayer.tsx` | Replaced by VideoBackground |
| Delete | `components/AvatarSelector.tsx` | Moved into SettingsPanel |
| Delete | `components/ModelSelector.tsx` | Moved into SettingsPanel |
| Keep | `lib/api.ts` | No changes needed |
| Keep | `lib/sse.ts` | No changes needed |
| Keep | `lib/webrtc.ts` | No changes needed |
| Update | `index.css` | Add glass utility class, gradient overlay styles |
| Update | `tailwind.config.js` | Add custom animation keyframes if needed |
