import { useEffect, useRef } from "react";
import type { Message } from "../types";
import { ChatBubble } from "./ChatBubble";

interface ChatMessagesProps {
  messages: Message[];
}

export function ChatMessages({ messages }: ChatMessagesProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  if (messages.length === 0) return null;

  return (
    <div className="fixed inset-x-0 bottom-[7.25rem] z-20 max-h-[45vh] overflow-y-auto px-4 pb-2">
      <div className="mx-auto flex max-w-2xl flex-col gap-2">
        {messages.map((m) => (
          <ChatBubble key={m.id} message={m} />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
