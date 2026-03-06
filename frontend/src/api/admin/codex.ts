import { apiClient } from '@/api/client'

export interface CodexStatus {
  enabled: boolean
  sleep_min: number
  sleep_max: number
  total_created: number
  total_updated: number
  total_skipped: number
  last_run: string | null
  last_success: string | null
  last_error: string | null
  proxy: boolean
  last_token_email: string | null
  last_created_email: string | null
  last_created_account_id: string | null
  last_updated_email: string | null
  last_updated_account_id: string | null
  last_processed_records: number
}

export interface CodexLogEntry {
  time: string
  level: string
  message: string
}

export async function getStatus(): Promise<CodexStatus> {
  const res = await apiClient.get<CodexStatus>('/admin/codex/status')
  return res.data
}

export async function getLogs(): Promise<CodexLogEntry[]> {
  const res = await apiClient.get<{ logs: CodexLogEntry[] }>('/admin/codex/logs')
  return res.data.logs || []
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

export default {
  getStatus,
  getLogs,
  enable,
  disable,
  runOnce
}
