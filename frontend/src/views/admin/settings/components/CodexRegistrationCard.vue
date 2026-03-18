<template>
  <div
    :class="[
      'card overflow-hidden transition-shadow duration-200',
      active ? 'shadow-2xl ring-1 ring-primary-500/40' : 'shadow-sm',
    ]"
  >
    <div class="card-body space-y-6">
      <div
        class="border-b border-gray-100 pb-6 dark:border-dark-700"
        data-testid="codex-controlbar"
      >
        <div
          class="flex flex-col gap-4 xl:grid xl:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] xl:items-center"
        >
          <div class="space-y-3" data-testid="codex-controlbar-status">
            <div class="flex flex-wrap items-center gap-3">
              <span
                :class="[
                  'inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium',
                  statusBadgeToneClass,
                ]"
              >
                {{ statusBadgeLabel }}
              </span>
              <span
                class="inline-flex items-center rounded-full border border-primary-200 bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700 dark:border-primary-900/60 dark:bg-primary-900/20 dark:text-primary-300"
              >
                {{ t("admin.codexRegister.badge.adminConsole") }}
              </span>
              <span
                class="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-500 dark:border-dark-600 dark:bg-dark-700 dark:text-gray-300"
              >
                {{ t("admin.codexRegister.panels.polling", { seconds: 10 }) }}
              </span>
            </div>
            <p class="truncate text-sm text-gray-500 dark:text-gray-400">
              {{ controlbarSummaryLabel }}
            </p>
          </div>

          <div
            class="flex justify-start xl:justify-center"
            data-testid="codex-controlbar-primary"
          >
            <button
              type="button"
              class="btn btn-primary min-w-32"
              :disabled="loading || primaryAction === 'inProgress'"
              @click="triggerPrimaryAction"
            >
              {{ primaryActionLabel }}
            </button>
          </div>

          <div
            class="flex flex-wrap items-center gap-2 xl:justify-end"
            data-testid="codex-controlbar-secondary"
          >
            <button
              type="button"
              class="btn btn-secondary"
              :disabled="refreshing || loading"
              @click="refreshAll"
            >
              {{
                refreshing
                  ? t("admin.codexRegister.actions.refreshing")
                  : t("common.refresh")
              }}
            </button>
            <button
              type="button"
              class="btn btn-secondary"
              :disabled="loading || !secondaryActionEnabled"
              @click="triggerSecondaryAction"
            >
              {{ secondaryActionLabel }}
            </button>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          :title="t('admin.codexRegister.summary.totalCreated')"
          :value="status?.total_created ?? 0"
          :icon="AccountsIcon"
          icon-variant="primary"
        />
        <StatCard
          :title="t('admin.codexRegister.summary.lastSuccess')"
          :value="lastSuccessLabel"
          :icon="ClockIcon"
          icon-variant="success"
        />
        <StatCard
          :title="t('admin.codexRegister.summary.proxy')"
          :value="proxySummaryLabel"
          :icon="NetworkIcon"
          icon-variant="warning"
        />
        <StatCard
          :title="t('admin.codexRegister.summary.sleepRange')"
          :value="sleepRangeSummaryLabel"
          :icon="PulseIcon"
          icon-variant="danger"
        />
      </div>

      <p
        v-if="combinedError"
        class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-900/20 dark:text-red-300"
      >
        {{ combinedError }}
      </p>

      <section
        v-if="workflowFailureDetail"
        class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900/60 dark:bg-red-900/20"
        data-testid="codex-workflow-failure-detail"
      >
        <h3 class="text-sm font-semibold text-red-700 dark:text-red-300">
          Workflow Failed
        </h3>
        <p
          class="mt-2 whitespace-pre-wrap break-words text-xs leading-6 text-red-700 dark:text-red-200"
        >
          {{ workflowFailureDetail }}
        </p>
      </section>

      <section
        v-if="isWaitingManual"
        class="rounded-2xl border border-amber-200 bg-amber-50/70 p-5 dark:border-amber-900/60 dark:bg-amber-900/10"
      >
        <h3 class="text-sm font-semibold text-amber-800 dark:text-amber-300">
          {{ t("admin.codexRegister.waitingTodo.title") }}
        </h3>
        <p class="mt-2 text-sm text-amber-700 dark:text-amber-200">
          {{ waitingTodoReason }}
        </p>
        <ol
          class="mt-3 list-decimal space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-100"
        >
          <li
            v-for="(step, index) in waitingTodoSteps"
            :key="`waiting-step-${index}`"
          >
            {{ step }}
          </li>
        </ol>
        <p class="mt-3 text-sm font-medium text-amber-800 dark:text-amber-200">
          {{ t("admin.codexRegister.waitingTodo.afterTip") }}
        </p>
      </section>

      <section
        v-if="showSubscribeGate"
        class="rounded-2xl border border-primary-200 bg-primary-50/70 p-5 dark:border-primary-900/60 dark:bg-primary-900/10"
        data-testid="codex-subscribe-gate"
      >
        <h3 class="text-sm font-semibold text-primary-800 dark:text-primary-300">
          {{ t("admin.codexRegister.subscribeGate.title") }}
        </h3>
        <p class="mt-2 text-sm text-primary-700 dark:text-primary-200">
          {{ t("admin.codexRegister.subscribeGate.email") }}:
          {{ subscribeGateEmail || t("common.unknown") }}
        </p>

        <div v-if="subscribeGateHasTokenControls" class="mt-3" data-testid="codex-subscribe-gate-token">
          <p class="text-sm text-primary-800 dark:text-primary-100 break-all">
            {{ subscribeGateTokenDisplay }}
          </p>
          <div
            class="mt-3 flex flex-wrap items-center gap-2"
            data-testid="codex-subscribe-gate-controls"
          >
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              @click="subscribeGateTokenVisible = !subscribeGateTokenVisible"
            >
              {{
                subscribeGateTokenVisible
                  ? t("admin.codexRegister.actions.hide")
                  : t("admin.codexRegister.actions.show")
              }}
            </button>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              data-testid="codex-subscribe-gate-copy"
              @click="copySubscribeGateToken"
            >
              {{ t("admin.codexRegister.actions.copy") }}
            </button>
            <button
              type="button"
              class="btn btn-primary btn-sm"
              @click="resumeWorkflow"
            >
              {{ t("admin.codexRegister.actions.resume") }}
            </button>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              @click="toggleEnabled(false)"
            >
              {{ t("admin.codexRegister.actions.stop") }}
            </button>
          </div>
          <p
            v-if="subscribeGateCopyHint"
            class="mt-2 text-xs text-primary-700 dark:text-primary-300"
            data-testid="codex-subscribe-gate-copy-hint"
          >
            {{ subscribeGateCopyHint }}
          </p>
        </div>

        <p
          v-else
          class="mt-3 text-xs text-primary-700 dark:text-primary-300"
          data-testid="codex-subscribe-gate-diagnostic"
        >
          {{ subscribeGateDiagnosticHint }}
        </p>
      </section>

      <section
        class="rounded-2xl border border-slate-200 bg-white/70 p-6 dark:border-dark-700 dark:bg-dark-900/40"
        data-testid="codex-debug-snapshot"
        data-section-order="debug"
      >
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">
              {{ t("admin.codexRegister.debug.snapshotTitle") }}
            </h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {{ resumeDiagnosticLabel }}
            </p>
          </div>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            data-testid="codex-debug-raw-toggle"
            @click="showRawSnapshot = !showRawSnapshot"
          >
            {{
              showRawSnapshot
                ? t("admin.codexRegister.debug.hideRaw")
                : t("admin.codexRegister.debug.showRaw")
            }}
          </button>
        </div>

        <div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div
            class="rounded-xl border border-slate-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/60"
          >
            <p
              class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400"
            >
              {{ t("admin.codexRegister.debug.phaseLabel") }}
            </p>
            <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
              {{ codexPhaseLabel }}
            </p>
          </div>
          <div
            class="rounded-xl border border-slate-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/60"
          >
            <p
              class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400"
            >
              {{ t("admin.codexRegister.debug.waitingLabel") }}
            </p>
            <p class="mt-2 text-sm font-medium text-gray-900 dark:text-white">
              {{ waitingReasonLabel }}
            </p>
          </div>
          <div
            class="rounded-xl border border-slate-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/60"
          >
            <p
              class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400"
            >
              {{ t("admin.codexRegister.debug.gateLabel") }}
            </p>
            <p
              class="mt-2 text-sm font-medium text-gray-900 dark:text-white break-all"
            >
              {{ resumeGateLabel }}
            </p>
          </div>
          <div
            class="rounded-xl border border-slate-200 bg-white p-4 dark:border-dark-700 dark:bg-dark-900/60"
          >
            <p
              class="text-xs font-medium uppercase tracking-[0.18em] text-gray-400 dark:text-dark-400"
            >
              {{ t("admin.codexRegister.debug.transitionLabel") }}
            </p>
            <p
              class="mt-2 text-sm font-medium text-gray-900 dark:text-white break-all"
            >
              {{ transitionMainLabel }}
            </p>
            <div
              class="mt-2 space-y-1 text-xs text-gray-500 dark:text-gray-400"
            >
              <p>
                {{ t("admin.codexRegister.debug.transitionReason") }}:
                {{ transitionReasonLabel }}
              </p>
              <p>
                {{ t("admin.codexRegister.debug.transitionTime") }}:
                {{ transitionTimeLabel }}
              </p>
            </div>
          </div>
        </div>

        <div
          v-if="showRawSnapshot"
          class="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600 dark:border-dark-700 dark:bg-dark-900/60 dark:text-slate-200"
          data-testid="codex-debug-raw-values"
        >
          <p>
            {{ t("admin.codexRegister.debug.rawPhase") }}:
            {{ status?.job_phase || "-" }}
          </p>
          <p>
            {{ t("admin.codexRegister.debug.rawWaiting") }}:
            {{ status?.waiting_reason || "-" }}
          </p>
          <p>
            {{ t("admin.codexRegister.debug.rawGate") }}:
            {{ status?.last_resume_gate_reason || "-" }}
          </p>
        </div>
      </section>

      <section
        class="rounded-2xl border border-gray-200 bg-gray-50/60 dark:border-dark-700 dark:bg-dark-900/20"
        data-section-order="events"
      >
        <div
          class="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-6 py-4 dark:border-dark-700"
        >
          <div>
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">
              {{ t("admin.codexRegister.panels.eventsTitle") }}
            </h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {{ t("admin.codexRegister.panels.eventsDescription") }}
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <label class="text-xs font-medium text-gray-500 dark:text-gray-400">
              {{ t("admin.codexRegister.debug.logLevel") }}
              <select
                v-model="selectedLogLevel"
                class="ml-2 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs dark:border-dark-700 dark:bg-dark-900"
                data-testid="codex-log-level"
              >
                <option value="all">all</option>
                <option value="info">info</option>
                <option value="warn">warn</option>
                <option value="error">error</option>
              </select>
            </label>
            <label class="text-xs font-medium text-gray-500 dark:text-gray-400">
              {{ t("admin.codexRegister.debug.logLimit") }}
              <select
                v-model.number="selectedLogLimit"
                class="ml-2 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs dark:border-dark-700 dark:bg-dark-900"
                data-testid="codex-log-limit"
              >
                <option :value="50">50</option>
                <option :value="100">100</option>
                <option :value="200">200</option>
              </select>
            </label>
            <label
              class="flex items-center gap-2 text-xs font-medium text-gray-500 dark:text-gray-400"
            >
              <input
                v-model="resumeOnly"
                type="checkbox"
                class="rounded border-gray-300"
                data-testid="codex-log-resume-only"
              />
              {{ t("admin.codexRegister.debug.resumeOnly") }}
            </label>
            <span
              class="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500 dark:border-dark-600 dark:bg-dark-800 dark:text-gray-300"
            >
              {{
                t("admin.codexRegister.panels.eventCount", {
                  count: visibleLogs.length,
                })
              }}
            </span>
          </div>
        </div>

        <div class="p-6">
          <div
            v-if="visibleLogs.length === 0"
            class="rounded-xl border border-dashed border-gray-200 px-6 py-10 text-center text-sm text-gray-500 dark:border-dark-700 dark:text-gray-400"
          >
            {{ t("admin.codexRegister.panels.emptyEvents") }}
          </div>
          <div
            v-else
            class="max-h-[28rem] overflow-auto rounded-xl border border-gray-200 bg-white dark:border-dark-700 dark:bg-dark-900/40"
          >
            <div
              v-for="(log, idx) in visibleLogs"
              :key="`${log.time}-${log.level}-${log.message}-${idx}`"
              class="border-b border-gray-100 px-4 py-3 last:border-b-0 dark:border-dark-800"
              data-testid="codex-log-row"
            >
              <div class="flex items-center justify-between gap-3 text-[11px]">
                <span
                  :class="[
                    'inline-flex items-center rounded-full px-2 py-0.5 font-semibold uppercase tracking-wide',
                    log.level === 'error'
                      ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                      : log.level === 'warn'
                        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
                        : 'bg-gray-100 text-gray-600 dark:bg-dark-700 dark:text-gray-300',
                  ]"
                >
                  {{ log.level }}
                </span>
                <span class="text-gray-400 dark:text-gray-500">{{
                  log.time
                }}</span>
              </div>
              <p
                class="mt-2 whitespace-pre-wrap break-words text-xs leading-6 text-gray-700 dark:text-gray-200"
              >
                {{ log.message }}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section
        class="rounded-2xl border border-gray-200 bg-gray-50/60 dark:border-dark-700 dark:bg-dark-900/20"
      >
        <div
          class="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-6 py-4 dark:border-dark-700"
        >
          <div>
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">
              {{ t("admin.codexRegister.accounts.title") }}
            </h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {{ t("admin.codexRegister.accounts.description") }}
            </p>
          </div>
          <div class="flex items-center gap-2">
            <input
              v-model.trim="accountSearchKeyword"
              type="text"
              class="input input-sm w-52"
              :placeholder="t('admin.codexRegister.accounts.searchPlaceholder')"
              data-testid="codex-accounts-search"
            />
            <span
              class="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500 dark:border-dark-600 dark:bg-dark-800 dark:text-gray-300"
            >
              {{
                t("admin.codexRegister.panels.eventCount", {
                  count: filteredAccounts.length,
                })
              }}
            </span>
          </div>
        </div>

        <div class="p-6">
          <div
            v-if="filteredAccounts.length === 0"
            class="rounded-xl border border-dashed border-gray-200 px-6 py-10 text-center text-sm text-gray-500 dark:border-dark-700 dark:text-gray-400"
          >
            {{ t("admin.codexRegister.accounts.empty") }}
          </div>
          <div
            v-else
            class="overflow-auto rounded-xl border border-gray-200 bg-white dark:border-dark-700 dark:bg-dark-900/40"
            data-testid="codex-accounts-scroll"
          >
            <table
              class="min-w-full divide-y divide-gray-200 text-xs dark:divide-dark-700"
            >
              <thead class="bg-gray-50 dark:bg-dark-800/60">
                <tr>
                  <th
                    class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300"
                  >
                    {{ t("admin.codexRegister.accounts.columns.email") }}
                  </th>
                  <th
                    class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300"
                  >
                    Role
                  </th>
                  <th
                    class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300"
                  >
                    {{ t("admin.codexRegister.accounts.columns.accessToken") }}
                  </th>
                  <th
                    class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300"
                  >
                    {{ t("admin.codexRegister.accounts.columns.refreshToken") }}
                  </th>
                  <th
                    class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300"
                  >
                    {{ t("admin.codexRegister.accounts.columns.accountId") }}
                  </th>
                  <th
                    class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300"
                  >
                    {{ t("admin.codexRegister.accounts.columns.createdAt") }}
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-100 dark:divide-dark-800">
                <tr v-for="account in filteredAccounts" :key="account.id">
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    {{ account.email }}
                  </td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    <span
                      :class="[
                        'inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold',
                        (account.codex_register_role || account.source) ===
                        'parent'
                          ? 'border border-purple-200 bg-purple-100 text-purple-800 dark:border-purple-900/60 dark:bg-purple-900/30 dark:text-purple-300'
                          : 'border border-blue-200 bg-blue-100 text-blue-800 dark:border-blue-900/60 dark:bg-blue-900/30 dark:text-blue-300',
                      ]"
                    >
                      {{
                        account.codex_register_role ||
                        account.source ||
                        "unknown"
                      }}
                    </span>
                  </td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    <div class="flex items-center gap-2">
                      <span
                        class="max-w-[220px] truncate whitespace-nowrap"
                        :title="secretDisplayValue(account, 'access_token')"
                        >{{ secretDisplayValue(account, "access_token") }}</span
                      >
                      <button
                        type="button"
                        class="btn btn-secondary btn-sm"
                        @click="toggleSecret(account.id, 'access_token')"
                      >
                        {{
                          isSecretRevealed(account.id, "access_token")
                            ? t("admin.codexRegister.actions.hide")
                            : t("admin.codexRegister.actions.show")
                        }}
                      </button>
                      <button
                        type="button"
                        class="btn btn-secondary btn-sm"
                        @click="copyText(account.access_token ?? '')"
                      >
                        {{ t("admin.codexRegister.actions.copy") }}
                      </button>
                    </div>
                  </td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    <div class="flex items-center gap-2">
                      <span
                        class="max-w-[220px] truncate whitespace-nowrap"
                        :title="secretDisplayValue(account, 'refresh_token')"
                        >{{
                          secretDisplayValue(account, "refresh_token")
                        }}</span
                      >
                      <button
                        type="button"
                        class="btn btn-secondary btn-sm"
                        @click="toggleSecret(account.id, 'refresh_token')"
                      >
                        {{
                          isSecretRevealed(account.id, "refresh_token")
                            ? t("admin.codexRegister.actions.hide")
                            : t("admin.codexRegister.actions.show")
                        }}
                      </button>
                      <button
                        type="button"
                        class="btn btn-secondary btn-sm"
                        @click="copyText(account.refresh_token ?? '')"
                      >
                        {{ t("admin.codexRegister.actions.copy") }}
                      </button>
                    </div>
                  </td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    {{ account.account_id || "-" }}
                  </td>
                  <td class="px-3 py-2 text-gray-700 dark:text-gray-200">
                    {{ account.created_at || "-" }}
                  </td>
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
import { computed, h, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { adminAPI } from "@/api/admin";
import type {
  CodexLogEntry,
  CodexRegisterAccount,
  CodexStatus,
} from "@/api/admin/codex";
import StatCard from "@/components/common/StatCard.vue";

const props = defineProps({
  active: {
    type: Boolean,
    default: false,
  },
});

const { t } = useI18n();

const status = ref<CodexStatus | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const statusError = ref<string | null>(null);
const logsError = ref<string | null>(null);
const accountsError = ref<string | null>(null);
const logs = ref<CodexLogEntry[]>([]);
const accounts = ref<CodexRegisterAccount[]>([]);
const refreshing = ref(false);
let timer: number | undefined;
const POLL_INTERVAL = 10000;
const selectedLogLevel = ref<"all" | "info" | "warn" | "error">("all");
const selectedLogLimit = ref(200);
const resumeOnly = ref(false);
const showRawSnapshot = ref(false);
const accountSearchKeyword = ref("");
const subscribeGateTokenVisible = ref(false);
const subscribeGateCopyHint = ref("");

const visibleLogs = computed(() => {
  const level = selectedLogLevel.value;
  const onlyResume = resumeOnly.value;

  return logs.value.filter((log, index) => {
    if (index >= selectedLogLimit.value) {
      return false;
    }

    if (level !== "all" && log.level !== level) {
      return false;
    }

    if (onlyResume && !String(log.message || "").includes("resume")) {
      return false;
    }

    return true;
  });
});

type PhaseTone = "neutral" | "running" | "waiting" | "failed";
type PrimaryAction = "start" | "resume" | "inProgress";
type SecretField = "access_token" | "refresh_token";

function phaseInfo(phase?: string | null): { label: string; tone: PhaseTone } {
  if (!phase) {
    return { label: t("admin.codexRegister.phase.unknown"), tone: "neutral" };
  }

  if (phase === "idle") {
    return { label: t("admin.codexRegister.phase.idle"), tone: "neutral" };
  }
  if (phase === "completed") {
    return { label: t("admin.codexRegister.phase.completed"), tone: "neutral" };
  }
  if (phase === "running:get_tokens") {
    return {
      label: t("admin.codexRegister.phase.runningGetTokens"),
      tone: "running",
    };
  }
  if (phase === "waiting_manual:subscribe_then_resume") {
    return {
      label: t("admin.codexRegister.phase.waitingSubscribeThenResume"),
      tone: "waiting",
    };
  }
  if (phase === "running:gpt_team_batch") {
    return {
      label: t("admin.codexRegister.phase.runningGptTeamBatch"),
      tone: "running",
    };
  }
  if (phase === "running:create_parent") {
    return {
      label: t("admin.codexRegister.phase.runningCreateParent"),
      tone: "running",
    };
  }
  if (phase.startsWith("waiting_manual:")) {
    return {
      label: t("admin.codexRegister.phase.waitingManual"),
      tone: "waiting",
    };
  }
  if (phase === "running:pre_resume_check") {
    return {
      label: t("admin.codexRegister.phase.runningPreResumeCheck"),
      tone: "running",
    };
  }
  if (phase === "running:invite_children") {
    return {
      label: t("admin.codexRegister.phase.runningInviteChildren"),
      tone: "running",
    };
  }
  if (phase === "running:accept_and_switch") {
    return {
      label: t("admin.codexRegister.phase.runningAcceptAndSwitch"),
      tone: "running",
    };
  }
  if (phase === "running:verify_and_bind") {
    return {
      label: t("admin.codexRegister.phase.runningVerifyAndBind"),
      tone: "running",
    };
  }
  if (phase === "abandoned") {
    return { label: t("admin.codexRegister.phase.abandoned"), tone: "neutral" };
  }
  if (phase === "failed") {
    return { label: t("admin.codexRegister.phase.failed"), tone: "failed" };
  }

  return { label: phase, tone: "neutral" };
}

function waitingReasonText(reason?: string | null): string {
  if (!reason) {
    return t("admin.codexRegister.panels.waitingReasonEmpty");
  }
  if (reason === "parent_upgrade") {
    return t("admin.codexRegister.waitingReason.parentUpgrade");
  }
  if (reason === "subscribe_then_resume") {
    return t("admin.codexRegister.waitingReason.subscribeThenResume");
  }
  return reason;
}

const phaseState = computed(() => {
  if (!status.value) {
    return {
      label: error.value ? t("common.unknown") : t("common.loading"),
      tone: "neutral" as PhaseTone,
    };
  }
  return phaseInfo(status.value.job_phase);
});

const statusBadgeToneClass = computed(() => {
  if (phaseState.value.tone === "running") {
    return "border-primary-200 bg-primary-50 text-primary-700 dark:border-primary-900/60 dark:bg-primary-900/20 dark:text-primary-300";
  }
  if (phaseState.value.tone === "waiting") {
    return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-300";
  }
  if (phaseState.value.tone === "failed") {
    return "border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-900/20 dark:text-red-300";
  }
  return "border-gray-200 bg-gray-100 text-gray-600 dark:border-dark-600 dark:bg-dark-700 dark:text-gray-300";
});

const statusBadgeLabel = computed(() => phaseState.value.label);
const serviceStatusLabel = computed(() => phaseState.value.label);

const controlbarSummaryLabel = computed(() => {
  if (!status.value) {
    return combinedError.value ? t("common.unknown") : t("common.loading");
  }

  if (status.value.waiting_reason) {
    return waitingReasonText(status.value.waiting_reason);
  }

  if (batchSummary.value) {
    return batchProgressLabel.value;
  }

  return proxyDetailLabel.value;
});

const proxySummaryLabel = computed(() => {
  if (status.value) {
    return status.value.proxy
      ? t("admin.codexRegister.summary.proxyConfigured")
      : t("admin.codexRegister.summary.proxyMissing");
  }

  return error.value ? t("common.unknown") : t("common.loading");
});

const proxyDetailLabel = computed(() => {
  if (status.value) {
    return status.value.proxy
      ? t("admin.codexRegister.panels.proxyConfiguredDetail")
      : t("admin.codexRegister.panels.proxyMissingDetail");
  }

  return error.value ? t("common.unknown") : t("common.loading");
});

const lastSuccessLabel = computed(() => {
  if (status.value) {
    return (
      status.value.last_success ||
      t("admin.codexRegister.panels.lastSuccessEmpty")
    );
  }

  return error.value ? t("common.unknown") : t("common.loading");
});

const sleepRangeSummaryLabel = computed(() => {
  if (status.value) {
    return t("admin.codexRegister.summary.rangeValue", {
      min: status.value.sleep_min,
      max: status.value.sleep_max,
    });
  }

  return error.value ? t("common.unknown") : t("common.loading");
});

const sleepRangeDetailLabel = computed(() => {
  if (status.value) {
    return t("admin.codexRegister.summary.rangeValueWithUnit", {
      min: status.value.sleep_min,
      max: status.value.sleep_max,
    });
  }

  return error.value ? t("common.unknown") : t("common.loading");
});

const codexPhaseLabel = computed(() => {
  if (!status.value) {
    return combinedError.value ? t("common.unknown") : t("common.loading");
  }

  return phaseInfo(status.value.job_phase).label;
});

const waitingReasonLabel = computed(() => {
  if (!status.value) {
    return combinedError.value ? t("common.unknown") : t("common.loading");
  }

  return waitingReasonText(status.value.waiting_reason);
});

const snapshotTransition = computed(
  () => status.value?.last_transition ?? null,
);
const transitionMainLabel = computed(() => {
  const transition = snapshotTransition.value;
  return transition
    ? `${transition.from} → ${transition.to}`
    : t("admin.codexRegister.debug.transitionEmpty");
});
const transitionReasonLabel = computed(
  () => snapshotTransition.value?.reason || "-",
);
const transitionTimeLabel = computed(
  () => snapshotTransition.value?.time || "-",
);
const resumeGateLabel = computed(
  () =>
    status.value?.last_resume_gate_reason ||
    t("admin.codexRegister.debug.gateClear"),
);
const batchSummary = computed(() => status.value?.last_processed_summary ?? null);

const batchProgressLabel = computed(() => {
  const summary = batchSummary.value;
  if (!summary) {
    return t("admin.codexRegister.summary.batchEmpty");
  }
  const total = Number(summary.records_seen ?? 0);
  const created = Number(summary.created ?? 0);
  const failed = Number(summary.failed ?? 0);
  return t("admin.codexRegister.summary.batchProgress", {
    total,
    created,
    failed,
  });
});

const workflowFailureDetail = computed(() => {
  if (status.value?.job_phase !== "failed") {
    return "";
  }

  const latestFailureLog = [...logs.value]
    .reverse()
    .find((item) => String(item.message || "").includes("workflow_failed"));

  if (latestFailureLog?.message) {
    return latestFailureLog.message;
  }

  return status.value?.last_error || "";
});

const resumeDiagnosticLabel = computed(() => {
  if (!status.value) {
    return combinedError.value ? t("common.unknown") : t("common.loading");
  }

  return t("admin.codexRegister.debug.snapshotDescription");
});

const isWaitingManual = computed(() =>
  Boolean(status.value?.job_phase?.startsWith("waiting_manual:")),
);
const waitingTodoReason = computed(() =>
  waitingReasonText(status.value?.waiting_reason),
);
const waitingTodoSteps = computed(() => {
  if (status.value?.waiting_reason === "parent_upgrade") {
    return [
      t("admin.codexRegister.waitingTodo.parentUpgrade.step1"),
      t("admin.codexRegister.waitingTodo.parentUpgrade.step2"),
      t("admin.codexRegister.waitingTodo.parentUpgrade.step3"),
    ];
  }

  if (status.value?.waiting_reason === "subscribe_then_resume") {
    return [
      t("admin.codexRegister.waitingTodo.subscribeThenResume.step1"),
      t("admin.codexRegister.waitingTodo.subscribeThenResume.step2"),
      t("admin.codexRegister.waitingTodo.subscribeThenResume.step3"),
    ];
  }

  return [
    t("admin.codexRegister.waitingTodo.generic.step1"),
    t("admin.codexRegister.waitingTodo.generic.step2"),
    t("admin.codexRegister.waitingTodo.generic.step3"),
  ];
});

const showSubscribeGate = computed(() => {
  const phase = status.value?.job_phase || "";
  const manualAction = status.value?.manual_gate?.action || "";
  const hasResumeEmail = Boolean(status.value?.resume_context?.email);
  return (
    phase === "waiting_manual:subscribe_then_resume" ||
    manualAction === "subscribe_then_resume" ||
    (phase.startsWith("waiting_manual:") && hasResumeEmail)
  );
});

const subscribeGateEmail = computed(
  () => status.value?.resume_context?.email || "",
);
const subscribeGateRawToken = computed(
  () =>
    status.value?.resume_context?.access_token_raw ||
    status.value?.manual_gate?.token ||
    "",
);
const subscribeGateHasTokenControls = computed(() =>
  Boolean(subscribeGateEmail.value && subscribeGateRawToken.value),
);
const subscribeGateMissingContextHint = computed(() => {
  const translated = t(
    "admin.codexRegister.subscribeGate.missingResumeContextHint",
  );
  if (
    translated === "admin.codexRegister.subscribeGate.missingResumeContextHint"
  ) {
    return "Missing resume_context.email or resume_context.access_token_raw.";
  }
  return translated;
});
const subscribeGateDiagnosticHint = computed(() => {
  const backendHint = status.value?.resume_hint;
  if (backendHint) {
    return backendHint;
  }
  return subscribeGateMissingContextHint.value;
});
function maskSubscribeGateToken(value: string): string {
  if (!value) return "-";
  if (value.length <= 11) return "******";
  return `${value.slice(0, 7)}...${value.slice(-4)}`;
}

const subscribeGateTokenDisplay = computed(() =>
  subscribeGateTokenVisible.value
    ? subscribeGateRawToken.value
    : maskSubscribeGateToken(subscribeGateRawToken.value),
);

const filteredAccounts = computed(() => {
  const keyword = accountSearchKeyword.value.trim().toLowerCase();
  if (!keyword) {
    return accounts.value;
  }
  return accounts.value.filter((account) =>
    String(account.email || "")
      .toLowerCase()
      .includes(keyword),
  );
});

const canStart = computed(() => Boolean(status.value?.can_start));
const canResume = computed(() => Boolean(status.value?.can_resume));
const canAbandon = computed(() => Boolean(status.value?.can_abandon));
const secondaryActionLabel = computed(() => {
  return t("admin.codexRegister.actions.stop");
});

const secondaryActionEnabled = computed(() => {
  return canAbandon.value;
});

const primaryAction = computed<PrimaryAction>(() => {
  if (canStart.value) return "start";
  if (canResume.value) return "resume";
  return "inProgress";
});

const primaryActionLabel = computed(() => {
  if (primaryAction.value === "start")
    return t("admin.codexRegister.actions.start");
  if (primaryAction.value === "resume") {
    return t("admin.codexRegister.actions.resume");
  }
  return t("admin.codexRegister.actions.inProgress");
});

const revealedSecrets = ref<Record<string, boolean>>({});

function secretKey(accountId: number, field: SecretField): string {
  return `${accountId}:${field}`;
}

function isSecretRevealed(accountId: number, field: SecretField): boolean {
  return Boolean(revealedSecrets.value[secretKey(accountId, field)]);
}

function toggleSecret(accountId: number, field: SecretField) {
  const key = secretKey(accountId, field);
  revealedSecrets.value[key] = !revealedSecrets.value[key];
}

function maskSecret(value: string): string {
  if (!value) return "-";
  if (value.length <= 10) return "******";
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function secretDisplayValue(
  account: CodexRegisterAccount,
  field: SecretField,
): string {
  const value = account[field] || "";
  return isSecretRevealed(account.id, field) ? value : maskSecret(value);
}

const combinedError = computed(
  () => logsError.value || statusError.value || accountsError.value,
);
const errorStateLabel = computed(() => {
  if (!status.value) {
    return combinedError.value ? t("common.unknown") : t("common.loading");
  }

  return status.value.last_error
    ? t("admin.codexRegister.badge.attention")
    : t("admin.codexRegister.badge.healthy");
});

const AccountsIcon = {
  render: () =>
    h(
      "svg",
      {
        fill: "none",
        viewBox: "0 0 24 24",
        stroke: "currentColor",
        "stroke-width": "1.8",
      },
      [
        h("path", {
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          d: "M17 20a4 4 0 00-8 0m8 0H7m10 0h3m-3 0a4 4 0 00-8 0m0-8a4 4 0 118 0 4 4 0 01-8 0zm8 0a4 4 0 11-8 0 4 4 0 018 0z",
        }),
      ],
    ),
};

const ClockIcon = {
  render: () =>
    h(
      "svg",
      {
        fill: "none",
        viewBox: "0 0 24 24",
        stroke: "currentColor",
        "stroke-width": "1.8",
      },
      [
        h("path", {
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          d: "M12 6v6l4 2m5-2a9 9 0 11-18 0 9 9 0 0118 0z",
        }),
      ],
    ),
};

const NetworkIcon = {
  render: () =>
    h(
      "svg",
      {
        fill: "none",
        viewBox: "0 0 24 24",
        stroke: "currentColor",
        "stroke-width": "1.8",
      },
      [
        h("path", {
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          d: "M7 17a4 4 0 010-8m10 8a4 4 0 000-8M8 12h8M12 7v10",
        }),
      ],
    ),
};

const PulseIcon = {
  render: () =>
    h(
      "svg",
      {
        fill: "none",
        viewBox: "0 0 24 24",
        stroke: "currentColor",
        "stroke-width": "1.8",
      },
      [
        h("path", {
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          d: "M3 12h4l3-7 4 14 3-7h4",
        }),
      ],
    ),
};

function getErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = error.message;
    if (typeof message === "string" && message) {
      return message;
    }
  }

  return error instanceof Error ? error.message : String(error);
}

