import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Kind = "success" | "error" | "info";
interface Toast { id: number; kind: Kind; title: string; body?: string; }
interface ToastApi {
  success: (t: string, b?: string) => void;
  error: (t: string, b?: string) => void;
  info: (t: string, b?: string) => void;
}

const Ctx = createContext<ToastApi | null>(null);
export const useToast = () => {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast must be used within ToastProvider");
  return v;
};

let nextId = 1;
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const remove = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const push = useCallback((kind: Kind, title: string, body?: string) => {
    const id = nextId++;
    setToasts((ts) => [...ts, { id, kind, title, body }]);
    setTimeout(() => remove(id), 6000);
  }, []);
  const api: ToastApi = {
    success: (t, b) => push("success", t, b),
    error: (t, b) => push("error", t, b),
    info: (t, b) => push("info", t, b),
  };
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2" role="region" aria-label="Notifications">
        {toasts.map((t) => (
          <div key={t.id} role="alert"
            className={`flex items-start gap-3 rounded-xl border bg-surface p-3 shadow ${t.kind === "error" ? "border-err-100" : "border-border"}`}>
            <div>
              <div className="text-sm font-bold">{t.title}</div>
              {t.body && <div className="text-xs text-muted">{t.body}</div>}
            </div>
            <button aria-label="Dismiss" className="text-muted" onClick={() => remove(t.id)}>×</button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
