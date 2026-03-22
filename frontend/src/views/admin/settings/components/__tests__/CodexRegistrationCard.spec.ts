import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CodexRegistrationCard from '../CodexRegistrationCard.vue'

const StatCardStub = {
  props: ['title', 'value'],
  template: '<div>{{ title }} {{ value }}</div>'
}


function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })

  return { promise, resolve, reject }
}

const codexApiMocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getLoopStatus: vi.fn(),
  getProxyStatus: vi.fn(),
  getLogs: vi.fn(),
  getAccounts: vi.fn(),
  saveProxyList: vi.fn(),
  selectProxy: vi.fn(),
  testProxy: vi.fn(),
  enable: vi.fn(),
  disable: vi.fn(),
  resume: vi.fn(),
  retry: vi.fn(),
  startLoop: vi.fn(),
  stopLoop: vi.fn()
}))

function makeStatus(overrides: Record<string, unknown> = {}) {
  return {
    enabled: false,
    sleep_min: 12,
    sleep_max: 34,
    total_created: 18,
    last_success: '2026-03-06 10:00:00',
    last_error: 'sample failure',
    proxy: true,
    job_phase: 'waiting_manual:db_connect_failed',
    workflow_id: 'wf-1',
    waiting_reason: 'db_connect_failed',
    can_start: false,
    can_resume: true,
    can_abandon: true,
    manual_gate: null,
    resume_context: null,
    resume_hint: null,
    last_transition: null,
    last_resume_gate_reason: null,
    recent_logs_tail: [],
    last_processed_summary: null,
    ...overrides
  }
}

function makeLoopStatus(overrides: Record<string, unknown> = {}) {
  return {
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
    loop_last_error: '',
    loop_history: [],
    loop_committed_accounts_jsonl_offset: 0,
    ...overrides
  }
}

function makeProxyStatus(overrides: Record<string, unknown> = {}) {
  return {
    proxy_enabled: true,
    proxy_current_id: 'proxy-1',
    proxy_current_name: 'Primary Proxy',
    proxy_last_used_id: 'proxy-2',
    proxy_last_used_name: 'Backup Proxy',
    proxy_last_checked_at: '2026-03-06T10:00:00Z',
    proxy_last_error: null,
    proxy_last_switch_reason: null,
    proxy_pool: [
      {
        id: 'proxy-1',
        name: 'Primary Proxy',
        proxy_url: 'http://proxy-1:8080',
        enabled: true,
        last_status: 'ok',
        last_checked_at: '2026-03-06T10:00:00Z',
        last_success_at: '2026-03-06T10:00:00Z',
        last_failure_at: null,
        cooldown_until: null,
        failure_count: 0
      },
      {
        id: 'proxy-2',
        name: 'Backup Proxy',
        proxy_url: 'http://proxy-2:8080',
        enabled: true,
        last_status: 'unknown',
        last_checked_at: null,
        last_success_at: null,
        last_failure_at: null,
        cooldown_until: null,
        failure_count: 0
      }
    ],
    ...overrides
  }
}

function makeSubscribeGateStatus(overrides: Record<string, unknown> = {}) {
  return makeStatus({
    job_phase: 'waiting_manual:subscribe_then_resume',
    waiting_reason: 'subscribe_then_resume',
    manual_gate: {
      action: 'subscribe_then_resume',
      token: 'tok-1234567890abcdef',
      continue_url: 'https://chatgpt.com/invite'
    },
    resume_context: {
      email: 'owner@example.com',
      access_token_raw: 'tok-1234567890abcdef'
    },
    ...overrides
  })
}

vi.mock('@/api/admin', () => ({
  adminAPI: {
    codex: codexApiMocks
  }
}))

