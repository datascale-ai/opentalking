import type { Message } from "../types";

interface ChatBubbleProps {
  message: Message;
}

export function ChatBubble({ message }: ChatBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex animate-slide-up ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[86%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
          isUser
            ? "bg-cyan-600 text-white"
            : "bg-slate-100 text-slate-800"
        }`}
      >
        {message.text}
      </div>
    </div>
  );
}
