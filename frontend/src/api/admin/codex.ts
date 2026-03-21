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

export interface CodexProcessedSummary {
  start_offset?: number;
  end_offset?: number;
  records_seen?: number;
  created?: number;
  updated?: number;
  skipped?: number;
  failed?: number;
  errors?: string[];
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
  last_processed_summary?: CodexProcessedSummary | null;
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

export interface CodexLoopHistoryEntry {
  round: number;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  summary: CodexProcessedSummary | null;
  error: string | null;
}

export interface CodexLoopStatus {
  loop_running: boolean;
  loop_stopping: boolean;
  loop_started_at: string | null;
  loop_current_round: number;
  loop_last_round_started_at: string | null;
  loop_last_round_finished_at: string | null;
  loop_last_round_created: number;
  loop_last_round_updated: number;
  loop_last_round_skipped: number;
  loop_last_round_failed: number;
  loop_total_created: number;
  loop_last_error: string | null;
  loop_history: CodexLoopHistoryEntry[];
  loop_committed_accounts_jsonl_offset: number;
  loop_current_proxy_id: string | null;
  loop_current_proxy_name: string | null;
  loop_last_proxy_id: string | null;
  loop_last_proxy_name: string | null;
  loop_last_switch_reason: string | null;
}

export interface CodexProxyEntry {
  id: string;
  name: string;
  proxy_url: string;
  enabled: boolean;
  last_status: "unknown" | "ok" | "failed" | "cooldown";
  last_checked_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  cooldown_until: string | null;
  failure_count: number;
}

export interface CodexProxyStatus {
  proxy_enabled: boolean;
  proxy_current_id: string | null;
  proxy_current_name: string | null;
  proxy_last_used_id: string | null;
  proxy_last_used_name: string | null;
  proxy_last_checked_at: string | null;
  proxy_last_error: string | null;
  proxy_last_switch_reason: string | null;
  proxy_pool: CodexProxyEntry[];
}

export interface CodexSaveProxyListPayload {
  proxy_enabled?: boolean;
  proxy_pool: Array<{
    id?: string;
    name: string;
    proxy_url: string;
    enabled?: boolean;
  }>;
}

export interface CodexSelectProxyPayload {
  proxy_id: string;
}

export interface CodexTestProxyPayload {
  proxy_id: string;
}

const defaultProcessedSummary = (): CodexProcessedSummary => ({
  start_offset: 0,
  end_offset: 0,
  records_seen: 0,
  created: 0,
  updated: 0,
  skipped: 0,
  failed: 0,
  errors: [],
});

const defaultStatus = (): CodexStatus => ({
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
  accounts_jsonl_offset: 0,
  accounts_jsonl_baseline_offset: 0,
  last_processed_offset: 0,
  last_processed_records: 0,
  total_skipped: 0,
  total_failed: 0,
  last_processed_summary: null,
});

const defaultLoopStatus = (): CodexLoopStatus => ({
  loop_running: false,
  loop_stopping: false,
  loop_started_at: null,
  loop_current_round: 0,
  loop_last_round_started_at: null,
  loop_last_round_finished_at: null,
  loop_last_round_created: 0,
  loop_last_round_updated: 0,
  loop_last_round_skipped: 0,
  loop_last_round_failed: 0,
  loop_total_created: 0,
  loop_last_error: null,
  loop_history: [],
  loop_committed_accounts_jsonl_offset: 0,
  loop_current_proxy_id: null,
  loop_current_proxy_name: null,
  loop_last_proxy_id: null,
  loop_last_proxy_name: null,
  loop_last_switch_reason: null,
});

const defaultProxyStatus = (): CodexProxyStatus => ({
  proxy_enabled: false,
  proxy_current_id: null,
  proxy_current_name: null,
  proxy_last_used_id: null,
  proxy_last_used_name: null,
  proxy_last_checked_at: null,
  proxy_last_error: null,
  proxy_last_switch_reason: null,
  proxy_pool: [],
});

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

function toNumber(value: unknown, fallback = 0): number {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function toNullableString(value: unknown): string | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  return String(value);
}

function normalizeProcessedSummary(value: unknown): CodexProcessedSummary | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const summary = value as Record<string, unknown>;
  return {
    start_offset: toNumber(summary.start_offset),
    end_offset: toNumber(summary.end_offset),
    records_seen: toNumber(summary.records_seen),
    created: toNumber(summary.created),
    updated: toNumber(summary.updated),
    skipped: toNumber(summary.skipped),
    failed: toNumber(summary.failed),
    errors: Array.isArray(summary.errors)
      ? summary.errors.map((item) => String(item))
      : [],
  };
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
    ...defaultStatus(),
    ...status,
    last_success: toNullableString(status.last_success),
    last_error: toNullableString(status.last_error),
    workflow_id: toNullableString(status.workflow_id),
    waiting_reason: toNullableString(status.waiting_reason),
    resume_hint: toNullableString(status.resume_hint),
    last_resume_gate_reason: toNullableString(status.last_resume_gate_reason),
    last_transition: normalizeTransition(status.last_transition),
    recent_logs_tail: Array.isArray(status.recent_logs_tail)
      ? status.recent_logs_tail.map(normalizeLogEntry)
      : [],
    last_processed_summary: normalizeProcessedSummary(status.last_processed_summary),
  };
}

