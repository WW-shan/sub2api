import { apiClient } from "@/api/client";

interface CodexEnvelope<T> {
  success?: boolean;
  data?: T;
  error?: string | null;
}

export interface CodexTransition {
  time: string;
  from: string;
  to: string;
  reason: string;
}

export interface CodexManualGate {
  action?: string | null;
  token?: string | null;
  continue_url?: string | null;
}

export interface CodexResumeContext {
  email?: string | null;
  access_token_raw?: string | null;
}

export interface CodexStatus {
  enabled: boolean;
  sleep_min: number;
  sleep_max: number;
  total_created: number;
  last_success: string | null;
  last_error: string | null;
  proxy: boolean;
  job_phase: string;
  workflow_id: string | null;
  waiting_reason: string | null;
  can_start: boolean;
  can_resume: boolean;
  can_abandon: boolean;
  manual_gate: CodexManualGate | null;
  resume_context: CodexResumeContext | null;
  resume_hint: string | null;
  last_transition: CodexTransition | null;
  last_resume_gate_reason: string | null;
  recent_logs_tail: CodexLogEntry[];
  accounts_jsonl_offset?: number;
  accounts_jsonl_baseline_offset?: number;
  last_processed_offset?: number;
  last_processed_records?: number;
  total_skipped?: number;
  total_failed?: number;
  last_processed_summary?: {
    start_offset?: number;
    end_offset?: number;
    records_seen?: number;
    created?: number;
    updated?: number;
    skipped?: number;
    failed?: number;
    errors?: string[];
  } | null;
}

export interface CodexLogEntry {
  time: string;
  level: string;
  message: string;
}

export interface CodexLogQuery {
  level?: "info" | "warn" | "error";
  limit?: number;
}

export interface CodexRegisterAccount {
  id: number;
  email: string;
  refresh_token?: string;
  access_token?: string;
  account_id: string | null;
  source: string;
  codex_register_role?: "parent" | "child";
  plan_type?: string;
  organization_id?: string | null;
  workspace_id?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

function unwrapCodexPayload<T>(payload: unknown, fallback: T): T {
  if (!payload || typeof payload !== "object") {
    return fallback;
  }

  const envelope = payload as CodexEnvelope<T>;
  if ("data" in envelope && envelope.data !== undefined) {
    return envelope.data as T;
  }

  return payload as T;
}

function normalizeLogEntry(entry: unknown): CodexLogEntry {
  if (!entry || typeof entry !== "object") {
    return {
      time: "",
      level: "info",
      message: String(entry ?? ""),
    };
  }

  const record = entry as Record<string, unknown>;
  const baseMessage = String(record.message ?? "");
  const detailKeys = Object.keys(record).filter(
    (key) => !["time", "level", "message"].includes(key),
  );

  const detailText = detailKeys
    .map((key) => {
      const value = record[key];
      if (value === null || value === undefined || value === "") {
        return "";
      }

      if (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
      ) {
        return `${key}=${String(value)}`;
      }

      try {
        return `${key}=${JSON.stringify(value)}`;
      } catch {
        return `${key}=${String(value)}`;
      }
    })
    .filter(Boolean)
    .join(" | ");

  const message = detailText
    ? baseMessage
      ? `${baseMessage} | ${detailText}`
      : detailText
    : baseMessage;

  return {
    time: String(record.time ?? ""),
    level: String(record.level ?? "info"),
    message,
  };
}

function normalizeTransition(value: unknown): CodexTransition | null {
  if (!value) {
    return null;
  }

  if (typeof value === "string") {
    return {
      time: value,
      from: "",
      to: "",
      reason: "",
    };
  }

  if (typeof value !== "object") {
    return null;
  }

  const transition = value as Record<string, unknown>;
  return {
    time: String(transition.time ?? ""),
    from: String(transition.from ?? ""),
    to: String(transition.to ?? ""),
    reason: String(transition.reason ?? ""),
  };
}

function normalizeStatus(status: CodexStatus): CodexStatus {
  return {
    ...status,
    last_transition: normalizeTransition(status.last_transition),
    recent_logs_tail: Array.isArray(status.recent_logs_tail)
      ? status.recent_logs_tail.map(normalizeLogEntry)
      : [],
  };
}

export async function getStatus(): Promise<CodexStatus> {
  const res = await apiClient.get<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/status",
  );
  return normalizeStatus(
    unwrapCodexPayload<CodexStatus>(res.data, {
      enabled: false,
      sleep_min: 0,
      sleep_max: 0,
      total_created: 0,
      last_success: null,
      last_error: null,
      proxy: false,
      job_phase: "idle",
      workflow_id: null,
      waiting_reason: null,
      can_start: false,
      can_resume: false,
      can_abandon: false,
      manual_gate: null,
      resume_context: null,
      resume_hint: null,
      last_transition: null,
      last_resume_gate_reason: null,
      recent_logs_tail: [],
    }),
  );
}

