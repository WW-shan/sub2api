import { apiClient } from '@/api/client'

export interface CodexTransition {
  time: string
  from: string
  to: string
  reason: string
}

export interface CodexStatus {
  enabled: boolean
  sleep_min: number
  sleep_max: number
  total_created: number
  last_success: string | null
  last_error: string | null
  proxy: boolean
  job_phase: string
  workflow_id: string | null
  waiting_reason: string | null
  can_start: boolean
  can_resume: boolean
  can_abandon: boolean
  last_transition: CodexTransition | null
  last_resume_gate_reason: string | null
  recent_logs_tail: CodexLogEntry[]
}

export interface CodexLogEntry {
  time: string
  level: string
  message: string
}

export interface CodexLogQuery {
  level?: 'info' | 'warn' | 'error'
  limit?: number
}

export interface CodexRegisterAccount {
  id: number
  email: string
  refresh_token: string
  access_token: string
  account_id: string | null
  source: string
  created_at: string | null
  updated_at: string | null
}

export async function getStatus(): Promise<CodexStatus> {
  const res = await apiClient.get<CodexStatus>('/admin/codex/status')
  return res.data
}

export async function getLogs(query: CodexLogQuery = {}): Promise<CodexLogEntry[]> {
  const res = await apiClient.get<{ logs: CodexLogEntry[] }>('/admin/codex/logs', { params: query })
  return res.data?.logs ?? []
}

export async function getAccounts(): Promise<CodexRegisterAccount[]> {
  const res = await apiClient.get<{ accounts: CodexRegisterAccount[] }>('/admin/codex/accounts')
  return res.data?.accounts ?? []
}

export async function enable(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus>('/admin/codex/enable')
  return res.data
}

export async function disable(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus>('/admin/codex/disable')
  return res.data
}

export async function runOnce(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus>('/admin/codex/run-once')
  return res.data
}

export async function resume(): Promise<CodexStatus> {
  const res = await apiClient.post<CodexStatus>('/admin/codex/resume')
  return res.data
}

export default {
  getStatus,
  getLogs,
  getAccounts,
  enable,
  disable,
  runOnce,
  resume
}