async function fetchStatus() {
  try {
    const data = await adminAPI.codex.getStatus();
    status.value = data;
    statusError.value = null;
    error.value = null;
  } catch (errorValue) {
    statusError.value = getErrorMessage(errorValue);
    error.value = statusError.value;
  }
}

async function fetchLogs() {
  try {
    const data = await adminAPI.codex.getLogs({
      level:
        selectedLogLevel.value === "all" ? undefined : selectedLogLevel.value,
      limit: selectedLogLimit.value,
    });
    logs.value = data;
    logsError.value = null;
    error.value = null;
  } catch (errorValue) {
    logsError.value = getErrorMessage(errorValue);
    error.value = logsError.value;
  }
}

function toTimestamp(value: string | null | undefined): number {
  if (!value) return Number.NEGATIVE_INFINITY;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
}

async function fetchAccounts() {
  try {
    const data = await adminAPI.codex.getAccounts();
    accounts.value = [...data].sort(
      (a, b) => toTimestamp(b.created_at) - toTimestamp(a.created_at),
    );
    accountsError.value = null;
    error.value = null;
  } catch (errorValue) {
    accounts.value = [];
    accountsError.value = getErrorMessage(errorValue);
    error.value = accountsError.value;
  }
}

async function copyText(value: string) {
  if (!value) return;
  await navigator.clipboard.writeText(value);
}

