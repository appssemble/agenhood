interface Props {
  message: string; confirmLabel: string; cancelLabel: string;
  destructive?: boolean; onConfirm: () => void; onCancel: () => void;
}
export function ConfirmBar({ message, confirmLabel, cancelLabel, destructive = true, onConfirm, onCancel }: Props) {
  return (
    <div role="region" aria-label="Confirm action"
      className="flex items-center gap-3 rounded-xl border border-warn-100 bg-warn-100/40 px-4 py-2.5 text-sm">
      <span className="flex-1">{message}</span>
      <button className="rounded-lg px-3 py-1.5 text-sm" onClick={onCancel}>{cancelLabel}</button>
      <button onClick={onConfirm}
        className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${destructive ? "bg-err-500 text-white" : "bg-ink text-white"}`}>
        {confirmLabel}
      </button>
    </div>
  );
}
