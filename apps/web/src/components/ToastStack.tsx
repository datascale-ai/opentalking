export type ToastTone = "info" | "success" | "error";

export type ToastMessage = {
  id: string;
  tone: ToastTone;
  message: string;
};

const TONE_CLASSES: Record<ToastTone, string> = {
  info: "border-sky-200 bg-sky-50 text-sky-800",
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  error: "border-red-200 bg-red-50 text-red-800",
};

const DOT_CLASSES: Record<ToastTone, string> = {
  info: "bg-sky-500",
  success: "bg-emerald-500",
  error: "bg-red-500",
};

type ToastStackProps = {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
};

export function ToastStack({ toasts, onDismiss }: ToastStackProps) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed right-4 top-16 z-[70] flex w-[min(calc(100vw-2rem),24rem)] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm shadow-lg shadow-slate-200/70 ${TONE_CLASSES[toast.tone]}`}
          role="status"
        >
          <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT_CLASSES[toast.tone]}`} />
          <p className="min-w-0 flex-1 leading-relaxed">{toast.message}</p>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            className="ml-1 rounded-md px-1.5 text-base leading-none opacity-60 transition hover:bg-white/70 hover:opacity-100"
            aria-label="关闭提示"
          >
            x
          </button>
        </div>
      ))}
    </div>
  );
}