async function copySubscribeGateToken() {
  subscribeGateCopyHint.value = "";
  const token = subscribeGateRawToken.value;
  if (!token) {
    subscribeGateCopyHint.value = subscribeGateMissingContextHint.value;
    return;
  }
  try {
    await copyText(token);
  } catch (errorValue) {
    subscribeGateCopyHint.value = getErrorMessage(errorValue);
  }
}

async function refreshAll() {
  if (refreshing.value) return;
  refreshing.value = true;
  try {
    await Promise.all([fetchStatus(), fetchLogs(), fetchAccounts()]);
  } finally {
    refreshing.value = false;
  }
}

async function toggleEnabled(value: boolean) {
  if (loading.value) return;
  loading.value = true;
  try {
    const data = value
      ? await adminAPI.codex.enable()
      : await adminAPI.codex.disable();
    status.value = data;
    error.value = null;
  } catch (errorValue) {
    error.value = getErrorMessage(errorValue);
  } finally {
    loading.value = false;
  }
  await fetchLogs();
}

async function resumeWorkflow() {
  if (loading.value) return;
  loading.value = true;
  try {
    const data = await adminAPI.codex.resume();
    status.value = data;
    error.value = null;
  } catch (errorValue) {
    error.value = getErrorMessage(errorValue);
  } finally {
    loading.value = false;
  }
  await fetchLogs();
}

