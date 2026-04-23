export type SseHandler = (event: string, data: unknown) => void;

export function connectSse(url: string, onEvent: SseHandler): () => void {
  const es = new EventSource(url);
  const anyHandler = (ev: MessageEvent) => {
    try {
      const parsed = JSON.parse(ev.data as string);
      onEvent(ev.type || "message", parsed);
    } catch {
      onEvent(ev.type || "message", ev.data);
    }
  };
  const names = [
    "speech.started",
    "speech.media_started",
    "subtitle.chunk",
    "speech.ended",
    "session.state_changed",
    "session.queued",
    "session.expiring",
    "session.expired",
    "error",
    "ping",
    "message",
  ];
  for (const n of names) {
    es.addEventListener(n, anyHandler as EventListener);
  }
  es.onmessage = anyHandler;
  es.onerror = () => {
    /* keep open; browser will retry */
  };
  return () => es.close();
}
