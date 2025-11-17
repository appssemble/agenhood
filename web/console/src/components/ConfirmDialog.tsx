interface Props {
  open: boolean; title: string; body: string; confirmLabel: string;
  destructive?: boolean; onConfirm: () => void; onCancel: () => void;
}
export function ConfirmDialog({ open, title, body, confirmLabel, destructive = true, onConfirm, onCancel }: Props) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40" onClick={onCancel}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className="w-full max-w-md rounded-2xl border border-border bg-surface p-5 shadow"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="text-base font-bold">{title}</h2>
        <p className="mt-2 text-sm text-muted">{body}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button className="rounded-lg border border-border px-3 py-1.5 text-sm" onClick={onCancel}>Cancel</button>
          <button onClick={onConfirm}
            className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${destructive ? "bg-err-500 text-white" : "bg-ink text-white"}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