function normalizeLoopHistoryEntry(value: unknown): CodexLoopHistoryEntry {
  if (!value || typeof value !== "object") {
    return {
      round: 0,
      started_at: null,
      finished_at: null,
      status: "unknown",
      created: 0,
      updated: 0,
      skipped: 0,
      failed: 0,
      summary: null,
      error: toNullableString(value),
    };
  }

  const entry = value as Record<string, unknown>;
  return {
    round: toNumber(entry.round),
    started_at: toNullableString(entry.started_at),
    finished_at: toNullableString(entry.finished_at),
    status: String(entry.status ?? "unknown"),
    created: toNumber(entry.created),
    updated: toNumber(entry.updated),
    skipped: toNumber(entry.skipped),
    failed: toNumber(entry.failed),
    summary: normalizeProcessedSummary(entry.summary) ?? defaultProcessedSummary(),
    error: toNullableString(entry.error),
  };
}

function normalizeLoopStatus(status: CodexLoopStatus): CodexLoopStatus {
  return {
    ...defaultLoopStatus(),
    ...status,
    loop_running: Boolean(status.loop_running),
    loop_stopping: Boolean(status.loop_stopping),
    loop_started_at: toNullableString(status.loop_started_at),
    loop_current_round: toNumber(status.loop_current_round),
    loop_last_round_started_at: toNullableString(status.loop_last_round_started_at),
    loop_last_round_finished_at: toNullableString(status.loop_last_round_finished_at),
    loop_last_round_created: toNumber(status.loop_last_round_created),
    loop_last_round_updated: toNumber(status.loop_last_round_updated),
    loop_last_round_skipped: toNumber(status.loop_last_round_skipped),
    loop_last_round_failed: toNumber(status.loop_last_round_failed),
    loop_total_created: toNumber(status.loop_total_created),
    loop_last_error: toNullableString(status.loop_last_error),
    loop_history: Array.isArray(status.loop_history)
      ? status.loop_history.map(normalizeLoopHistoryEntry)
      : [],
    loop_committed_accounts_jsonl_offset: toNumber(
      status.loop_committed_accounts_jsonl_offset,
    ),
    loop_current_proxy_id: toNullableString(status.loop_current_proxy_id),
    loop_current_proxy_name: toNullableString(status.loop_current_proxy_name),
    loop_last_proxy_id: toNullableString(status.loop_last_proxy_id),
    loop_last_proxy_name: toNullableString(status.loop_last_proxy_name),
    loop_last_switch_reason: toNullableString(status.loop_last_switch_reason),
  };
}

function normalizeProxyEntry(entry: unknown): CodexProxyEntry {
  const fallback: CodexProxyEntry = {
    id: "",
    name: "",
    proxy_url: "",
    enabled: true,
    last_status: "unknown",
    last_checked_at: null,
    last_success_at: null,
    last_failure_at: null,
    cooldown_until: null,
    failure_count: 0,
  };

  if (!entry || typeof entry !== "object") {
    return fallback;
  }

  const value = entry as Record<string, unknown>;
  const statusValue = String(value.last_status ?? "unknown");
  const allowedStatus = ["unknown", "ok", "failed", "cooldown"] as const;

  return {
    id: String(value.id ?? ""),
    name: String(value.name ?? ""),
    proxy_url: String(value.proxy_url ?? ""),
    enabled: value.enabled === undefined ? true : Boolean(value.enabled),
    last_status: allowedStatus.includes(statusValue as (typeof allowedStatus)[number])
      ? (statusValue as CodexProxyEntry["last_status"])
      : "unknown",
    last_checked_at: toNullableString(value.last_checked_at),
    last_success_at: toNullableString(value.last_success_at),
    last_failure_at: toNullableString(value.last_failure_at),
    cooldown_until: toNullableString(value.cooldown_until),
    failure_count: toNumber(value.failure_count),
  };
}

