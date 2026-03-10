import { apiClient } from '@/api/client'

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
}

export interface CodexLogEntry {
  time: string
  level: string
  message: string
}

export interface CodexRegisterAccount {
  id: number
  email: string
  password: string
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

export async function getLogs(): Promise<CodexLogEntry[]> {
  const res = await apiClient.get<{ logs: CodexLogEntry[] }>('/admin/codex/logs')
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
