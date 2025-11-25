import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { useToast } from "../components/Toast";
import { Card } from "../ui/Card";
import { Field } from "../ui/Field";
import { Input } from "../ui/inputs";
import { Button } from "../ui/Button";
import { Note } from "../ui/Note";

export default function ChangePassword({ forced = true, bare = false }: { forced?: boolean; bare?: boolean }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await api.post(`/v1/users/${user?.id}/password`, { current_password: current, new_password: next });
      toast.success("Password updated");
      setCurrent("");
      setNext("");
      if (forced) navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change password");
    } finally {
      setSaving(false);
    }
  }

  const fields = (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <Field label="Current password" htmlFor="current">
        <Input
          id="current"
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
        />
      </Field>

      <Field label="New password" htmlFor="next">
        <Input
          id="next"
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
        />
      </Field>

      {error && (
        <Note tone="amber">{error}</Note>
      )}

      <Button
        type="submit"
        variant="dark"
        size="md"
        className={bare ? "self-start" : "w-full justify-center"}
        disabled={saving || !current || !next}
      >
        {saving ? "Updating…" : "Update password"}
      </Button>
    </form>
  );

  // Bare mode: just the form, so a host screen can supply its own section chrome.
  if (bare) return fields;

  const form = (
    <Card className="shadow-sm">
      <h1 className="mb-1 text-base font-bold tracking-tight">
        {forced ? "Set a new password" : "Change password"}
      </h1>
      {forced && (
        <p className="mb-5 text-[12.5px] text-muted">
          You must change your password before continuing.
        </p>
      )}
      <div className={forced ? "" : "mt-5"}>{fields}</div>
    </Card>
  );

  if (!forced) return form;

  return (
    <div className="grid min-h-screen place-items-center bg-surface-2">
      <div className="w-full max-w-sm px-4">
        {/* Brand wordmark */}
        <div className="mb-6 text-center">
          <span className="text-2xl font-extrabold tracking-tight">
            agen<span className="rounded bg-primary-300 px-1.5">hood</span>
          </span>
        </div>

        {form}
      </div>
    </div>
  );
}
