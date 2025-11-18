import { useMemo } from "react";
import { useModels } from "../api/queries";
import { Note } from "../ui";
import type { ModelOption } from "../api/types";

const GROUP_LABEL: Record<string, string> = {
  free: "Free",
  api_key: "API key",
  subscription: "OpenAI · subscription",
};
const REQUIRE_LABEL: Record<string, string> = {
  openai_api_key: "needs OpenAI key",
  anthropic_api_key: "needs Anthropic key",
  openai_subscription: "needs ChatGPT subscription",
};

export function ModelPicker({
  driver, value, onChange,
}: { driver: string; value: string; onChange: (id: string) => void }) {
  const q = useModels(driver);
  const groups = useMemo(() => {
    const by: Record<string, ModelOption[]> = {};
    for (const m of q.data?.models ?? []) (by[m.category] ??= []).push(m);
    return by;
  }, [q.data]);

  if (q.isLoading) return <Note>Loading models…</Note>;
  const all = q.data?.models ?? [];
  if (all.length === 0) return <Note>No models available for this driver.</Note>;

  return (
    <div role="radiogroup" aria-label="Model" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {["free", "api_key", "subscription"].filter((c) => groups[c]?.length).map((cat) => (
        <div key={cat}>
          <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--muted)", marginBottom: 6 }}>
            {GROUP_LABEL[cat]}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {groups[cat].map((m) => (
              <label key={m.id} className="check" style={{ opacity: m.available ? 1 : 0.7, display: "flex", width: "100%" }}>
                <input
                  type="radio" name="model" value={m.id}
                  checked={value === m.id}
                  onChange={() => onChange(m.id)}
                />
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12.5 }}>{m.label}</span>
                {m.available ? null : (
                  <span className="tag" style={{ marginLeft: "auto", fontSize: 10 }}>
                    {m.requires.map((r) => REQUIRE_LABEL[r] ?? r).join(", ")}
                  </span>
                )}
              </label>
            ))}
          </div>
        </div>
      ))}
      {value && !all.find((m) => m.id === value)?.available && (
        <Note tone="amber">This model needs a credential. Add one in Settings → Credentials.</Note>
      )}
    </div>
  );
}
