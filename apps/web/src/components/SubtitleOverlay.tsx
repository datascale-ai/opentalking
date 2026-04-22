interface SubtitleOverlayProps {
  text: string;
}

export function SubtitleOverlay({ text }: SubtitleOverlayProps) {
  if (!text) return null;

  return (
    <div className="fixed inset-x-0 bottom-[45vh] z-20 flex max-h-[38vh] justify-center overflow-hidden px-4">
      <div className="glass animate-fade-in max-h-full max-w-[min(100%,42rem)] overflow-y-auto rounded-xl px-5 py-2.5 text-center text-sm leading-relaxed text-slate-100 break-words whitespace-pre-wrap">
        {text}
      </div>
    </div>
  );
}
