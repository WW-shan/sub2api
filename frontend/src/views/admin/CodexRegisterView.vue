<template>
  <AppLayout>
    <div class="mx-auto max-w-3xl space-y-6">
      <div class="card p-6">
        <h1 class="mb-2 text-xl font-semibold text-gray-900 dark:text-white">
          Codex 自动注册服务
        </h1>
        <p class="text-sm text-gray-600 dark:text-gray-300">
          该页面用于说明 Codex 自动注册容器的工作方式，并提供开关与基础控制。
        </p>
      </div>

      <div class="card space-y-4 p-6 text-sm text-gray-700 dark:text-gray-200">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-gray-900 dark:text-white">当前状态</p>
            <p class="mt-1 text-sm">
              <span v-if="status?.enabled" class="text-green-600 dark:text-green-400">已开启自动注册</span>
              <span v-else class="text-gray-500 dark:text-gray-400">已关闭自动注册</span>
            </p>
          </div>
          <div class="flex gap-2">
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

        <div v-if="status" class="grid grid-cols-2 gap-4 md:grid-cols-3">
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">累计创建账号数</p>
            <p class="mt-1 text-lg font-semibold text-gray-900 dark:text-white">
              {{ status.total_created }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">最近成功时间</p>
            <p class="mt-1 text-xs text-gray-800 dark:text-gray-200">
              {{ status.last_success || '暂无' }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">休眠区间（秒）</p>
            <p class="mt-1 text-xs text-gray-800 dark:text-gray-200">
              {{ status.sleep_min }} - {{ status.sleep_max }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">是否配置代理</p>
            <p class="mt-1 text-xs text-gray-800 dark:text-gray-200">
              {{ status.proxy ? '已配置' : '未配置' }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">累计更新账号数</p>
            <p class="mt-1 text-lg font-semibold text-gray-900 dark:text-white">
              {{ status.total_updated }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">累计跳过次数</p>
            <p class="mt-1 text-lg font-semibold text-gray-900 dark:text-white">
              {{ status.total_skipped }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">本轮处理记录数</p>
            <p class="mt-1 text-lg font-semibold text-gray-900 dark:text-white">
              {{ status.last_processed_records }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">最近识别账号</p>
            <p class="mt-1 break-all text-xs text-gray-800 dark:text-gray-200">
              {{ status.last_token_email || '暂无' }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">最近创建账号</p>
            <p class="mt-1 break-all text-xs text-gray-800 dark:text-gray-200">
              {{ status.last_created_email || status.last_created_account_id || '暂无' }}
            </p>
          </div>
          <div>
            <p class="text-xs text-gray-500 dark:text-gray-400">最近更新账号</p>
            <p class="mt-1 break-all text-xs text-gray-800 dark:text-gray-200">
              {{ status.last_updated_email || status.last_updated_account_id || '暂无' }}
            </p>
          </div>
          <div class="md:col-span-3">
            <p class="text-xs text-gray-500 dark:text-gray-400">Codex 凭证目录</p>
            <p class="mt-1 break-all text-xs text-gray-800 dark:text-gray-200">
              {{ status.auth_dir || '未配置' }}
            </p>
          </div>
        </div>

        <div
          v-if="status?.last_error"
          class="rounded-md bg-red-50 p-3 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-300"
        >
          <div class="mb-1 font-medium">最近错误日志</div>
          <pre class="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] leading-snug">
{{ status.last_error }}
          </pre>
        </div>

        <p v-if="error" class="text-xs text-red-600 dark:text-red-400">
          {{ error }}
        </p>
      </div>

      <div class="card space-y-3 p-6 text-sm text-gray-700 dark:text-gray-200">
        <p>
          1. 在 <code>docker-compose.local.yml</code> 中会启动 <code>codex-register</code> 容器，并把 <code>deploy/codex_auth</code> 挂载到容器内的 <code>{{ status?.auth_dir || '/app/codex-auth' }}</code>。
        </p>
        <p>
          2. 将 Codex CLI 机器上的 <code>~/.codex/auth.json</code> 复制到该目录下任意子目录，例如 <code>deploy/codex_auth/user-a/auth.json</code>，服务会自动识别并导入。
        </p>
        <p>
          3. 每次导入/刷新后，新账号会直接写入 PostgreSQL 的 <code>accounts</code> 表，平台为 <code>openai</code>、类型为 <code>oauth</code>，并自动写入 <code>claude-* → gpt-5.4</code> 模型映射。
        </p>
        <p>
          4. 这些账号会自动出现在「渠道账户」页面中（管理后台 &gt; Accounts）。如需配置代理或频率，可设置 <code>CODEX_PROXY</code>、<code>CODEX_SLEEP_MIN</code>、<code>CODEX_SLEEP_MAX</code>、<code>CODEX_GROUP_IDS</code>。
        </p>
      </div>

      <div class="card space-y-2 p-6 text-sm text-gray-700 dark:text-gray-200">
        <p class="font-medium">最近事件</p>
        <div
          v-if="logs.length === 0"
          class="text-xs text-gray-500 dark:text-gray-400"
        >
          暂无事件
        </div>
        <div
          v-else
          class="max-h-64 space-y-1 overflow-auto border-t border-gray-100 pt-2 text-xs dark:border-dark-700"
        >
          <div
            v-for="(log, idx) in logs"
            :key="idx"
            class="whitespace-pre-wrap text-[11px] leading-snug"
          >
            [{{ log.level }}] {{ log.time }} - {{ log.message }}
          </div>
        </div>
      </div>

      <div class="card p-6 text-sm text-gray-700 dark:text-gray-200">
        <p class="mb-2 font-medium">快速入口</p>
        <router-link
          to="/admin/accounts"
          class="inline-flex items-center rounded-md border border-primary-500 px-3 py-1.5 text-sm font-medium text-primary-600 hover:bg-primary-50 dark:border-primary-400 dark:text-primary-300 dark:hover:bg-primary-900/20"
        >
          前往 Accounts 页面查看自动注册结果
        </router-link>
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

async function fetchStatus() {
  try {
    const data = await adminAPI.codex.getStatus()
    status.value = data
    error.value = null
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    error.value = msg
  }
}

async function fetchLogs() {
  try {
    const data = await adminAPI.codex.getLogs()
    logs.value = data
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    error.value = msg
  }
}

async function toggleEnabled(value: boolean) {
  if (loading.value) return
  loading.value = true
  try {
    const data = value ? await adminAPI.codex.enable() : await adminAPI.codex.disable()
    status.value = data
    error.value = null
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    error.value = msg
  } finally {
    loading.value = false
  }
}

async function runOnce() {
  if (loading.value) return
  loading.value = true
  try {
    const data = await adminAPI.codex.runOnce()
    status.value = data
    error.value = null
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    error.value = msg
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void fetchStatus()
  void fetchLogs()
  timer = window.setInterval(() => {
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

<style scoped>
</style>
