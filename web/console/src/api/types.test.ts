import { describe, it, expect } from "vitest";
import type {
  AgentConfig, OutputContract, Event, Container, Template,
  Me, ApiKeyCreated, Credential, TaskStatus, EventType,
} from "./types";

describe("wire types match index §4/§6.2", () => {
  it("AgentConfig carries the snapshot fields", () => {
    const c: AgentConfig = {
      driver: "vanilla", model: "claude-sonnet-4-6", system_prompt: "x",
      system_prompt_mode: "augment", tools: ["read_file"],
      context: { variables: {}, text: null, files: [] },
    };
    expect(c.system_prompt_mode).toBe("augment");
  });
  it("OutputContract uses the on-wire `schema` field", () => {
    const o: OutputContract = { type: "structured", schema: { type: "object" } };
    expect(o.type).toBe("structured");
  });
  it("Event seq is numeric and type is the literal union", () => {
    const e: Event = { seq: 1, type: "task_started", ts: "2026-05-20T10:00:00Z", payload: { driver: "vanilla", model: "m" } };
    const t: EventType = e.type;
    expect(t).toBe("task_started");
  });
  it("Container exposes lifecycle status, config, image_variant", () => {
    const ctr: Container = {
      id: "con_1", name: "n", external_id: null, status: "running",
      image_variant: "full", image_tag: "v0.1.0", metadata: {},
      last_task_at: null, created_at: "2026-05-20T10:00:00Z", error_message: null,
      config: { driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } },
      mem_limit: "1Gi", cpus: 1,
    };
    expect(ctr.status).toBe("running");
  });
  it("Template carries driver capability metadata for the editor", () => {
    const tpl: Template = {
      id: "tpl_1", tenant_id: null, name: "Research", driver: "vanilla", model: "m",
      system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] },
      skills: [], mcp_servers: [], limits: {}, is_builtin: true,
      capabilities: { supports_tools: true, supports_structured_output: true, supports_cancel: true, requires_image_feature: null },
      driver_template: { driver: "vanilla", default_system_prompt: "", available_tools: ["read_file"], tools_user_editable: true, supports_context: true },
      available_tool_specs: [{ name: "web_fetch", description: "", input_schema: {}, requires_image_feature: "chromium" }],
    };
    expect(tpl.capabilities.supports_structured_output).toBe(true);
  });
  it("ApiKeyCreated reveals the secret once; Me carries role + limits", () => {
    const k: ApiKeyCreated = { id: "key_1", name: "ci", key: "tk_live_secret", prefix: "tk_live_", created_at: "2026-05-20T10:00:00Z" };
    const me: Me = {
      id: "usr_1", tenant_id: "tnt_1", name: "Davis", email: "d@x.io", role: "admin",
      is_staff: false, must_change_password: false,
      tenant: { id: "tnt_1", name: "Acme", limits: { allowed_drivers: ["vanilla"], default_max_iterations: 30, default_max_tokens: 2000000, default_task_timeout_seconds: 1800, max_concurrent_tasks_per_container: 4 } },
      active_tenant_id: null, tenants: [],
    };
    const status: TaskStatus = "completed";
    const cred: Credential = { id: "cred_1", provider: "anthropic", last4: "abcd", created_by: "Davis", created_at: "2026-05-20T10:00:00Z", auth_method: "api_key", status: "active", account_tail: null, expires_at: null };
    expect([k.key, me.role, status, cred.provider]).toEqual(["tk_live_secret", "admin", "completed", "anthropic"]);
  });
});