vi.mock('vue-i18n', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-i18n')>()

  const messages: Record<string, string> = {
    'common.loading': '加载中...',
    'common.unknown': '未知',
    'common.refresh': '刷新',
    'common.all': '全部',
    'common.info': '提示',
    'common.warning': '警告',
    'common.error': '错误',
    'admin.codexRegister.badge.adminConsole': '后台控制台',
    'admin.codexRegister.badge.attention': '需关注',
    'admin.codexRegister.badge.healthy': '暂无错误',
    'admin.codexRegister.actions.start': '开始',
    'admin.codexRegister.actions.stop': '停止',
    'admin.codexRegister.actions.resume': '继续',
    'admin.codexRegister.actions.retry': '重试',
    'admin.codexRegister.actions.inProgress': '进行中',
    'admin.codexRegister.actions.refreshing': '刷新中…',
    'admin.codexRegister.actions.copy': '复制',
    'admin.codexRegister.actions.show': '显示',
    'admin.codexRegister.actions.hide': '隐藏',
    'admin.codexRegister.summary.totalCreated': '累计生成账号数',
    'admin.codexRegister.summary.lastSuccess': '最近成功时间',
    'admin.codexRegister.summary.proxy': '是否配置代理',
    'admin.codexRegister.summary.sleepRange': '休眠区间（秒）',
    'admin.codexRegister.summary.proxyConfigured': '已配置',
    'admin.codexRegister.summary.proxyMissing': '未配置',
    'admin.codexRegister.summary.batchEmpty': '本轮批量暂无统计数据',
    'admin.codexRegister.summary.batchProgress': '本轮已处理 5 条，成功 5 条，失败 0 条',
    'admin.codexRegister.summary.empty': '暂无',
    'admin.codexRegister.phase.unknown': '未知阶段',
    'admin.codexRegister.phase.idle': '未运行',
    'admin.codexRegister.phase.runningCreateParent': '正在创建母号',
    'admin.codexRegister.phase.runningGetTokens': '创建母号中',
    'admin.codexRegister.phase.waitingSubscribeThenResume': '母号开通订阅中',
    'admin.codexRegister.phase.runningGptTeamBatch': '子号批量注册/邀请中',
    'admin.codexRegister.phase.waitingManual': '等待你手动操作',
    'admin.codexRegister.phase.runningPreResumeCheck': '继续前校验中',
    'admin.codexRegister.phase.runningInviteChildren': '正在邀请子号',
    'admin.codexRegister.phase.runningAcceptAndSwitch': '子号接受并切组中',
    'admin.codexRegister.phase.runningVerifyAndBind': '正在校验并绑定',
    'admin.codexRegister.phase.abandoned': '已终止',
    'admin.codexRegister.phase.failed': '执行失败',
    'admin.codexRegister.waitingReason.parentUpgrade': '需要先完成母号升级',
    'admin.codexRegister.waitingReason.subscribeThenResume': '等待你在官网完成订阅后再点击继续',
    'admin.codexRegister.waitingTodo.title': '待办清单',
    'admin.codexRegister.waitingTodo.afterTip': '完成以上操作后，点击“继续”以恢复自动流程。',
    'admin.codexRegister.waitingTodo.parentUpgrade.step1': '登录母号并完成升级流程。',
    'admin.codexRegister.waitingTodo.parentUpgrade.step2': '确认升级成功且账户状态正常。',
    'admin.codexRegister.waitingTodo.parentUpgrade.step3': '返回本页后点击“继续”。',
    'admin.codexRegister.waitingTodo.subscribeThenResume.step1': '使用上方提示的母号在官网开通订阅。',
    'admin.codexRegister.waitingTodo.subscribeThenResume.step2': '确认订阅状态已生效。',
    'admin.codexRegister.waitingTodo.subscribeThenResume.step3': '返回本页后点击“继续”恢复自动流程。',
    'admin.codexRegister.waitingTodo.generic.step1': '根据等待原因完成对应手动操作。',
    'admin.codexRegister.waitingTodo.generic.step2': '确认操作已在目标平台生效。',
    'admin.codexRegister.waitingTodo.generic.step3': '返回本页后点击“继续”。',
    'admin.codexRegister.panels.polling': '自动轮询：10 秒',
    'admin.codexRegister.panels.waitingReasonEmpty': '当前无需等待',
    'admin.codexRegister.panels.lastSuccessEmpty': '暂无成功记录',
    'admin.codexRegister.panels.proxyConfiguredDetail': '已配置代理，容器可按当前出口执行注册',
    'admin.codexRegister.panels.proxyMissingDetail': '未配置代理，请确认网络出口要求',
    'admin.codexRegister.panels.eventsTitle': '最近事件',
    'admin.codexRegister.panels.eventsDescription': 'events description',
    'admin.codexRegister.panels.workflowFailed': '工作流失败',
    'admin.codexRegister.panels.emptyEvents': '暂无事件',
    'admin.codexRegister.accounts.title': '已创建账户',
    'admin.codexRegister.accounts.description': '仅展示 codex-register 自动创建记录',
    'admin.codexRegister.accounts.empty': '暂无账号记录',
    'admin.codexRegister.accounts.searchPlaceholder': '按邮箱搜索',
    'admin.codexRegister.accounts.columns.email': '邮箱',
    'admin.codexRegister.accounts.columns.role': '角色',
    'admin.codexRegister.accounts.columns.accessToken': 'Access Token',
    'admin.codexRegister.accounts.columns.refreshToken': 'Refresh Token',
    'admin.codexRegister.accounts.columns.accountId': 'Account ID',
    'admin.codexRegister.accounts.columns.createdAt': '创建时间',
    'admin.codexRegister.subscribeGate.title': '手动订阅关卡',
    'admin.codexRegister.subscribeGate.email': '目标邮箱',
    'admin.codexRegister.subscribeGate.missingResumeContextHint': '缺少 resume_context.email 或 resume_context.access_token_raw。',
    'admin.codexRegister.debug.snapshotTitle': 'Debug Snapshot',
    'admin.codexRegister.debug.phaseLabel': 'Current Phase',
    'admin.codexRegister.debug.waitingLabel': 'Waiting Reason',
    'admin.codexRegister.debug.gateLabel': 'Resume Gate',
    'admin.codexRegister.debug.gateClear': 'No gate block',
    'admin.codexRegister.debug.transitionLabel': 'Last Transition',
    'admin.codexRegister.debug.transitionReason': 'Reason',
    'admin.codexRegister.debug.transitionTime': 'Time',
    'admin.codexRegister.debug.transitionEmpty': 'No transition data',
    'admin.codexRegister.debug.showRaw': 'Show raw fields',
    'admin.codexRegister.debug.hideRaw': 'Hide raw fields',
    'admin.codexRegister.debug.rawPhase': 'Raw phase',
    'admin.codexRegister.debug.rawWaiting': 'Raw waiting reason',
    'admin.codexRegister.debug.rawGate': 'Raw resume gate reason',
    'admin.codexRegister.debug.logLevel': 'Level',
    'admin.codexRegister.debug.logLimit': 'Limit',
    'admin.codexRegister.debug.resumeOnly': 'Resume only',
    'admin.codexRegister.debug.resumeIgnored': 'Resume ignored',
    'admin.codexRegister.debug.resumeGateBlocked': 'Resume gate blocked: {reason}',
    'admin.codexRegister.debug.resumeStarted': 'Resume started',
    'admin.codexRegister.debug.resumeUnknown': 'Resume unknown',
    'admin.codexRegister.loop.title': '循环执行控制',
    'admin.codexRegister.loop.actions.start': '启动循环',
    'admin.codexRegister.loop.actions.starting': '启动中…',
    'admin.codexRegister.loop.actions.stop': '停止循环',
    'admin.codexRegister.loop.actions.stopping': '停止中…',
    'admin.codexRegister.loop.status.idle': '未运行',
    'admin.codexRegister.loop.status.running': '循环运行中',
    'admin.codexRegister.loop.status.stopping': '停止中',
    'admin.codexRegister.loop.summary.idle': '可按需启动独立循环执行。',
    'admin.codexRegister.loop.summary.idleWithHistory': '最近保留 1 轮执行记录。',
    'admin.codexRegister.loop.summary.running': '当前正在执行第 3 轮循环。',
    'admin.codexRegister.loop.summary.stopping': '正在请求停止当前循环，请稍候。',
    'admin.codexRegister.loop.fields.status': '循环状态',
    'admin.codexRegister.loop.fields.currentRound': '当前轮次',
    'admin.codexRegister.loop.fields.totalCreated': '循环累计创建',
    'admin.codexRegister.loop.fields.committedOffset': '已提交偏移量',
    'admin.codexRegister.loop.fields.startedAt': '启动时间',
    'admin.codexRegister.loop.fields.lastFinishedAt': '最近完成时间',
    'admin.codexRegister.loop.fields.lastRoundSummary': '最近一轮结果',
    'admin.codexRegister.loop.fields.lastError': '最近循环错误',
    'admin.codexRegister.loop.lastRoundSummary': '创建 2 / 更新 1 / 跳过 0 / 失败 0',
    'admin.codexRegister.loop.noError': '暂无循环错误',
    'admin.codexRegister.loop.history.title': '最近循环历史',
    'admin.codexRegister.loop.history.empty': '暂无循环历史',
    'admin.codexRegister.loop.history.status.running': '运行中',
    'admin.codexRegister.loop.history.status.success': '成功',
    'admin.codexRegister.loop.history.status.failed': '失败',
    'admin.codexRegister.proxyPool.emptyHint': 'No proxies yet. Add a proxy URL to enable routing.',
    'admin.codexRegister.proxyPool.addAction': 'Add Proxy',
    'admin.codexRegister.proxyPool.deleteAction': 'Delete Proxy',
    'admin.codexRegister.proxyPool.title': 'Proxy Pool',
    'admin.codexRegister.proxyPool.available': 'Available Proxies: {count}',
    'admin.codexRegister.proxyPool.lastError': 'Last Proxy Error: {error}',
    'admin.codexRegister.proxyPool.enableRouting': 'Enable Proxy Routing',
    'admin.codexRegister.proxyPool.statusLabel': 'Status: {status}',
    'admin.codexRegister.proxyPool.cooldownLabel': 'Cooldown: {value}',
    'admin.codexRegister.proxyPool.failedLabel': 'Failed: {count}',
    'admin.codexRegister.proxyPool.testAction': 'Test Proxy',
    'admin.codexRegister.proxyPool.selectAction': 'Select Proxy',
    'admin.codexRegister.proxyPool.saveAction': 'Save Proxy Pool',
    'admin.codexRegister.proxyPool.statusValue.ok': 'Healthy',
    'admin.codexRegister.proxyPool.statusValue.failed': 'Failed',
    'admin.codexRegister.proxyPool.statusValue.cooldown': 'Cooldown',
    'admin.codexRegister.proxyPool.statusValue.unknown': 'Unknown',
  }

  return {
    ...actual,
    useI18n: () => ({
      t: (key: string, params?: Record<string, unknown>) => {
        if (key === 'admin.codexRegister.panels.polling' && params) {
          return `自动轮询：${params.seconds} 秒`
        }
        if (key === 'admin.codexRegister.panels.eventCount' && params) {
          return `${params.count} 条记录`
        }
        if (key === 'admin.codexRegister.summary.rangeValue' && params) {
          return `${params.min} - ${params.max}`
        }
        if (key === 'admin.codexRegister.summary.rangeValueWithUnit' && params) {
          return `${params.min} - ${params.max} 秒`
        }
        if (key === 'admin.codexRegister.loop.summary.running' && params) {
          return `当前正在执行第 ${params.round} 轮循环。`
        }
        if (key === 'admin.codexRegister.loop.summary.idleWithHistory' && params) {
          return `最近保留 ${params.count} 轮执行记录。`
        }
        if (key === 'admin.codexRegister.loop.lastRoundSummary' && params) {
          return `创建 ${params.created} / 更新 ${params.updated} / 跳过 ${params.skipped} / 失败 ${params.failed}`
        }
        if (key === 'admin.codexRegister.loop.proxySummary' && params) {
          return `本轮代理：${params.currentProxy} · 上一轮代理：${params.previousProxy}`
        }
        if (key === 'admin.codexRegister.loop.history.count' && params) {
          return `${params.count} 条记录`
        }
        if (key === 'admin.codexRegister.loop.history.round' && params) {
          return `第 ${params.round} 轮`
        }
        if (key === 'admin.codexRegister.loop.history.summary' && params) {
          return `创建 ${params.created} / 更新 ${params.updated} / 跳过 ${params.skipped} / 失败 ${params.failed}`
        }
        if (key === 'admin.codexRegister.loop.history.timeRange' && params) {
          return `开始：${params.startedAt} · 结束：${params.finishedAt}`
        }

        if (key === 'admin.codexRegister.proxyPool.available' && params) {
          return `Available Proxies: ${params.count}`
        }
        if (key === 'admin.codexRegister.proxyPool.lastError' && params) {
          return `Last Proxy Error: ${params.error}`
        }
        if (key === 'admin.codexRegister.proxyPool.statusLabel' && params) {
          return `Status: ${params.status}`
        }
        if (key === 'admin.codexRegister.proxyPool.cooldownLabel' && params) {
          return `Cooldown: ${params.value}`
        }
        if (key === 'admin.codexRegister.proxyPool.failedLabel' && params) {
          return `Failed: ${params.count}`
        }
        return messages[key] ?? key
      }
    })
  }
})

