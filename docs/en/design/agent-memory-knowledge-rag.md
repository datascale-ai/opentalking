# Agent Memory and Knowledge RAG Design

This page is a short English companion for the Chinese design draft. It keeps the
design note visible in the English documentation until a full translation is prepared.

## Goal

The first version adds a minimal but end-to-end Agent layer for OpenTalking:

- persistent memory across sessions,
- one default knowledge base,
- LightRAG-backed retrieval,
- local SQLite and filesystem persistence,
- controlled LLM context injection before speech generation.

The design keeps the realtime digital-human path stable. Memory and knowledge context
can enrich LLM responses, but they must not rewrite user input or block TTS, WebRTC, or
video generation.

## First-Version Boundaries

The first version intentionally avoids account systems, multi-tenant permissions,
online collaborative document editing, and complex knowledge-base versioning. It uses a
browser-generated client user ID for lightweight isolation and starts with a single
default knowledge base before expanding to multiple knowledge bases and avatar binding.

## Main Flow

```text
Open WebUI
  -> create or read client_user_id
  -> select avatar
  -> enable memory and/or knowledge base
  -> create session with Agent options
  -> retrieve memory and knowledge snippets before LLM generation
  -> stream LLM output to TTS and digital-human playback
  -> save the turn and update memory asynchronously
```

For the full Chinese draft, switch the language selector to Chinese on this page.
