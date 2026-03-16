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
  last_transition: CodexTransition | null;
  last_resume_gate_reason: string | null;
  recent_logs_tail: CodexLogEntry[];
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
  refresh_token: string;
  access_token: string;
  account_id: string | null;
  source: string;
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
  return {
    time: String(record.time ?? ""),
    level: String(record.level ?? "info"),
    message: String(record.message ?? ""),
  };
}

export async function getStatus(): Promise<CodexStatus> {
  const res = await apiClient.get<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/status",
  );
  return unwrapCodexPayload<CodexStatus>(res.data, {
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
    last_transition: null,
    last_resume_gate_reason: null,
    recent_logs_tail: [],
  });
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
  return unwrapCodexPayload<CodexStatus>(res.data, {
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
    last_transition: null,
    last_resume_gate_reason: null,
    recent_logs_tail: [],
  });
}

export async function disable(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/disable",
  );
  return unwrapCodexPayload<CodexStatus>(res.data, {
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
    last_transition: null,
    last_resume_gate_reason: null,
    recent_logs_tail: [],
  });
}

export async function resume(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/resume",
  );
  return unwrapCodexPayload<CodexStatus>(res.data, {
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
    last_transition: null,
    last_resume_gate_reason: null,
    recent_logs_tail: [],
  });
}

export async function retry(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/retry",
  );
  return unwrapCodexPayload<CodexStatus>(res.data, {
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
    last_transition: null,
    last_resume_gate_reason: null,
    recent_logs_tail: [],
  });
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
