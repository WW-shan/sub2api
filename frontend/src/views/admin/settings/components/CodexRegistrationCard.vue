<template>
  <div
    :class="[
      'card overflow-hidden transition-shadow duration-200',
      active ? 'shadow-2xl ring-1 ring-primary-500/40' : 'shadow-sm'
    ]"
  >
    <div class="card-body space-y-6">
      <div
        class="border-b border-gray-100 pb-6 dark:border-dark-700"
        data-testid="codex-controlbar"
      >
        <div class="flex flex-col gap-4 xl:grid xl:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] xl:items-center">
          <div class="space-y-3" data-testid="codex-controlbar-status">
            <div class="flex flex-wrap items-center gap-3">
              <span
                :class="[
                  'inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium',
                  statusBadgeToneClass
                ]"
              >
                {{ statusBadgeLabel }}
              </span>
              <span class="inline-flex items-center rounded-full border border-primary-200 bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700 dark:border-primary-900/60 dark:bg-primary-900/20 dark:text-primary-300">
                {{ t('admin.codexRegister.badge.adminConsole') }}
              </span>
              <span class="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-500 dark:border-dark-600 dark:bg-dark-700 dark:text-gray-300">
                {{ t('admin.codexRegister.panels.polling', { seconds: 10 }) }}
              </span>
            </div>
            <p class="truncate text-sm text-gray-500 dark:text-gray-400">
              {{ controlbarSummaryLabel }}
            </p>
          </div>

          <div class="flex justify-start xl:justify-center" data-testid="codex-controlbar-primary">
            <button
              type="button"
              class="btn btn-primary min-w-32"
              :disabled="loading || primaryAction === 'inProgress'"
              @click="triggerPrimaryAction"
            >
              {{ primaryActionLabel }}
            </button>
          </div>

          <div class="flex flex-wrap items-center gap-2 xl:justify-end" data-testid="codex-controlbar-secondary">
            <button
              type="button"
              class="btn btn-secondary"
              :disabled="refreshing || loading"
              @click="refreshAll"
            >
              {{ refreshing ? t('admin.codexRegister.actions.refreshing') : t('common.refresh') }}
            </button>
            <button
              type="button"
              class="btn btn-secondary"
              :disabled="loading || !canAbandon"
              @click="toggleEnabled(false)"
            >
              {{ t('admin.codexRegister.actions.stop') }}
            </button>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard :title="t('admin.codexRegister.summary.totalCreated')" :value="status?.total_created ?? 0" :icon="AccountsIcon" icon-variant="primary" />
        <StatCard :title="t('admin.codexRegister.summary.lastSuccess')" :value="lastSuccessLabel" :icon="ClockIcon" icon-variant="success" />
        <StatCard :title="t('admin.codexRegister.summary.proxy')" :value="proxySummaryLabel" :icon="NetworkIcon" icon-variant="warning" />
        <StatCard :title="t('admin.codexRegister.summary.sleepRange')" :value="sleepRangeSummaryLabel" :icon="PulseIcon" icon-variant="danger" />
      </div>

      <p v-if="error" class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-900/20 dark:text-red-300">
        {{ error }}
      </p>

      <section
        v-if="isWaitingManual"
        class="rounded-2xl border border-amber-200 bg-amber-50/70 p-5 dark:border-amber-900/60 dark:bg-amber-900/10"
      >
        <h3 class="text-sm font-semibold text-amber-800 dark:text-amber-300">
          {{ t('admin.codexRegister.waitingTodo.title') }}
        </h3>
        <p class="mt-2 text-sm text-amber-700 dark:text-amber-200">
          {{ waitingTodoReason }}
        </p>
        <ol class="mt-3 list-decimal space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-100">
          <li v-for="(step, index) in waitingTodoSteps" :key="`waiting-step-${index}`">{{ step }}</li>
        </ol>
        <p class="mt-3 text-sm font-medium text-amber-800 dark:text-amber-200">
          {{ t('admin.codexRegister.waitingTodo.afterTip') }}
        </p>
      </section>

      <div class="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <section class="rounded-2xl border border-gray-200 bg-gray-50/60 dark:border-dark-700 dark:bg-dark-900/20">
          <div class="border-b border-gray-200 px-6 py-4 dark:border-dark-700">
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">{{ t('admin.codexRegister.panels.statusTitle') }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {{ t('admin.codexRegister.panels.statusDescription') }}
            </p>
          </div>
          <div class="space-y-4 p-6">
            <div class="grid gap-3 sm:grid-cols-2">
              <div class="rounded-xl border border-gray-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">{{ t('admin.codexRegister.panels.serviceStatus') }}</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                  {{ serviceStatusLabel }}
                </p>
              </div>
              <div class="rounded-xl border border-gray-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">{{ t('admin.codexRegister.panels.proxyConfig') }}</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                  {{ proxyDetailLabel }}
                </p>
              </div>
              <div class="rounded-xl border border-gray-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">{{ t('admin.codexRegister.panels.phaseTitle') }}</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white break-all">
                  {{ codexPhaseLabel }}
                </p>
              </div>
              <div class="rounded-xl border border-gray-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">{{ t('admin.codexRegister.panels.waitingReasonTitle') }}</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white break-all">
                  {{ waitingReasonLabel }}
                </p>
              </div>
              <div class="rounded-xl border border-gray-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">{{ t('admin.codexRegister.panels.lastSuccessTitle') }}</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                  {{ lastSuccessLabel }}
                </p>
              </div>
              <div class="rounded-xl border border-gray-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/40">
                <p class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400">{{ t('admin.codexRegister.panels.sleepRangeTitle') }}</p>
                <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
                  {{ sleepRangeDetailLabel }}
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
                  {{ t('admin.codexRegister.panels.errorTitle') }}
                </h3>
                <span
                  :class="[
                    'text-xs',
                    status?.last_error ? 'text-red-500 dark:text-red-400' : 'text-emerald-500 dark:text-emerald-400'
                  ]"
                >
                  {{ errorStateLabel }}
                </span>
              </div>
              <pre
                v-if="status?.last_error"
                class="mt-3 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg border border-red-200/80 bg-white/70 p-3 text-[11px] leading-snug text-red-800 dark:border-red-900/60 dark:bg-dark-950/60 dark:text-red-200"
              >{{ status.last_error }}</pre>
              <p v-else class="mt-3 text-sm text-emerald-700 dark:text-emerald-300">
                {{ t('admin.codexRegister.panels.noErrors') }}
              </p>
            </div>
          </div>
        </section>

        <section class="rounded-2xl border border-gray-200 bg-gray-50/60 dark:border-dark-700 dark:bg-dark-900/20">
          <div class="flex items-center justify-between gap-3 border-b border-gray-200 px-6 py-4 dark:border-dark-700">
            <div>
              <h2 class="text-base font-semibold text-gray-900 dark:text-white">{{ t('admin.codexRegister.panels.eventsTitle') }}</h2>
              <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('admin.codexRegister.panels.eventsDescription') }}</p>
            </div>
            <span class="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500 dark:border-dark-600 dark:bg-dark-800 dark:text-gray-300">
              {{ t('admin.codexRegister.panels.eventCount', { count: logs.length }) }}
            </span>
          </div>

          <div class="p-6">
            <div
              v-if="logs.length === 0"
              class="rounded-xl border border-dashed border-gray-200 px-6 py-10 text-center text-sm text-gray-500 dark:border-dark-700 dark:text-gray-400"
            >
              {{ t('admin.codexRegister.panels.emptyEvents') }}
            </div>
            <div
              v-else
              class="max-h-[28rem] overflow-auto rounded-xl border border-gray-200 bg-white dark:border-dark-700 dark:bg-dark-900/40"
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
        </section>
      </div>

      <section class="rounded-2xl border border-gray-200 bg-gray-50/60 dark:border-dark-700 dark:bg-dark-900/20">
        <div class="flex items-center justify-between gap-3 border-b border-gray-200 px-6 py-4 dark:border-dark-700">
          <div>
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">{{ t('admin.codexRegister.accounts.title') }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('admin.codexRegister.accounts.description') }}</p>
          </div>
          <span class="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500 dark:border-dark-600 dark:bg-dark-800 dark:text-gray-300">
            {{ t('admin.codexRegister.panels.eventCount', { count: accounts.length }) }}
          </span>
        </div>

        <div class="p-6">
          <div
            v-if="accounts.length === 0"
            class="rounded-xl border border-dashed border-gray-200 px-6 py-10 text-center text-sm text-gray-500 dark:border-dark-700 dark:text-gray-400"
          >
            {{ t('admin.codexRegister.accounts.empty') }}
          </div>
          <div
            v-else
            class="overflow-auto rounded-xl border border-gray-200 bg-white dark:border-dark-700 dark:bg-dark-900/40"
          >
            <table class="min-w-full divide-y divide-gray-200 text-xs dark:divide-dark-700">
              <thead class="bg-gray-50 dark:bg-dark-800/60">
                <tr>
                  <th class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">{{ t('admin.codexRegister.accounts.columns.email') }}</th>
                  <th class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">{{ t('admin.codexRegister.accounts.columns.password') }}</th>
                  <th class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">{{ t('admin.codexRegister.accounts.columns.accessToken') }}</th>
                  <th class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">{{ t('admin.codexRegister.accounts.columns.refreshToken') }}</th>
                  <th class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">{{ t('admin.codexRegister.accounts.columns.accountId') }}</th>
                  <th class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">{{ t('admin.codexRegister.accounts.columns.createdAt') }}</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-100 dark:divide-dark-800">
                <tr v-for="account in accounts" :key="account.id">
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">{{ account.email }}</td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    <div class="flex items-center gap-2">
                      <span class="max-w-[220px] truncate whitespace-nowrap" :title="secretDisplayValue(account, 'password')">{{ secretDisplayValue(account, 'password') }}</span>
                      <button type="button" class="btn btn-secondary btn-sm" @click="toggleSecret(account.id, 'password')">
                        {{ isSecretRevealed(account.id, 'password') ? t('admin.codexRegister.actions.hide') : t('admin.codexRegister.actions.show') }}
                      </button>
                      <button type="button" class="btn btn-secondary btn-sm" @click="copyText(account.password)">{{ t('admin.codexRegister.actions.copy') }}</button>
                    </div>
                  </td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    <div class="flex items-center gap-2">
                      <span class="max-w-[220px] truncate whitespace-nowrap" :title="secretDisplayValue(account, 'access_token')">{{ secretDisplayValue(account, 'access_token') }}</span>
                      <button type="button" class="btn btn-secondary btn-sm" @click="toggleSecret(account.id, 'access_token')">
                        {{ isSecretRevealed(account.id, 'access_token') ? t('admin.codexRegister.actions.hide') : t('admin.codexRegister.actions.show') }}
                      </button>
                      <button type="button" class="btn btn-secondary btn-sm" @click="copyText(account.access_token)">{{ t('admin.codexRegister.actions.copy') }}</button>
                    </div>
                  </td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    <div class="flex items-center gap-2">
                      <span class="max-w-[220px] truncate whitespace-nowrap" :title="secretDisplayValue(account, 'refresh_token')">{{ secretDisplayValue(account, 'refresh_token') }}</span>
                      <button type="button" class="btn btn-secondary btn-sm" @click="toggleSecret(account.id, 'refresh_token')">
                        {{ isSecretRevealed(account.id, 'refresh_token') ? t('admin.codexRegister.actions.hide') : t('admin.codexRegister.actions.show') }}
                      </button>
                      <button type="button" class="btn btn-secondary btn-sm" @click="copyText(account.refresh_token)">{{ t('admin.codexRegister.actions.copy') }}</button>
                    </div>
                  </td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">{{ account.account_id || '-' }}</td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">{{ account.created_at || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { adminAPI } from '@/api/admin'
import type { CodexLogEntry, CodexRegisterAccount, CodexStatus } from '@/api/admin/codex'
import StatCard from '@/components/common/StatCard.vue'

const props = defineProps({
  active: {
    type: Boolean,
    default: false
  }
})

const { t } = useI18n()

const status = ref<CodexStatus | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const logs = ref<CodexLogEntry[]>([])
const accounts = ref<CodexRegisterAccount[]>([])
const refreshing = ref(false)
let timer: number | undefined
const POLL_INTERVAL = 10000

type PhaseTone = 'neutral' | 'running' | 'waiting' | 'failed'
type PrimaryAction = 'start' | 'resume' | 'inProgress'
type SecretField = 'password' | 'access_token' | 'refresh_token'

function phaseInfo(phase?: string | null): { label: string, tone: PhaseTone } {
  if (!phase) {
    return { label: t('admin.codexRegister.phase.unknown'), tone: 'neutral' }
  }

  if (phase === 'idle' || phase === 'completed') {
    return { label: t('admin.codexRegister.phase.idle'), tone: 'neutral' }
  }
  if (phase === 'running:create_parent') {
    return { label: t('admin.codexRegister.phase.runningCreateParent'), tone: 'running' }
  }
  if (phase.startsWith('waiting_manual:')) {
    return { label: t('admin.codexRegister.phase.waitingManual'), tone: 'waiting' }
  }
  if (phase === 'running:pre_resume_check') {
    return { label: t('admin.codexRegister.phase.runningPreResumeCheck'), tone: 'running' }
  }
  if (phase === 'running:invite_children') {
    return { label: t('admin.codexRegister.phase.runningInviteChildren'), tone: 'running' }
  }
  if (phase === 'running:accept_and_switch') {
    return { label: t('admin.codexRegister.phase.runningAcceptAndSwitch'), tone: 'running' }
  }
  if (phase === 'running:verify_and_bind') {
    return { label: t('admin.codexRegister.phase.runningVerifyAndBind'), tone: 'running' }
  }
  if (phase === 'abandoned') {
    return { label: t('admin.codexRegister.phase.abandoned'), tone: 'neutral' }
  }
  if (phase === 'failed') {
    return { label: t('admin.codexRegister.phase.failed'), tone: 'failed' }
  }

  return { label: phase, tone: 'neutral' }
}

function waitingReasonText(reason?: string | null): string {
  if (!reason) {
    return t('admin.codexRegister.panels.waitingReasonEmpty')
  }
  if (reason === 'parent_upgrade') {
    return t('admin.codexRegister.waitingReason.parentUpgrade')
  }
  return reason
}

const phaseState = computed(() => {
  if (!status.value) {
    return {
      label: error.value ? t('common.unknown') : t('common.loading'),
      tone: 'neutral' as PhaseTone
    }
  }
  return phaseInfo(status.value.job_phase)
})

const statusBadgeToneClass = computed(() => {
  if (phaseState.value.tone === 'running') {
    return 'border-primary-200 bg-primary-50 text-primary-700 dark:border-primary-900/60 dark:bg-primary-900/20 dark:text-primary-300'
  }
  if (phaseState.value.tone === 'waiting') {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-300'
  }
  if (phaseState.value.tone === 'failed') {
    return 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-900/20 dark:text-red-300'
  }
  return 'border-gray-200 bg-gray-100 text-gray-600 dark:border-dark-600 dark:bg-dark-700 dark:text-gray-300'
})

const statusBadgeLabel = computed(() => phaseState.value.label)
const serviceStatusLabel = computed(() => phaseState.value.label)

const controlbarSummaryLabel = computed(() => {
  if (!status.value) {
    return error.value ? t('common.unknown') : t('common.loading')
  }

  if (status.value.waiting_reason) {
    return waitingReasonText(status.value.waiting_reason)
  }

  return proxyDetailLabel.value
})

const proxySummaryLabel = computed(() => {
  if (status.value) {
    return status.value.proxy ? t('admin.codexRegister.summary.proxyConfigured') : t('admin.codexRegister.summary.proxyMissing')
  }

  return error.value ? t('common.unknown') : t('common.loading')
})

const proxyDetailLabel = computed(() => {
  if (status.value) {
    return status.value.proxy ? t('admin.codexRegister.panels.proxyConfiguredDetail') : t('admin.codexRegister.panels.proxyMissingDetail')
  }

  return error.value ? t('common.unknown') : t('common.loading')
})

const lastSuccessLabel = computed(() => {
  if (status.value) {
    return status.value.last_success || t('admin.codexRegister.panels.lastSuccessEmpty')
  }

  return error.value ? t('common.unknown') : t('common.loading')
})

const sleepRangeSummaryLabel = computed(() => {
  if (status.value) {
    return t('admin.codexRegister.summary.rangeValue', { min: status.value.sleep_min, max: status.value.sleep_max })
  }

  return error.value ? t('common.unknown') : t('common.loading')
})

const sleepRangeDetailLabel = computed(() => {
  if (status.value) {
    return t('admin.codexRegister.summary.rangeValueWithUnit', { min: status.value.sleep_min, max: status.value.sleep_max })
  }

  return error.value ? t('common.unknown') : t('common.loading')
})

const codexPhaseLabel = computed(() => {
  if (!status.value) {
    return error.value ? t('common.unknown') : t('common.loading')
  }

  return phaseInfo(status.value.job_phase).label
})

const waitingReasonLabel = computed(() => {
  if (!status.value) {
    return error.value ? t('common.unknown') : t('common.loading')
  }

  return waitingReasonText(status.value.waiting_reason)
})

const isWaitingManual = computed(() => Boolean(status.value?.job_phase?.startsWith('waiting_manual:')))
const waitingTodoReason = computed(() => waitingReasonText(status.value?.waiting_reason))
const waitingTodoSteps = computed(() => {
  if (status.value?.waiting_reason === 'parent_upgrade') {
    return [
      t('admin.codexRegister.waitingTodo.parentUpgrade.step1'),
      t('admin.codexRegister.waitingTodo.parentUpgrade.step2'),
      t('admin.codexRegister.waitingTodo.parentUpgrade.step3')
    ]
  }

  return [
    t('admin.codexRegister.waitingTodo.generic.step1'),
    t('admin.codexRegister.waitingTodo.generic.step2'),
    t('admin.codexRegister.waitingTodo.generic.step3')
  ]
})

const canStart = computed(() => Boolean(status.value?.can_start))
const canResume = computed(() => Boolean(status.value?.can_resume))
const canAbandon = computed(() => Boolean(status.value?.can_abandon))

const primaryAction = computed<PrimaryAction>(() => {
  if (canStart.value) return 'start'
  if (canResume.value) return 'resume'
  return 'inProgress'
})

const primaryActionLabel = computed(() => {
  if (primaryAction.value === 'start') return t('admin.codexRegister.actions.start')
  if (primaryAction.value === 'resume') return t('admin.codexRegister.actions.resume')
  return t('admin.codexRegister.actions.inProgress')
})

const revealedSecrets = ref<Record<string, boolean>>({})

function secretKey(accountId: number, field: SecretField): string {
  return `${accountId}:${field}`
}

function isSecretRevealed(accountId: number, field: SecretField): boolean {
  return Boolean(revealedSecrets.value[secretKey(accountId, field)])
}

function toggleSecret(accountId: number, field: SecretField) {
  const key = secretKey(accountId, field)
  revealedSecrets.value[key] = !revealedSecrets.value[key]
}

function maskSecret(value: string): string {
  if (!value) return '-'
  if (value.length <= 10) return '******'
  return `${value.slice(0, 6)}...${value.slice(-4)}`
}

function secretDisplayValue(account: CodexRegisterAccount, field: SecretField): string {
  const value = account[field] || ''
  return isSecretRevealed(account.id, field) ? value : maskSecret(value)
}

const errorStateLabel = computed(() => {
  if (!status.value) {
    return error.value ? t('common.unknown') : t('common.loading')
  }

  return status.value.last_error ? t('admin.codexRegister.badge.attention') : t('admin.codexRegister.badge.healthy')
})

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
    status.value = null
    error.value = getErrorMessage(errorValue)
  }
}