describe('CodexRegistrationCard', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()

    codexApiMocks.getStatus.mockResolvedValue(makeStatus())
    codexApiMocks.getLoopStatus.mockResolvedValue(makeLoopStatus())
    codexApiMocks.getProxyStatus.mockResolvedValue(makeProxyStatus())
    codexApiMocks.getProxyStatus.mockClear()
    codexApiMocks.getLogs.mockResolvedValue([
      {
        level: 'info',
        time: '2026-03-06 10:00:01',
        message: 'run completed'
      }
    ])
    codexApiMocks.getAccounts.mockResolvedValue([
      {
        id: 1,
        email: 'a@example.com',
        access_token: 'at-1234567890-secret',
        refresh_token: 'rt-1234567890-secret',
        account_id: 'acct-1',
        source: 'codex-register',
        created_at: '2026-03-06T10:00:01Z',
        updated_at: '2026-03-06T10:00:01Z'
      }
    ])
    codexApiMocks.startLoop.mockResolvedValue(makeLoopStatus({ loop_running: true, loop_current_round: 1 }))
    codexApiMocks.stopLoop.mockResolvedValue(makeLoopStatus({ loop_running: false, loop_stopping: false }))
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('uses job_phase to render primary status and action', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('等待你手动操作')
    expect(text).toContain('继续')
    expect(text).not.toContain('手动执行一次')
  })

  it('renders top controlbar with status, primary action and secondary actions', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const controlbar = wrapper.find('[data-testid="codex-controlbar"]')
    expect(controlbar.exists()).toBe(true)
    expect(controlbar.find('[data-testid="codex-controlbar-status"]').exists()).toBe(true)
    expect(controlbar.find('[data-testid="codex-controlbar-primary"]').text()).toContain('继续')

    const secondaryText = controlbar.find('[data-testid="codex-controlbar-secondary"]').text()
    expect(secondaryText).toContain('刷新')
    expect(secondaryText).toContain('停止')
  })

  it('keeps exactly one primary CTA in controlbar center area', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const center = wrapper.find('[data-testid="codex-controlbar-primary"]')
    const primaryButtons = center.findAll('button.btn-primary')

    expect(primaryButtons).toHaveLength(1)
    expect(primaryButtons[0].text()).toBe('继续')
  })

  it('shows waiting_manual todo checklist for parent_upgrade', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(makeStatus({
      last_success: null,
      last_error: null,
      job_phase: 'waiting_manual:parent_upgrade',
      waiting_reason: 'parent_upgrade'
    }))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('待办清单')
    expect(text).toContain('需要先完成母号升级')
    expect(text).toContain('登录母号并完成升级流程。')
    expect(text).toContain('完成以上操作后，点击“继续”以恢复自动流程。')
  })

  it('masks access_token/refresh_token by default', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('at-123...cret')
    expect(text).toContain('rt-123...cret')
    expect(text).not.toContain('at-1234567890-secret')
    expect(text).not.toContain('rt-1234567890-secret')
  })

  it('reveals only clicked token cell when show is pressed', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const accountRows = wrapper.findAll('tbody tr')
    expect(accountRows.length).toBeGreaterThan(0)
    const showButtons = accountRows[0].findAll('button').filter((btn) => btn.text() === '显示')
    expect(showButtons.length).toBeGreaterThanOrEqual(1)

    await showButtons[0].trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('at-1234567890-secret')
    expect(text).toContain('rt-123...cret')
  })

  it('shows disabled in-progress primary button without layout duplication', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(makeStatus({
      enabled: true,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      job_phase: 'running:create_parent',
      workflow_id: 'wf-2',
      waiting_reason: null,
      can_resume: false
    }))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const center = wrapper.find('[data-testid="codex-controlbar-primary"]')
    const buttons = center.findAll('button')

    expect(buttons).toHaveLength(1)
    expect(buttons[0].text()).toContain('进行中')
    expect((buttons[0].element as HTMLButtonElement).disabled).toBe(true)
  })

  it('calls resume endpoint when primary action is resume', async () => {
    codexApiMocks.resume.mockResolvedValueOnce(makeStatus({
      enabled: true,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      job_phase: 'running:create_parent',
      workflow_id: 'wf-2',
      waiting_reason: null,
      can_resume: false
    }))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const resumeButton = wrapper.find('[data-testid="codex-controlbar-primary"] button')
    expect(resumeButton.exists()).toBe(true)
    expect(resumeButton.text()).toBe('继续')

    await resumeButton.trigger('click')
    await flushPromises()

    expect(codexApiMocks.resume).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLoopStatus).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('正在创建母号')
  })

  it('keeps secondary action as stop in cancelled waiting state', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(makeStatus({
      enabled: false,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'waiting_manual:cancelled',
      workflow_id: 'wf-2',
      waiting_reason: 'cancelled',
      can_start: false,
      can_resume: true,
      can_abandon: true
    }))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const controlbar = wrapper.find('[data-testid="codex-controlbar-secondary"]')
    expect(controlbar.text()).toContain('停止')
    expect(controlbar.text()).not.toContain('重试')
  })

  it('calls disable endpoint when secondary stop button is clicked in cancelled waiting state', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(makeStatus({
      enabled: false,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'waiting_manual:cancelled',
      workflow_id: 'wf-2',
      waiting_reason: 'cancelled',
      can_start: false,
      can_resume: true,
      can_abandon: true
    }))

    codexApiMocks.disable.mockResolvedValueOnce(makeStatus({
      enabled: false,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'abandoned',
      workflow_id: 'wf-3',
      waiting_reason: null,
      can_start: true,
      can_resume: false,
      can_abandon: false
    }))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const stopButton = wrapper.find('[data-testid="codex-controlbar-secondary"] button:last-of-type')
    expect(stopButton.exists()).toBe(true)
    expect(stopButton.text()).toBe('停止')

    await stopButton.trigger('click')
    await flushPromises()

    expect(codexApiMocks.disable).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.retry).not.toHaveBeenCalled()
  })

  it('keeps resume as primary action in cancelled waiting state', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(makeStatus({
      enabled: false,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'waiting_manual:cancelled',
      workflow_id: 'wf-2',
      waiting_reason: 'cancelled',
      can_start: false,
      can_resume: true,
      can_abandon: true
    }))

    codexApiMocks.resume.mockResolvedValueOnce(makeStatus({
      enabled: true,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'running:create_parent',
      workflow_id: 'wf-3',
      waiting_reason: null,
      can_start: false,
      can_resume: false,
      can_abandon: true
    }))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const primaryButton = wrapper.find('[data-testid="codex-controlbar-primary"] button')
    expect(primaryButton.text()).toBe('继续')

    await primaryButton.trigger('click')
    await flushPromises()

    expect(codexApiMocks.resume).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.retry).not.toHaveBeenCalled()
  })

  it('renders workflow failure heading via i18n', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(makeStatus({
      job_phase: 'failed',
      last_error: 'terminal failure'
    }))

    codexApiMocks.getLogs.mockResolvedValueOnce([
      {
        level: 'error',
        time: '2026-03-06 10:00:09',
        message: 'workflow_failed: terminal failure'
      }
    ])

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const failurePanel = wrapper.find('[data-testid="codex-workflow-failure-detail"]')
    expect(failurePanel.exists()).toBe(true)
    expect(failurePanel.text()).toContain('工作流失败')
  })

  it('renders debug snapshot before events section', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const order = wrapper
      .findAll('[data-section-order]')
      .map((node) => node.attributes('data-section-order'))

    expect(order).toEqual(['debug', 'events'])
  })

  it('renders phase/waiting/gate/transition cards with transition reason and time', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(
      makeStatus({
        last_transition: {
          time: '2026-03-06 11:00:00',
          from: 'waiting_manual:parent_upgrade',
          to: 'running:pre_resume_check',
          reason: 'resume'
        },
        last_resume_gate_reason: 'parent_upgrade'
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const snapshot = wrapper.find('[data-testid="codex-debug-snapshot"]')
    const text = snapshot.text()
    expect(text).toContain('Last Transition')
    expect(text).toContain('waiting_manual:parent_upgrade → running:pre_resume_check')
    expect(text).toContain('Reason')
    expect(text).toContain('resume')
    expect(text).toContain('Time')
    expect(text).toContain('2026-03-06 11:00:00')
    expect(text).toContain('Resume Gate')
    expect(text).toContain('parent_upgrade')
  })

  it('hides raw fields by default and shows raw job_phase/waiting_reason/last_resume_gate_reason when toggled', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(
      makeStatus({
        waiting_reason: 'parent_upgrade',
        last_resume_gate_reason: 'parent_upgrade'
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(wrapper.find('[data-testid="codex-debug-raw-values"]').exists()).toBe(false)

    await wrapper.find('[data-testid="codex-debug-raw-toggle"]').trigger('click')
    await flushPromises()

    const raw = wrapper.find('[data-testid="codex-debug-raw-values"]').text()
    expect(raw).toContain('waiting_manual:db_connect_failed')
    expect(raw).toContain('parent_upgrade')
  })

  it('renders localized log level options and log limit options, and requests logs with selected level/limit', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const levelSelect = wrapper.find('[data-testid="codex-log-level"]')
    const levelOptions = levelSelect.findAll('option').map((option) => option.text())
    expect(levelOptions).toEqual(['全部', '提示', '警告', '错误'])

    const limitSelect = wrapper.find('[data-testid="codex-log-limit"]')
    const options = limitSelect.findAll('option').map((option) => option.text())
    expect(options).toEqual(['50', '100', '200'])

    await levelSelect.setValue('warn')
    await limitSelect.setValue('100')
    await flushPromises()

    const lastCall = codexApiMocks.getLogs.mock.calls.at(-1)
    expect(lastCall?.[0]).toEqual({ level: 'warn', limit: 100 })
  })

  it('applies resume-only local filter without changing server query', async () => {
    codexApiMocks.getLogs.mockResolvedValueOnce([
      { level: 'info', time: '2026-03-06 10:00:01', message: 'resume_request_ignored:not_waiting' },
      { level: 'info', time: '2026-03-06 10:00:02', message: 'other event' }
    ])

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    await wrapper.find('[data-testid="codex-log-resume-only"]').setValue(true)
    await flushPromises()

    const logs = wrapper.findAll('[data-testid="codex-log-row"]')
    expect(logs).toHaveLength(1)
    expect(logs[0].text()).toContain('resume_request_ignored:not_waiting')

    const lastCall = codexApiMocks.getLogs.mock.calls.at(-1)
    expect(lastCall?.[0]).toEqual({ level: undefined, limit: 200 })
  })

  it('shows resume ignored diagnostic when not waiting', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(
      makeStatus({
        job_phase: 'running:create_parent',
        waiting_reason: null,
        last_resume_gate_reason: null,
        recent_logs_tail: [
          { level: 'warn', time: '2026-03-06 10:00:09', message: 'resume_request_ignored:not_waiting:phase=running:create_parent' }
        ]
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const snapshot = wrapper.find('[data-testid="codex-debug-snapshot"]')
    expect(snapshot.text()).toContain('Resume ignored')
  })

  it('shows resume gate blocked diagnostic when gate reason exists', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(
      makeStatus({
        job_phase: 'waiting_manual:parent_upgrade',
        waiting_reason: 'parent_upgrade',
        last_resume_gate_reason: 'parent_upgrade'
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const snapshot = wrapper.find('[data-testid="codex-debug-snapshot"]')
    expect(snapshot.text()).toContain('Resume gate blocked')
    expect(snapshot.text()).toContain('parent_upgrade')
  })

  it('shows resume started diagnostic when phase moves to running:pre_resume_check', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(
      makeStatus({
        job_phase: 'running:pre_resume_check',
        waiting_reason: null,
        last_resume_gate_reason: null
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const snapshot = wrapper.find('[data-testid="codex-debug-snapshot"]')
    expect(snapshot.text()).toContain('Resume started')
  })

  it('keeps status snapshot visible when logs request fails', async () => {
    codexApiMocks.getLogs.mockRejectedValueOnce(new Error('log failure'))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(wrapper.find('[data-testid="codex-debug-snapshot"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('log failure')
  })

  it('keeps log error visible even after later status success', async () => {
    let resolveStatus: (value: ReturnType<typeof makeStatus>) => void
    const statusPromise = new Promise<ReturnType<typeof makeStatus>>((resolve) => {
      resolveStatus = resolve
    })

    codexApiMocks.getStatus.mockReturnValueOnce(statusPromise)
    codexApiMocks.getLogs.mockRejectedValueOnce(new Error('log failure'))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(wrapper.text()).toContain('log failure')

    resolveStatus!(makeStatus({ job_phase: 'running:create_parent', waiting_reason: null }))
    await flushPromises()

    expect(wrapper.text()).toContain('log failure')
  })

  it('keeps existing logs visible when status request fails', async () => {
    codexApiMocks.getLogs.mockResolvedValueOnce([
      { level: 'info', time: '2026-03-06 10:00:01', message: 'resume_started_after_gate' }
    ])
    codexApiMocks.getStatus.mockRejectedValueOnce(new Error('status failure'))

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(wrapper.findAll('[data-testid="codex-log-row"]').length).toBe(1)
    expect(wrapper.text()).toContain('status failure')
  })

  it('renders loop last finished time from loop status', async () => {
    codexApiMocks.getLoopStatus.mockResolvedValueOnce(
      makeLoopStatus({
        loop_last_round_finished_at: '2026-03-06 12:34:56'
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const loopPanel = wrapper.find('[data-testid="codex-loop-panel"]')
    expect(loopPanel.text()).toContain('最近完成时间')
    expect(loopPanel.text()).toContain('2026-03-06 12:34:56')
  })

  it('polls only when active and stops when deactivated', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval')
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: false },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(codexApiMocks.getStatus).not.toHaveBeenCalled()
    expect(codexApiMocks.getLoopStatus).not.toHaveBeenCalled()
    expect(codexApiMocks.getLogs).not.toHaveBeenCalled()
    expect(setIntervalSpy).not.toHaveBeenCalled()

    await wrapper.setProps({ active: true })
    await flushPromises()

    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLoopStatus).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getAccounts).toHaveBeenCalledTimes(1)
    expect(setIntervalSpy).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(10000)
    await flushPromises()

    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLoopStatus).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getAccounts).toHaveBeenCalledTimes(2)

    await wrapper.setProps({ active: false })
    await flushPromises()

    expect(clearIntervalSpy).toHaveBeenCalled()

    vi.advanceTimersByTime(10000)
    await flushPromises()

    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLoopStatus).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getAccounts).toHaveBeenCalledTimes(2)

    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
  })

  it('disables workflow action buttons while refresh polling is in flight', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const statusDeferred = createDeferred<ReturnType<typeof makeStatus>>()
    const loopDeferred = createDeferred<ReturnType<typeof makeLoopStatus>>()
    const logsDeferred = createDeferred<unknown[]>()
    const accountsDeferred = createDeferred<unknown[]>()

    codexApiMocks.getStatus.mockReturnValueOnce(statusDeferred.promise)
    codexApiMocks.getLoopStatus.mockReturnValueOnce(loopDeferred.promise)
    codexApiMocks.getLogs.mockReturnValueOnce(logsDeferred.promise)
    codexApiMocks.getAccounts.mockReturnValueOnce(accountsDeferred.promise)

    vi.advanceTimersByTime(10000)
    await wrapper.vm.$nextTick()

    const primaryButton = wrapper.find('[data-testid="codex-controlbar-primary"] button')
    const secondaryButtons = wrapper.findAll('[data-testid="codex-controlbar-secondary"] button')

    expect(primaryButton.text()).toBe('继续')
    expect((primaryButton.element as HTMLButtonElement).disabled).toBe(true)
    expect(secondaryButtons).toHaveLength(2)
    expect(secondaryButtons[0].text()).toBe('刷新中…')
    expect((secondaryButtons[0].element as HTMLButtonElement).disabled).toBe(true)
    expect(secondaryButtons[1].text()).toBe('停止')
    expect((secondaryButtons[1].element as HTMLButtonElement).disabled).toBe(true)

    statusDeferred.resolve(makeStatus())
    loopDeferred.resolve(makeLoopStatus())
    logsDeferred.resolve([])
    accountsDeferred.resolve([])
    await flushPromises()
  })

  it('sorts accounts by created_at descending and keeps invalid/null timestamps last', async () => {
    codexApiMocks.getAccounts.mockResolvedValueOnce([
      {
        id: 1,
        email: 'oldest@example.com',
        access_token: 'at-old',
        refresh_token: 'rt-old',
        account_id: 'acct-old',
        source: 'codex-register',
        created_at: '2026-03-05T10:00:01Z',
        updated_at: '2026-03-05T10:00:01Z'
      },
      {
        id: 2,
        email: 'invalid@example.com',
        access_token: 'at-invalid',
        refresh_token: 'rt-invalid',
        account_id: 'acct-invalid',
        source: 'codex-register',
        created_at: 'not-a-date',
        updated_at: '2026-03-06T10:00:01Z'
      },
      {
        id: 3,
        email: 'newest@example.com',
        access_token: 'at-new',
        refresh_token: 'rt-new',
        account_id: 'acct-new',
        source: 'codex-register',
        created_at: '2026-03-07T10:00:01Z',
        updated_at: '2026-03-07T10:00:01Z'
      },
      {
        id: 4,
        email: 'null@example.com',
        access_token: 'at-null',
        refresh_token: 'rt-null',
        account_id: 'acct-null',
        source: 'codex-register',
        created_at: null,
        updated_at: '2026-03-06T10:00:01Z'
      },
      {
        id: 5,
        email: 'middle@example.com',
        access_token: 'at-middle',
        refresh_token: 'rt-middle',
        account_id: 'acct-middle',
        source: 'codex-register',
        created_at: '2026-03-06T10:00:01Z',
        updated_at: '2026-03-06T10:00:01Z'
      }
    ])

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    const renderedEmails = rows.map((row) => row.find('td').text())

    expect(renderedEmails).toEqual([
      'newest@example.com',
      'middle@example.com',
      'oldest@example.com',
      'invalid@example.com',
      'null@example.com'
    ])
  })

  it('prefers plan_type over codex_register_role and source for account badges', async () => {
    codexApiMocks.getAccounts.mockResolvedValueOnce([
      {
        id: 1,
        email: 'plan-type-first@example.com',
        access_token: 'at-plan-type-first',
        refresh_token: 'rt-plan-type-first',
        account_id: 'acct-plan-type-first',
        source: 'parent',
        codex_register_role: 'parent',
        plan_type: 'child',
        created_at: '2026-03-08T10:00:01Z',
        updated_at: '2026-03-08T10:00:01Z'
      },
      {
        id: 2,
        email: 'role-second@example.com',
        access_token: 'at-role-second',
        refresh_token: 'rt-role-second',
        account_id: 'acct-role-second',
        source: 'child',
        codex_register_role: 'parent',
        created_at: '2026-03-07T10:00:01Z',
        updated_at: '2026-03-07T10:00:01Z'
      },
      {
        id: 3,
        email: 'source-third@example.com',
        access_token: 'at-source-third',
        refresh_token: 'rt-source-third',
        account_id: 'acct-source-third',
        source: 'parent',
        created_at: '2026-03-06T10:00:01Z',
        updated_at: '2026-03-06T10:00:01Z'
      }
    ])

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(3)

    const firstBadge = rows[0].findAll('td')[1].find('span')
    expect(firstBadge.text()).toBe('child')
    expect(firstBadge.classes()).toContain('bg-blue-100')

    const secondBadge = rows[1].findAll('td')[1].find('span')
    expect(secondBadge.text()).toBe('parent')
    expect(secondBadge.classes()).toContain('bg-purple-100')

    const thirdBadge = rows[2].findAll('td')[1].find('span')
    expect(thirdBadge.text()).toBe('parent')
    expect(thirdBadge.classes()).toContain('bg-purple-100')
  })

  it('copies account secrets with copy action', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const firstRow = wrapper.find('tbody tr')
    expect(firstRow.exists()).toBe(true)
    const copyButtons = firstRow.findAll('button').filter((btn) => btn.text() === '复制')
    expect(copyButtons.length).toBeGreaterThan(0)

    await copyButtons[0].trigger('click')
    expect(writeText).toHaveBeenCalled()
  })

  it('current status panel is removed and should not render', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(wrapper.text()).not.toContain('当前状态')
    expect(wrapper.find('[data-section-order="status"]').exists()).toBe(false)
  })

  it('subscribe gate renders for waiting_manual:subscribe_then_resume', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(makeSubscribeGateStatus())

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const gate = wrapper.find('[data-testid="codex-subscribe-gate"]')
    expect(gate.exists()).toBe(true)
    expect(gate.text()).toContain('owner@example.com')
    expect(gate.text()).toContain('tok-123...cdef')
    expect(gate.text()).not.toContain('tok-1234567890abcdef')

    const controls = gate.find('[data-testid="codex-subscribe-gate-controls"]')
    expect(controls.text()).toContain('显示')
    expect(controls.text()).toContain('复制')
    expect(controls.text()).toContain('继续')
  })

  it('manual_gate is absent and still renders subscribe gate via waiting phase fallback', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(
      makeSubscribeGateStatus({
        manual_gate: null
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const gate = wrapper.find('[data-testid="codex-subscribe-gate"]')
    expect(gate.exists()).toBe(true)
    expect(gate.text()).toContain('owner@example.com')
  })

  it('copy fails and keeps non-blocking UX with unchanged phase/action', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(makeSubscribeGateStatus())
    const writeText = vi.fn().mockRejectedValue(new Error('copy denied'))
    Object.assign(navigator, { clipboard: { writeText } })

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const copyButton = wrapper.find('[data-testid="codex-subscribe-gate-copy"]')
    await copyButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="codex-subscribe-gate-copy-hint"]').text()).toContain('copy denied')
    expect(wrapper.text()).toContain('等待你在官网完成订阅后再点击继续')
    expect(wrapper.find('[data-testid="codex-controlbar-primary"]').text()).toContain('继续')
  })

  it('missing resume_context still shows gate shell but hides token controls', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce(
      makeSubscribeGateStatus({
        resume_context: null
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const gate = wrapper.find('[data-testid="codex-subscribe-gate"]')
    expect(gate.exists()).toBe(true)
    expect(gate.find('[data-testid="codex-subscribe-gate-token"]').exists()).toBe(false)
    expect(gate.find('[data-testid="codex-subscribe-gate-controls"]').exists()).toBe(false)
    expect(gate.find('[data-testid="codex-subscribe-gate-diagnostic"]').text()).toContain('resume_context.email')
  })

  it('prefers plan_type over codex_register_role in account badge', async () => {
    codexApiMocks.getAccounts.mockResolvedValueOnce([
      {
        id: 1,
        email: 'team@example.com',
        access_token: 'at-team-secret',
        refresh_token: 'rt-team-secret',
        account_id: 'acct-team',
        source: 'codex-register',
        codex_register_role: 'child',
        plan_type: 'team',
        created_at: '2026-03-07T10:00:01Z',
        updated_at: '2026-03-07T10:00:01Z'
      },
      {
        id: 2,
        email: 'free@example.com',
        access_token: 'at-free-secret',
        refresh_token: 'rt-free-secret',
        account_id: 'acct-free',
        source: 'codex-register',
        codex_register_role: 'parent',
        plan_type: 'free',
        created_at: '2026-03-06T10:00:01Z',
        updated_at: '2026-03-06T10:00:01Z'
      },
      {
        id: 3,
        email: 'legacy@example.com',
        access_token: 'at-legacy-secret',
        refresh_token: 'rt-legacy-secret',
        account_id: 'acct-legacy',
        source: 'legacy-source',
        codex_register_role: 'parent',
        created_at: '2026-03-05T10:00:01Z',
        updated_at: '2026-03-05T10:00:01Z'
      }
    ])

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(3)
    expect(rows[0].text()).toContain('team@example.com')
    expect(rows[0].text()).toContain('team')
    expect(rows[0].text()).not.toContain('child')
    expect(rows[1].text()).toContain('free@example.com')
    expect(rows[1].text()).toContain('free')
    expect(rows[1].text()).not.toContain('parent')
    expect(rows[2].text()).toContain('legacy@example.com')
    expect(rows[2].text()).toContain('parent')
  })

  it('filters account rows by email keyword and keeps scroll container', async () => {
    codexApiMocks.getAccounts.mockResolvedValueOnce([
      {
        id: 1,
        email: 'alice@example.com',
        access_token: 'at-alice-secret',
        refresh_token: 'rt-alice-secret',
        account_id: 'acct-alice',
        source: 'codex-register',
        created_at: '2026-03-07T10:00:01Z',
        updated_at: '2026-03-07T10:00:01Z'
      },
      {
        id: 2,
        email: 'bob@example.com',
        access_token: 'at-bob-secret',
        refresh_token: 'rt-bob-secret',
        account_id: 'acct-bob',
        source: 'codex-register',
        created_at: '2026-03-06T10:00:01Z',
        updated_at: '2026-03-06T10:00:01Z'
      },
      {
        id: 3,
        email: 'carol@example.com',
        access_token: 'at-carol-secret',
        refresh_token: 'rt-carol-secret',
        account_id: 'acct-carol',
        source: 'codex-register',
        created_at: '2026-03-05T10:00:01Z',
        updated_at: '2026-03-05T10:00:01Z'
      }
    ])

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const search = wrapper.find('[data-testid="codex-accounts-search"]')
    await search.setValue('bob')
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('bob@example.com')

    const scrollContainer = wrapper.find('[data-testid="codex-accounts-scroll"]')
    expect(scrollContainer.exists()).toBe(true)
    expect(scrollContainer.classes()).toContain('overflow-auto')
  })

  it('renders loop status summary fields', async () => {
    codexApiMocks.getLoopStatus.mockResolvedValueOnce(
      makeLoopStatus({
        loop_running: true,
        loop_current_round: 3,
        loop_total_created: 7,
        loop_started_at: '2026-03-06T11:00:00Z',
        loop_last_round_finished_at: '2026-03-06T11:05:00Z',
        loop_last_round_created: 2,
        loop_last_round_updated: 1,
        loop_last_round_skipped: 0,
        loop_last_round_failed: 0,
        loop_committed_accounts_jsonl_offset: 24
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const panel = wrapper.find('[data-testid="codex-loop-panel"]')
    expect(panel.text()).toContain('循环执行控制')
    expect(panel.text()).toContain('循环运行中')
    expect(panel.text()).toContain('当前轮次')
    expect(panel.text()).toContain('3')
    expect(panel.text()).toContain('循环累计创建')
    expect(panel.text()).toContain('7')
    expect(panel.text()).toContain('已提交偏移量')
    expect(panel.text()).toContain('24')
    expect(panel.text()).toContain('最近完成时间')
    expect(panel.text()).toContain('2026-03-06T11:05:00Z')
    expect(panel.text()).toContain('创建 2 / 更新 1 / 跳过 0 / 失败 0')
  })

  it('renders loop summary current/previous proxy labels from i18n', async () => {
    codexApiMocks.getLoopStatus.mockResolvedValueOnce(
      makeLoopStatus({
        loop_running: true,
        loop_current_round: 4,
        loop_current_proxy_name: 'Round4 Proxy',
        loop_last_proxy_name: 'Round3 Proxy'
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const panel = wrapper.find('[data-testid="codex-loop-panel"]')
    expect(panel.text()).toContain('本轮代理：Round4 Proxy · 上一轮代理：Round3 Proxy')
  })

  it('disables loop controls while refresh polling is in flight', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const statusDeferred = createDeferred<ReturnType<typeof makeStatus>>()
    const loopDeferred = createDeferred<ReturnType<typeof makeLoopStatus>>()
    const logsDeferred = createDeferred<unknown[]>()
    const accountsDeferred = createDeferred<unknown[]>()

    codexApiMocks.getStatus.mockReturnValueOnce(statusDeferred.promise)
    codexApiMocks.getLoopStatus.mockReturnValueOnce(loopDeferred.promise)
    codexApiMocks.getLogs.mockReturnValueOnce(logsDeferred.promise)
    codexApiMocks.getAccounts.mockReturnValueOnce(accountsDeferred.promise)

    vi.advanceTimersByTime(10000)
    await wrapper.vm.$nextTick()

    const startButton = wrapper.find('[data-testid="codex-loop-start"]')
    const stopButton = wrapper.find('[data-testid="codex-loop-stop"]')

    expect((startButton.element as HTMLButtonElement).disabled).toBe(true)
    expect((stopButton.element as HTMLButtonElement).disabled).toBe(true)

    statusDeferred.resolve(makeStatus())
    loopDeferred.resolve(makeLoopStatus())
    logsDeferred.resolve([])
    accountsDeferred.resolve([])
    await flushPromises()
  })
  it('sets start and stop loop button enabled states', async () => {
    const idleWrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const idleStartButton = idleWrapper.find('[data-testid="codex-loop-start"]')
    const idleStopButton = idleWrapper.find('[data-testid="codex-loop-stop"]')

    expect((idleStartButton.element as HTMLButtonElement).disabled).toBe(false)
    expect((idleStopButton.element as HTMLButtonElement).disabled).toBe(true)

    codexApiMocks.getLoopStatus.mockResolvedValueOnce(
      makeLoopStatus({ loop_running: true, loop_current_round: 1 })
    )

    const runningWrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const runningStartButton = runningWrapper.find('[data-testid="codex-loop-start"]')
    const runningStopButton = runningWrapper.find('[data-testid="codex-loop-stop"]')

    expect((runningStartButton.element as HTMLButtonElement).disabled).toBe(true)
    expect((runningStopButton.element as HTMLButtonElement).disabled).toBe(false)

    codexApiMocks.getLoopStatus.mockResolvedValueOnce(
      makeLoopStatus({ loop_running: true, loop_stopping: true, loop_current_round: 1 })
    )

    const stoppingWrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const stoppingStopButton = stoppingWrapper.find('[data-testid="codex-loop-stop"]')

    expect((stoppingStopButton.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('calls startLoop when start button is clicked', async () => {
    codexApiMocks.startLoop.mockResolvedValueOnce(
      makeLoopStatus({ loop_running: true, loop_current_round: 1 })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    await wrapper.find('[data-testid="codex-loop-start"]').trigger('click')
    await flushPromises()

    expect(codexApiMocks.startLoop).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
  })

  it('calls stopLoop when stop button is clicked', async () => {
    codexApiMocks.getLoopStatus.mockResolvedValueOnce(
      makeLoopStatus({ loop_running: true, loop_current_round: 2 })
    )
    codexApiMocks.stopLoop.mockResolvedValueOnce(
      makeLoopStatus({ loop_running: false, loop_stopping: false, loop_current_round: 2 })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    await wrapper.find('[data-testid="codex-loop-stop"]').trigger('click')
    await flushPromises()

    expect(codexApiMocks.stopLoop).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
  })


  it('renders loop history entries', async () => {
    codexApiMocks.getLoopStatus.mockResolvedValueOnce(
      makeLoopStatus({
        loop_history: [
          {
            round: 1,
            started_at: '2026-03-06T11:00:00Z',
            finished_at: '2026-03-06T11:05:00Z',
            status: 'success',
            created: 2,
            updated: 1,
            skipped: 0,
            failed: 0,
            summary: null,
            error: ''
          },
          {
            round: 2,
            started_at: '2026-03-06T12:00:00Z',
            finished_at: '2026-03-06T12:03:00Z',
            status: 'failed',
            created: 1,
            updated: 0,
            skipped: 1,
            failed: 1,
            summary: null,
            error: 'db boom'
          }
        ]
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const historyRows = wrapper.findAll('[data-testid="codex-loop-history-row"]')
    expect(historyRows).toHaveLength(2)
    expect(historyRows[0].text()).toContain('第 2 轮')
    expect(historyRows[0].text()).toContain('失败')
    expect(historyRows[0].text()).toContain('db boom')
    expect(historyRows[1].text()).toContain('第 1 轮')
    expect(historyRows[1].text()).toContain('成功')
  })

  it('renders empty proxy pool helper and adds first proxy url row', async () => {
    codexApiMocks.getProxyStatus.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_pool: []
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(wrapper.text()).toContain('No proxies yet. Add a proxy URL to enable routing.')

    const addButton = wrapper.find('[data-testid="codex-proxy-add"]')
    expect(addButton.exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="codex-proxy-row"]')).toHaveLength(0)

    await addButton.trigger('click')
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="codex-proxy-row"]')
    expect(rows).toHaveLength(1)
    expect(wrapper.findAll('[data-testid^="codex-proxy-name-input-"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid^="codex-proxy-enabled-input-"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid^="codex-proxy-url-input-"]')).toHaveLength(1)
  })


  it('disables proxy save button while initial loading is in progress', async () => {
    codexApiMocks.getProxyStatus.mockImplementationOnce(
      () => new Promise(() => {})
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(wrapper.find('[data-testid="codex-proxy-save"]').attributes('disabled')).toBeDefined()
  })

  it('saves a newly added proxy row using only proxy_url and current routing state', async () => {
    codexApiMocks.getProxyStatus.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_enabled: false,
        proxy_pool: []
      })
    )
    codexApiMocks.saveProxyList.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_enabled: true,
        proxy_pool: [
          {
            id: 'proxy-3',
            name: 'proxy-3',
            proxy_url: 'http://proxy-3:8080',
            enabled: true,
            last_status: 'unknown',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0,
          }
        ]
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    await wrapper.find('[data-testid="codex-proxy-routing-toggle"]').setValue(true)
    await wrapper.find('[data-testid="codex-proxy-add"]').trigger('click')
    await flushPromises()

    const urlInput = wrapper.find('[data-testid^="codex-proxy-url-input-"]')
    await urlInput.setValue('http://proxy-3:8080')

    await wrapper.find('[data-testid="codex-proxy-save"]').trigger('click')
    await flushPromises()

    expect(codexApiMocks.saveProxyList).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.saveProxyList).toHaveBeenCalledWith({
      proxy_enabled: true,
      proxy_pool: [
        {
          proxy_url: 'http://proxy-3:8080'
        }
      ]
    })
    expect(wrapper.find('[data-testid="codex-proxy-test-proxy-3"]').exists()).toBe(true)
  })

  it('save action persists proxy routing flag with saved rows serialized as id plus proxy_url', async () => {
    codexApiMocks.saveProxyList.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_enabled: false,
        proxy_pool: [
          {
            id: 'proxy-1',
            name: 'proxy-1',
            proxy_url: 'http://proxy-1:8080',
            enabled: true,
            last_status: 'ok',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          },
          {
            id: 'proxy-2',
            name: 'proxy-2',
            proxy_url: 'http://proxy-2:8080',
            enabled: true,
            last_status: 'unknown',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          }
        ]
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    await wrapper.find('[data-testid="codex-proxy-routing-toggle"]').setValue(false)
    await wrapper.find('[data-testid="codex-proxy-save"]').trigger('click')
    await flushPromises()

    expect(codexApiMocks.saveProxyList).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.saveProxyList).toHaveBeenCalledWith({
      proxy_enabled: false,
      proxy_pool: [
        {
          id: 'proxy-1',
          proxy_url: 'http://proxy-1:8080'
        },
        {
          id: 'proxy-2',
          proxy_url: 'http://proxy-2:8080'
        }
      ]
    })
  })

  it('does not render dedicated proxy enable or disable buttons', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(wrapper.find('[data-testid="codex-proxy-enable"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="codex-proxy-disable"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="codex-proxy-routing-toggle"]').exists()).toBe(true)
  })

  it('displays available proxy count from total saved rows', async () => {
    codexApiMocks.getProxyStatus.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_pool: [
          {
            id: 'proxy-1',
            name: 'proxy-1',
            proxy_url: 'http://proxy-1:8080',
            enabled: true,
            last_status: 'ok',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          },
          {
            id: 'proxy-2',
            name: 'proxy-2',
            proxy_url: 'http://proxy-2:8080',
            enabled: false,
            last_status: 'ok',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          },
          {
            id: 'proxy-3',
            name: 'proxy-3',
            proxy_url: 'http://proxy-3:8080',
            enabled: true,
            last_status: 'unknown',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          }
        ]
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const countLabel = wrapper.find('[data-testid="codex-proxy-available-count"]')
    expect(countLabel.exists()).toBe(true)
    expect(countLabel.text()).toContain('3')
  })
  it('renders proxy diagnostics by proxy id rather than row index', async () => {

    codexApiMocks.getProxyStatus.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_pool: [
          {
            id: 'proxy-2',
            name: 'Backup Proxy',
            proxy_url: 'http://proxy-2:8080',
            enabled: true,
            last_status: 'failed',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: '2026-03-06T10:03:00Z',
            cooldown_until: null,
            failure_count: 3
          },
          {
            id: 'proxy-1',
            name: 'Primary Proxy',
            proxy_url: 'http://proxy-1:8080',
            enabled: true,
            last_status: 'cooldown',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: '2026-03-06T10:02:00Z',
            cooldown_until: '2026-03-06T10:10:00Z',
            failure_count: 2
          }
        ]
      })
    )

    codexApiMocks.saveProxyList.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_pool: [
          {
            id: 'proxy-1',
            name: 'Primary Proxy First',
            proxy_url: 'http://proxy-1:8080',
            enabled: true,
            last_status: 'cooldown',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: '2026-03-06T10:02:00Z',
            cooldown_until: '2026-03-06T10:10:00Z',
            failure_count: 2
          },
          {
            id: 'proxy-2',
            name: 'Backup Proxy Second',
            proxy_url: 'http://proxy-2:8080',
            enabled: true,
            last_status: 'failed',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: '2026-03-06T10:03:00Z',
            cooldown_until: null,
            failure_count: 3
          }
        ]
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    await wrapper.find('[data-testid="codex-proxy-save"]').trigger('click')
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="codex-proxy-row"]')
    expect(rows).toHaveLength(2)

    expect(rows[0].text()).toContain('proxy-1')
    expect(rows[0].text()).toContain('Status: Cooldown')
    expect(rows[0].text()).toContain('Cooldown: 2026-03-06T10:10:00Z')
    expect(rows[0].text()).toContain('Failed: 2')

    expect(rows[1].text()).toContain('proxy-2')
    expect(rows[1].text()).toContain('Status: Failed')
    expect(rows[1].text()).toContain('Failed: 3')
    expect(rows[1].text()).not.toContain('Cooldown:')
  })

  it('applies returned proxy status to UI after testProxy action', async () => {
    codexApiMocks.testProxy.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_pool: [
          {
            id: 'proxy-1',
            name: 'Primary Proxy',
            proxy_url: 'http://proxy-1:8080',
            enabled: true,
            last_status: 'failed',
            last_checked_at: '2026-03-06T10:12:00Z',
            last_success_at: null,
            last_failure_at: '2026-03-06T10:12:00Z',
            cooldown_until: '2026-03-06T10:20:00Z',
            failure_count: 4
          },
          {
            id: 'proxy-2',
            name: 'Backup Proxy',
            proxy_url: 'http://proxy-2:8080',
            enabled: true,
            last_status: 'ok',
            last_checked_at: '2026-03-06T10:12:00Z',
            last_success_at: '2026-03-06T10:12:00Z',
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          }
        ],
        proxy_last_error: 'dial tcp timeout'
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    await wrapper.find('[data-testid="codex-proxy-test-proxy-1"]').trigger('click')
    await flushPromises()

    expect(codexApiMocks.testProxy).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.testProxy).toHaveBeenCalledWith({ proxy_id: 'proxy-1' })

    const rows = wrapper.findAll('[data-testid="codex-proxy-row"]')
    expect(rows[0].text()).toContain('Status: Failed')
    expect(rows[0].text()).toContain('Cooldown: 2026-03-06T10:20:00Z')
    expect(rows[0].text()).toContain('Failed: 4')

    const errorLabel = wrapper.find('[data-testid="codex-proxy-last-error"]')
    expect(errorLabel.text()).toContain('dial tcp timeout')
  })

  it('displays available proxy count', async () => {
    codexApiMocks.getProxyStatus.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_pool: [
          {
            id: 'proxy-1',
            name: 'Primary Proxy',
            proxy_url: 'http://proxy-1:8080',
            enabled: true,
            last_status: 'ok',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          },
          {
            id: 'proxy-2',
            name: 'Backup Proxy',
            proxy_url: 'http://proxy-2:8080',
            enabled: false,
            last_status: 'ok',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          },
          {
            id: 'proxy-3',
            name: 'Spare Proxy',
            proxy_url: 'http://proxy-3:8080',
            enabled: true,
            last_status: 'unknown',
            last_checked_at: null,
            last_success_at: null,
            last_failure_at: null,
            cooldown_until: null,
            failure_count: 0
          }
        ]
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const countLabel = wrapper.find('[data-testid="codex-proxy-available-count"]')
    expect(countLabel.exists()).toBe(true)
    expect(countLabel.text()).toContain('3')
  })

  it('displays last proxy error', async () => {
    codexApiMocks.getProxyStatus.mockResolvedValueOnce(
      makeProxyStatus({
        proxy_last_error: 'dial tcp timeout'
      })
    )

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const errorLabel = wrapper.find('[data-testid="codex-proxy-last-error"]')
    expect(errorLabel.exists()).toBe(true)
    expect(errorLabel.text()).toContain('dial tcp timeout')
  })
})
