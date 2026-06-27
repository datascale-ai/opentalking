import { useEffect, useRef } from "react";
import type { Message } from "../types";
import { ChatBubble } from "./ChatBubble";

interface ChatMessagesProps {
  messages: Message[];
  /** If > 0, only the last N messages are shown (newest at bottom). */
  maxVisible?: number;
}

export function ChatMessages({ messages, maxVisible = 0 }: ChatMessagesProps) {
  const endRef = useRef<HTMLDivElement>(null);

  const visible =
    maxVisible > 0 ? messages.slice(-maxVisible) : messages;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [visible.length]);

  if (visible.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center rounded-lg border border-slate-200 bg-gradient-to-b from-white to-slate-50 p-6 text-center">
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-slate-950 text-cyan-300">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden>
            <path d="M4 5a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3h-4.4L8 20v-4H7a3 3 0 0 1-3-3V5Zm4 2v2h8V7H8Zm0 4v2h5v-2H8Z" />
          </svg>
        </div>
        <p className="text-sm font-semibold text-slate-900">等待第一轮对话</p>
        <p className="mt-1 max-w-52 text-xs leading-relaxed text-slate-500">
          连接会话后，对话记录、流式字幕和用户输入会在这里沉淀。
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="flex flex-col gap-3">
        {visible.map((m) => (
          <ChatBubble key={m.id} message={m} />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