async function fetchLogs() {
  try {
    const data = await adminAPI.codex.getLogs()
    logs.value = data
  } catch (errorValue) {
    logs.value = []
    error.value = getErrorMessage(errorValue)
  }
}

async function fetchAccounts() {
  try {
    const data = await adminAPI.codex.getAccounts()
    accounts.value = data
  } catch (errorValue) {
    accounts.value = []
    error.value = getErrorMessage(errorValue)
  }
}

async function copyText(value: string) {
  if (!value) return
  await navigator.clipboard.writeText(value)
}

async function refreshAll() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([fetchStatus(), fetchLogs(), fetchAccounts()])
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

async function resumeWorkflow() {
  if (loading.value) return
  loading.value = true
  try {
    const data = await adminAPI.codex.resume()
    status.value = data
    error.value = null
  } catch (errorValue) {
    error.value = getErrorMessage(errorValue)
  } finally {
    loading.value = false
  }
  await fetchLogs()
}

async function triggerPrimaryAction() {
  if (primaryAction.value === 'start') {
    await toggleEnabled(true)
    return
  }
  if (primaryAction.value === 'resume') {
    await resumeWorkflow()
  }
}

function startPolling() {
  if (timer !== undefined) return
  void refreshAll()
  timer = window.setInterval(() => {
    if (loading.value || refreshing.value) {
      return
    }
    void refreshAll()
  }, POLL_INTERVAL)
}

function stopPolling() {
  if (timer !== undefined) {
    window.clearInterval(timer)
    timer = undefined
  }
}

watch(
  () => props.active,
  (isActive) => {
    if (isActive) {
      startPolling()
    } else {
      stopPolling()
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  stopPolling()
})

defineExpose({
  StatCard,
  AccountsIcon,
  ClockIcon,
  NetworkIcon,
  PulseIcon,
  statusBadgeLabel,
  serviceStatusLabel,
  proxySummaryLabel,
  proxyDetailLabel,
  lastSuccessLabel,
  sleepRangeSummaryLabel,
  sleepRangeDetailLabel,
  errorStateLabel,
  primaryAction,
  primaryActionLabel,
  triggerPrimaryAction,
  toggleEnabled,
  resumeWorkflow,
  isWaitingManual,
  waitingTodoSteps,
  maskSecret,
  secretDisplayValue,
  toggleSecret,
  isSecretRevealed
})
</script>
