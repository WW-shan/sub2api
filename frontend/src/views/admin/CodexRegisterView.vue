<template>
  <AppLayout>
    <div class="mx-auto max-w-6xl space-y-6">
      <div class="card overflow-hidden">
        <div class="card-header flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div class="space-y-3">
            <div class="flex flex-wrap items-center gap-3">
              <span
                :class="[
                  'inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium',
                  status?.enabled
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-900/20 dark:text-emerald-300'
                    : 'border-gray-200 bg-gray-100 text-gray-600 dark:border-dark-600 dark:bg-dark-700 dark:text-gray-300'
                ]"
              >
                {{ status?.enabled ? '运行中' : '已停止' }}
              </span>
              <span class="inline-flex items-center rounded-full border border-primary-200 bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700 dark:border-primary-900/60 dark:bg-primary-900/20 dark:text-primary-300">
                Admin Console
              </span>
            </div>
            <div>
              <h1 class="text-2xl font-semibold tracking-tight text-gray-900 dark:text-white">Codex 注册</h1>
              <p class="mt-2 max-w-3xl text-sm leading-6 text-gray-500 dark:text-gray-400">
                管理 Codex 自动注册服务的运行状态、执行节奏和最近事件，让这套能力和后台其他运维页面保持同一视觉与信息层级。
              </p>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="refreshing || loading"
              @click="refreshAll"
            >
              {{ refreshing ? '刷新中…' : '刷新' }}
            </button>
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

        <div class="card-body space-y-6">
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard title="累计生成账号数" :value="status?.total_created ?? 0" :icon="AccountsIcon" icon-variant="primary" />
            <StatCard title="最近成功时间" :value="status?.last_success || '暂无'" :icon="ClockIcon" icon-variant="success" />
            <StatCard title="是否配置代理" :value="status?.proxy ? '已配置' : '未配置'" :icon="NetworkIcon" icon-variant="warning" />
            <StatCard title="休眠区间（秒）" :value="status ? `${status.sleep_min} - ${status.sleep_max}` : '--'" :icon="PulseIcon" icon-variant="danger" />
          </div>

          <p v-if="error" class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-900/20 dark:text-red-300">
            {{ error }}
          </p>
        </div>
      </div>

      <div class="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <div class="card overflow-hidden">
          <div class="card-header">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 class="text-base font-semibold text-gray-900 dark:text-white">当前状态</h2>
                <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  统一查看当前开关状态、代理配置和最近一次失败信息。
                </p>
              </div>
              <span class="text-xs text-gray-400 dark:text-gray-500">自动轮询：10 秒</span>
            </div>
          </div>
          <div class="card-body space-y-4">
            <div class="grid gap-3 sm:grid-cols-2">
              <div class="rounded-xl border border-gray-200 bg-gray-50/80 p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">服务状态</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                  {{ status?.enabled ? '当前状态：已开启自动注册' : '当前状态：已关闭自动注册' }}
                </p>
              </div>
              <div class="rounded-xl border border-gray-200 bg-gray-50/80 p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">代理配置</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                  {{ status?.proxy ? '已配置代理，容器可按当前出口执行注册' : '未配置代理，请确认网络出口要求' }}
                </p>
              </div>
              <div class="rounded-xl border border-gray-200 bg-gray-50/80 p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">最近成功时间</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                  {{ status?.last_success || '暂无成功记录' }}
                </p>
              </div>
              <div class="rounded-xl border border-gray-200 bg-gray-50/80 p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">休眠区间</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                  {{ status ? `${status.sleep_min} - ${status.sleep_max} 秒` : '--' }}
                </p>
              </div>
            </div>

            <div
              :class="[
                'rounded-xl border p-4',
                status?.last_error
                  ? 'border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-900/20'
                  : 'border-emerald-200 bg-emerald-50 dark:border-emerald-900/60 dark:bg-emerald-900/10'
              ]"
            >
              <div class="flex items-center justify-between gap-3">
                <h3
                  :class="[
                    'text-sm font-semibold',
                    status?.last_error ? 'text-red-700 dark:text-red-300' : 'text-emerald-700 dark:text-emerald-300'
                  ]"
                >
                  最近错误日志
                </h3>
                <span
                  :class="[
                    'text-xs',
                    status?.last_error ? 'text-red-500 dark:text-red-400' : 'text-emerald-500 dark:text-emerald-400'
                  ]"
                >
                  {{ status?.last_error ? '需关注' : '暂无错误' }}
                </span>
              </div>
              <pre
                v-if="status?.last_error"
                class="mt-3 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg border border-red-200/80 bg-white/70 p-3 text-[11px] leading-snug text-red-800 dark:border-red-900/60 dark:bg-dark-950/60 dark:text-red-200"
              >{{ status.last_error }}</pre>
              <p v-else class="mt-3 text-sm text-emerald-700 dark:text-emerald-300">
                最近没有错误输出，服务状态看起来正常。
              </p>
            </div>
          </div>
        </div>

        <div class="card overflow-hidden">
          <div class="card-header">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 class="text-base font-semibold text-gray-900 dark:text-white">最近事件</h2>
                <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">展示服务最近的运行记录和错误，便于快速排查容器执行情况。</p>
              </div>
              <span class="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-500 dark:border-dark-600 dark:bg-dark-700 dark:text-gray-300">
                {{ logs.length }} 条记录
              </span>
            </div>
          </div>

          <div class="card-body">
            <div
              v-if="logs.length === 0"
              class="rounded-xl border border-dashed border-gray-200 px-6 py-10 text-center text-sm text-gray-500 dark:border-dark-700 dark:text-gray-400"
            >
              暂无事件
            </div>
            <div
              v-else
              class="max-h-[28rem] overflow-auto rounded-xl border border-gray-200 dark:border-dark-700"
            >
              <div
                v-for="(log, idx) in logs"
                :key="`${log.time}-${log.level}-${log.message}-${idx}`"
                class="border-b border-gray-100 px-4 py-3 last:border-b-0 dark:border-dark-800"
              >
                <div class="flex items-center justify-between gap-3 text-[11px]">
                  <span
                    :class="[
                      'inline-flex items-center rounded-full px-2 py-0.5 font-semibold uppercase tracking-wide',
                      log.level === 'error'
                        ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                        : log.level === 'warn'
                          ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
                          : 'bg-gray-100 text-gray-600 dark:bg-dark-700 dark:text-gray-300'
                    ]"
                  >
                    {{ log.level }}
                  </span>
                  <span class="text-gray-400 dark:text-gray-500">{{ log.time }}</span>
                </div>
                <p class="mt-2 whitespace-pre-wrap break-words text-xs leading-6 text-gray-700 dark:text-gray-200">
                  {{ log.message }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { h, onMounted, onUnmounted, ref } from 'vue'
import { adminAPI } from '@/api/admin'
import type { CodexLogEntry, CodexStatus } from '@/api/admin/codex'
import StatCard from '@/components/common/StatCard.vue'

const status = ref<CodexStatus | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const logs = ref<CodexLogEntry[]>([])
const refreshing = ref(false)
let timer: number | undefined

const AccountsIcon = {
  render: () => h('svg', { fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.8' }, [
    h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M17 20a4 4 0 00-8 0m8 0H7m10 0h3m-3 0a4 4 0 00-8 0m0-8a4 4 0 118 0 4 4 0 01-8 0zm8 0a4 4 0 11-8 0 4 4 0 018 0z' })
  ])
}

const ClockIcon = {
  render: () => h('svg', { fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.8' }, [
    h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M12 6v6l4 2m5-2a9 9 0 11-18 0 9 9 0 0118 0z' })
  ])
}

const NetworkIcon = {
  render: () => h('svg', { fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.8' }, [
    h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M7 17a4 4 0 010-8m10 8a4 4 0 000-8M8 12h8M12 7v10' })
  ])
}

const PulseIcon = {
  render: () => h('svg', { fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.8' }, [
    h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: 'M3 12h4l3-7 4 14 3-7h4' })
  ])
}

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

async function refreshAll() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([fetchStatus(), fetchLogs()])
  } finally {
    refreshing.value = false
  }
}

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
  await fetchLogs()
}

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
  await fetchLogs()
}

onMounted(() => {
  void refreshAll()
  timer = window.setInterval(() => {
    if (loading.value || refreshing.value) {
      return
    }
    void refreshAll()
  }, 10000)
})

onUnmounted(() => {
  if (timer !== undefined) {
    window.clearInterval(timer)
  }
})

defineExpose({
  StatCard,
  AccountsIcon,
  ClockIcon,
  NetworkIcon,
  PulseIcon,
  toggleEnabled,
  runOnce
})
</script>