async function retryWorkflow() {
  if (loading.value) return;
  loading.value = true;
  try {
    const data = await adminAPI.codex.retry();
    status.value = data;
    error.value = null;
  } catch (errorValue) {
    error.value = getErrorMessage(errorValue);
  } finally {
    loading.value = false;
  }
  await fetchLogs();
}

async function triggerPrimaryAction() {
  if (primaryAction.value === "start") {
    await toggleEnabled(true);
    return;
  }
  if (primaryAction.value === "resume") {
    await resumeWorkflow();
  }
}

async function triggerSecondaryAction() {
  await toggleEnabled(false);
}

function startPolling() {
  if (timer !== undefined) return;
  void refreshAll();
  timer = window.setInterval(() => {
    if (loading.value || refreshing.value) {
      return;
    }
    void refreshAll();
  }, POLL_INTERVAL);
}

function stopPolling() {
  if (timer !== undefined) {
    window.clearInterval(timer);
    timer = undefined;
  }
}

watch([selectedLogLevel, selectedLogLimit], () => {
  void fetchLogs();
});

watch(
  () => props.active,
  (isActive) => {
    if (isActive) {
      startPolling();
    } else {
      stopPolling();
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  stopPolling();
});

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
  secondaryActionLabel,
  secondaryActionEnabled,
  triggerPrimaryAction,
  triggerSecondaryAction,
  toggleEnabled,
  resumeWorkflow,
  retryWorkflow,
  isWaitingManual,
  waitingTodoSteps,
  maskSecret,
  secretDisplayValue,
  toggleSecret,
  isSecretRevealed,
});
</script>