export async function getLogs(
  query: CodexLogQuery = {},
): Promise<CodexLogEntry[]> {
  const res = await apiClient.get<
    { logs: CodexLogEntry[] } | CodexEnvelope<CodexLogEntry[]>
  >("/admin/codex/logs", { params: query });

  const payload = res.data;
  if (payload && typeof payload === "object" && "logs" in payload) {
    const legacy = (payload as { logs?: unknown[] }).logs ?? [];
    return legacy.map(normalizeLogEntry);
  }

  const unwrapped = unwrapCodexPayload<CodexLogEntry[]>(payload, []);
  return Array.isArray(unwrapped) ? unwrapped.map(normalizeLogEntry) : [];
}

export async function getAccounts(): Promise<CodexRegisterAccount[]> {
  const res = await apiClient.get<
    { accounts: CodexRegisterAccount[] } | CodexEnvelope<CodexRegisterAccount[]>
  >("/admin/codex/accounts");

  const payload = res.data;
  if (payload && typeof payload === "object" && "accounts" in payload) {
    return (payload as { accounts?: CodexRegisterAccount[] }).accounts ?? [];
  }

  const unwrapped = unwrapCodexPayload<CodexRegisterAccount[]>(payload, []);
  return Array.isArray(unwrapped) ? unwrapped : [];
}

export async function enable(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/enable",
  );
  return normalizeStatus(
    unwrapCodexPayload<CodexStatus>(res.data, {
      enabled: false,
      sleep_min: 0,
      sleep_max: 0,
      total_created: 0,
      last_success: null,
      last_error: null,
      proxy: false,
      job_phase: "idle",
      workflow_id: null,
      waiting_reason: null,
      can_start: false,
      can_resume: false,
      can_abandon: false,
      manual_gate: null,
      resume_context: null,
      resume_hint: null,
      last_transition: null,
      last_resume_gate_reason: null,
      recent_logs_tail: [],
    }),
  );
}

export async function disable(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/disable",
  );
  return normalizeStatus(
    unwrapCodexPayload<CodexStatus>(res.data, {
      enabled: false,
      sleep_min: 0,
      sleep_max: 0,
      total_created: 0,
      last_success: null,
      last_error: null,
      proxy: false,
      job_phase: "idle",
      workflow_id: null,
      waiting_reason: null,
      can_start: false,
      can_resume: false,
      can_abandon: false,
      manual_gate: null,
      resume_context: null,
      resume_hint: null,
      last_transition: null,
      last_resume_gate_reason: null,
      recent_logs_tail: [],
    }),
  );
}

export async function resume(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/resume",
  );
  return normalizeStatus(
    unwrapCodexPayload<CodexStatus>(res.data, {
      enabled: false,
      sleep_min: 0,
      sleep_max: 0,
      total_created: 0,
      last_success: null,
      last_error: null,
      proxy: false,
      job_phase: "idle",
      workflow_id: null,
      waiting_reason: null,
      can_start: false,
      can_resume: false,
      can_abandon: false,
      manual_gate: null,
      resume_context: null,
      resume_hint: null,
      last_transition: null,
      last_resume_gate_reason: null,
      recent_logs_tail: [],
    }),
  );
}

export async function retry(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/retry",
  );
  return normalizeStatus(
    unwrapCodexPayload<CodexStatus>(res.data, {
      enabled: false,
      sleep_min: 0,
      sleep_max: 0,
      total_created: 0,
      last_success: null,
      last_error: null,
      proxy: false,
      job_phase: "idle",
      workflow_id: null,
      waiting_reason: null,
      can_start: false,
      can_resume: false,
      can_abandon: false,
      manual_gate: null,
      resume_context: null,
      resume_hint: null,
      last_transition: null,
      last_resume_gate_reason: null,
      recent_logs_tail: [],
    }),
  );
}

export default {
  getStatus,
  getLogs,
  getAccounts,
  enable,
  disable,
  resume,
  retry,
};
