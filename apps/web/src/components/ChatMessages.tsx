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

  if (visible.length === 0) return null;

  return (
    <div className="fixed inset-x-0 bottom-[7.25rem] z-20 max-h-[45vh] overflow-y-auto px-4 pb-2">
      <div className="mx-auto flex max-w-2xl flex-col gap-2">
        {visible.map((m) => (
          <ChatBubble key={m.id} message={m} />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
