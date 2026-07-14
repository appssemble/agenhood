import { useMemo } from "react";
import { useModels } from "../api/queries";
import { Note } from "../ui";
import type { ModelOption } from "../api/types";

const GROUP_LABEL: Record<string, string> = {
  free: "Free",
  api_key: "API key",
  opencode_zen: "OpenCode Zen · pay-per-token credits",
  opencode_go: "OpenCode Go · plan usage",
  subscription: "OpenAI · subscription",
};
const GROUP_ORDER = ["free", "api_key", "opencode_go", "opencode_zen", "subscription"];
const REQUIRE_LABEL: Record<string, string> = {
  openai_api_key: "needs OpenAI key",
  anthropic_api_key: "needs Anthropic key",
  opencode_api_key: "needs OpenCode key",
  openai_subscription: "needs ChatGPT subscription",
};

// The two OpenCode providers list the same model names but bill differently
// (Go plan vs Zen credits); split them into their own sections so the picker
// doesn't show two indistinguishable rows per model.
function groupOf(m: ModelOption): string {
  if (m.category === "api_key" && m.provider === "opencode") return "opencode_zen";
  if (m.category === "api_key" && m.provider === "opencode-go") return "opencode_go";
  return m.category;
}

export function ModelPicker({
  driver, value, onChange,
}: { driver: string; value: string; onChange: (id: string) => void }) {
  const q = useModels(driver);
  const groups = useMemo(() => {
    const by: Record<string, ModelOption[]> = {};
    for (const m of q.data?.models ?? []) (by[groupOf(m)] ??= []).push(m);
    return by;
  }, [q.data]);

  if (q.isLoading) return <Note>Loading models…</Note>;
  const all = q.data?.models ?? [];
  if (all.length === 0) return <Note>No models available for this driver.</Note>;

  return (
    <div role="radiogroup" aria-label="Model" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {GROUP_ORDER.filter((c) => groups[c]?.length).map((cat) => (
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