function normalizeProxyStatus(status: CodexProxyStatus): CodexProxyStatus {
  return {
    ...defaultProxyStatus(),
    ...status,
    proxy_enabled: Boolean(status.proxy_enabled),
    proxy_current_id: toNullableString(status.proxy_current_id),
    proxy_current_name: toNullableString(status.proxy_current_name),
    proxy_last_used_id: toNullableString(status.proxy_last_used_id),
    proxy_last_used_name: toNullableString(status.proxy_last_used_name),
    proxy_last_checked_at: toNullableString(status.proxy_last_checked_at),
    proxy_last_error: toNullableString(status.proxy_last_error),
    proxy_last_switch_reason: toNullableString(status.proxy_last_switch_reason),
    proxy_pool: Array.isArray(status.proxy_pool)
      ? status.proxy_pool.map(normalizeProxyEntry)
      : [],
  };
}

export async function getStatus(): Promise<CodexStatus> {
  const res = await apiClient.get<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/status",
  );
  return normalizeStatus(unwrapCodexPayload<CodexStatus>(res.data, defaultStatus()));
}

export async function getLoopStatus(): Promise<CodexLoopStatus> {
  const res = await apiClient.get<
    CodexLoopStatus | CodexEnvelope<CodexLoopStatus>
  >("/admin/codex/loop/status");
  return normalizeLoopStatus(
    unwrapCodexPayload<CodexLoopStatus>(res.data, defaultLoopStatus()),
  );
}

export async function getProxyStatus(): Promise<CodexProxyStatus> {
  const res = await apiClient.get<
    CodexProxyStatus | CodexEnvelope<CodexProxyStatus>
  >("/admin/codex/proxy/status");
  return normalizeProxyStatus(
    unwrapCodexPayload<CodexProxyStatus>(res.data, defaultProxyStatus()),
  );
}

export async function saveProxyList(
  payload: CodexSaveProxyListPayload,
): Promise<CodexProxyStatus> {
  const res = await apiClient.post<
    CodexProxyStatus | CodexEnvelope<CodexProxyStatus>
  >("/admin/codex/proxy/list", payload);
  return normalizeProxyStatus(
    unwrapCodexPayload<CodexProxyStatus>(res.data, defaultProxyStatus()),
  );
}

export async function selectProxy(
  payload: CodexSelectProxyPayload,
): Promise<CodexProxyStatus> {
  const res = await apiClient.post<
    CodexProxyStatus | CodexEnvelope<CodexProxyStatus>
  >("/admin/codex/proxy/select", payload);
  return normalizeProxyStatus(
    unwrapCodexPayload<CodexProxyStatus>(res.data, defaultProxyStatus()),
  );
}

export async function testProxy(
  payload: CodexTestProxyPayload,
): Promise<CodexProxyStatus> {
  const res = await apiClient.post<
    CodexProxyStatus | CodexEnvelope<CodexProxyStatus>
  >("/admin/codex/proxy/test", payload);
  return normalizeProxyStatus(
    unwrapCodexPayload<CodexProxyStatus>(res.data, defaultProxyStatus()),
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
  return normalizeStatus(unwrapCodexPayload<CodexStatus>(res.data, defaultStatus()));
}

export async function disable(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/disable",
  );
  return normalizeStatus(unwrapCodexPayload<CodexStatus>(res.data, defaultStatus()));
}

export async function resume(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/resume",
  );
  return normalizeStatus(unwrapCodexPayload<CodexStatus>(res.data, defaultStatus()));
}

export async function retry(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus | CodexEnvelope<CodexStatus>>(
    "/admin/codex/retry",
  );
  return normalizeStatus(unwrapCodexPayload<CodexStatus>(res.data, defaultStatus()));
}

export async function startLoop(): Promise<CodexLoopStatus> {
  const res = await apiClient.post<
    CodexLoopStatus | CodexEnvelope<CodexLoopStatus>
  >("/admin/codex/loop/start");
  return normalizeLoopStatus(
    unwrapCodexPayload<CodexLoopStatus>(res.data, defaultLoopStatus()),
  );
}

export async function stopLoop(): Promise<CodexLoopStatus> {
  const res = await apiClient.post<
    CodexLoopStatus | CodexEnvelope<CodexLoopStatus>
  >("/admin/codex/loop/stop");
  return normalizeLoopStatus(
    unwrapCodexPayload<CodexLoopStatus>(res.data, defaultLoopStatus()),
  );
}

export default {
  getStatus,
  getLoopStatus,
  getProxyStatus,
  saveProxyList,
  selectProxy,
  testProxy,
  getLogs,
  getAccounts,
  enable,
  disable,
  resume,
  retry,
  startLoop,
  stopLoop,
};
