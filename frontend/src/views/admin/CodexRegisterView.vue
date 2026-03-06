<template>
  <AppLayout>
    <div class="mx-auto max-w-4xl space-y-6">
      <div class="card">
        <div class="flex items-center justify-between gap-4 border-b border-gray-100 px-6 py-4 dark:border-dark-700">
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white">Codex 自动注册</h1>
          <span
            :class="[
              'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium',
              status?.enabled
                ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                : 'bg-gray-100 text-gray-600 dark:bg-dark-700 dark:text-gray-300'
            ]"
          >
            {{ status?.enabled ? '运行中' : '已停止' }}
          </span>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-4 p-6 text-sm text-gray-700 dark:text-gray-200">
          <div>
            <p class="text-sm font-medium text-gray-900 dark:text-white">当前状态</p>
            <p class="mt-1 text-sm">
              <span v-if="status?.enabled" class="text-green-600 dark:text-green-400">已开启自动注册</span>
              <span v-else class="text-gray-500 dark:text-gray-400">已关闭自动注册</span>
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="loading || status?.enabled"
              @click="toggleEnabled(true)"
            >
              开启
            </button>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="loading || !status?.enabled"
              @click="toggleEnabled(false)"
            >
              关闭
            </button>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="loading"
              @click="runOnce"
            >
              手动执行一次
            </button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="border-b border-gray-100 px-6 py-4 dark:border-dark-700">
          <h2 class="text-base font-semibold text-gray-900 dark:text-white">运行概览</h2>
        </div>

        <div class="space-y-4 p-6 text-sm text-gray-700 dark:text-gray-200">
          <div class="grid gap-4 sm:grid-cols-3">
            <div class="rounded-lg border border-gray-100 bg-gray-50/80 p-3 dark:border-dark-700 dark:bg-dark-800/40">
              <p class="text-xs text-gray-500 dark:text-gray-400">最近成功时间</p>
              <p class="mt-1 text-xs text-gray-800 dark:text-gray-200">
                {{ status?.last_success || '暂无' }}
              </p>
            </div>
            <div class="rounded-lg border border-gray-100 bg-gray-50/80 p-3 dark:border-dark-700 dark:bg-dark-800/40">
              <p class="text-xs text-gray-500 dark:text-gray-400">是否配置代理</p>
              <p class="mt-1 text-xs text-gray-800 dark:text-gray-200">
                {{ status?.proxy ? '已配置' : '未配置' }}
              </p>
            </div>
            <div class="rounded-lg border border-gray-100 bg-gray-50/80 p-3 dark:border-dark-700 dark:bg-dark-800/40">
              <p class="text-xs text-gray-500 dark:text-gray-400">休眠区间（秒）</p>
              <p class="mt-1 text-xs text-gray-800 dark:text-gray-200">
                {{ status ? `${status.sleep_min} - ${status.sleep_max}` : '--' }}
              </p>
            </div>
          </div>

          <div
            v-if="status?.last_error"
            class="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900/60 dark:bg-red-900/30 dark:text-red-300"
          >
            <div class="mb-1 font-medium">最近错误日志</div>
            <pre class="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] leading-snug">{{ status.last_error }}</pre>
          </div>

          <p v-if="error" class="text-xs text-red-600 dark:text-red-400">
            {{ error }}
          </p>
        </div>
      </div>

      <div class="card">
        <div class="border-b border-gray-100 px-6 py-4 dark:border-dark-700">
          <h2 class="text-base font-semibold text-gray-900 dark:text-white">最近事件</h2>
        </div>

        <div class="p-6 text-sm text-gray-700 dark:text-gray-200">
          <div
            v-if="logs.length === 0"
            class="text-xs text-gray-500 dark:text-gray-400"
          >
            暂无事件
          </div>
          <div
            v-else
            class="max-h-64 overflow-auto rounded-lg border border-gray-100 text-xs dark:border-dark-700"
          >
            <div
              v-for="(log, idx) in logs"
              :key="`${log.time}-${log.level}-${log.message}-${idx}`"
              class="border-b border-gray-100 px-3 py-2 whitespace-pre-wrap text-[11px] leading-snug last:border-b-0 dark:border-dark-700"
            >
              [{{ log.level }}] {{ log.time }} - {{ log.message }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { adminAPI } from '@/api/admin'
import type { CodexLogEntry, CodexStatus } from '@/api/admin/codex'

const status = ref<CodexStatus | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const logs = ref<CodexLogEntry[]>([])
let timer: number | undefined

function getErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    const message = error.message
    if (typeof message === 'string' && message) {
      return message
    }
  }

  return error instanceof Error ? error.message : String(error)
}

async function fetchStatus() {
  try {
    const data = await adminAPI.codex.getStatus()
    status.value = data
    error.value = null
  } catch (errorValue) {
    error.value = getErrorMessage(errorValue)
  }
}

async function fetchLogs() {
  try {
    const data = await adminAPI.codex.getLogs()
    logs.value = data
  } catch (errorValue) {
    error.value = getErrorMessage(errorValue)
  }
}

// biome-ignore lint/correctness/noUnusedVariables: referenced by template events
async function toggleEnabled(value: boolean) {
  if (loading.value) return
  loading.value = true
  try {
    const data = value ? await adminAPI.codex.enable() : await adminAPI.codex.disable()
    status.value = data
    error.value = null
  } catch (errorValue) {
    error.value = getErrorMessage(errorValue)
  } finally {
    loading.value = false
  }
}

// biome-ignore lint/correctness/noUnusedVariables: referenced by template events
async function runOnce() {
  if (loading.value) return
  loading.value = true
  try {
    const data = await adminAPI.codex.runOnce()
    status.value = data
    error.value = null
  } catch (errorValue) {
    error.value = getErrorMessage(errorValue)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void fetchStatus()
  void fetchLogs()
  timer = window.setInterval(() => {
    if (loading.value) {
      return
    }
    void fetchStatus()
    void fetchLogs()
  }, 10000)
})

onUnmounted(() => {
  if (timer !== undefined) {
    window.clearInterval(timer)
  }
})
</script>
