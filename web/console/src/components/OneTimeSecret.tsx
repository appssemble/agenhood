import { Button } from "../ui/Button";
import { Card } from "../ui/Card";

export function OneTimeSecret({
  secret,
  onDismiss,
}: {
  secret: string;
  onDismiss: () => void;
}) {
  function handleCopy() {
    navigator.clipboard?.writeText(secret);
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40">
      <Card role="dialog" aria-modal="true" className="w-full max-w-md p-6">
        <h2 className="text-base font-bold">Copy your key now</h2>
        <p className="mt-1 text-sm text-muted">
          You won't see it again after you dismiss this dialog.
        </p>
        <code className="mono mt-3 block break-all rounded-lg bg-surface-3 p-3 text-sm">
          {secret}
        </code>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={handleCopy}>
            Copy
          </Button>
          <Button variant="dark" size="sm" onClick={onDismiss}>
            Dismiss
          </Button>
        </div>
      </Card>
    </div>
  );
}
