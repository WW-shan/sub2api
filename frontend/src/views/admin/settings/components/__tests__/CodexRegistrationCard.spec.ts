import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CodexRegistrationCard from '../CodexRegistrationCard.vue'

const StatCardStub = {
  props: ['title', 'value'],
  template: '<div>{{ title }} {{ value }}</div>'
}

const codexApiMocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getLogs: vi.fn(),
  getAccounts: vi.fn(),
  enable: vi.fn(),
  disable: vi.fn(),
  resume: vi.fn(),
  retry: vi.fn()
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
    last_transition: null,
    last_resume_gate_reason: null,
    recent_logs_tail: [],
    ...overrides
  }
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
    'admin.codexRegister.phase.unknown': '未知阶段',
    'admin.codexRegister.phase.idle': '未运行',
    'admin.codexRegister.phase.runningCreateParent': '正在创建母号',
    'admin.codexRegister.phase.waitingManual': '等待你手动操作',
    'admin.codexRegister.phase.runningPreResumeCheck': '继续前校验中',
    'admin.codexRegister.phase.runningInviteChildren': '正在邀请子号',
    'admin.codexRegister.phase.runningAcceptAndSwitch': '子号接受并切组中',
    'admin.codexRegister.phase.runningVerifyAndBind': '正在校验并绑定',
    'admin.codexRegister.phase.abandoned': '已终止',
    'admin.codexRegister.phase.failed': '执行失败',
    'admin.codexRegister.waitingReason.parentUpgrade': '需要先完成母号升级',
    'admin.codexRegister.waitingTodo.title': '待办清单',
    'admin.codexRegister.waitingTodo.afterTip': '完成以上操作后，点击“继续”以恢复自动流程。',
    'admin.codexRegister.waitingTodo.parentUpgrade.step1': '登录母号并完成升级流程。',
    'admin.codexRegister.waitingTodo.parentUpgrade.step2': '确认升级成功且账户状态正常。',
    'admin.codexRegister.waitingTodo.parentUpgrade.step3': '返回本页后点击“继续”。',
    'admin.codexRegister.waitingTodo.generic.step1': '根据等待原因完成对应手动操作。',
    'admin.codexRegister.waitingTodo.generic.step2': '确认操作已在目标平台生效。',
    'admin.codexRegister.waitingTodo.generic.step3': '返回本页后点击“继续”。',
    'admin.codexRegister.panels.statusTitle': '当前状态',
    'admin.codexRegister.panels.statusDescription': 'status description',
    'admin.codexRegister.panels.serviceStatus': '服务状态',
    'admin.codexRegister.panels.proxyConfig': '代理配置',
    'admin.codexRegister.panels.proxyConfiguredDetail': '已配置代理，容器可按当前出口执行注册',
    'admin.codexRegister.panels.proxyMissingDetail': '未配置代理，请确认网络出口要求',
    'admin.codexRegister.panels.phaseTitle': '工作流阶段',
    'admin.codexRegister.panels.waitingReasonTitle': '等待原因',
    'admin.codexRegister.panels.waitingReasonEmpty': '当前无需等待',
    'admin.codexRegister.panels.lastSuccessTitle': '最近成功时间',
    'admin.codexRegister.panels.lastSuccessEmpty': '暂无成功记录',
    'admin.codexRegister.panels.sleepRangeTitle': '休眠区间',
    'admin.codexRegister.panels.errorTitle': '最近错误日志',
    'admin.codexRegister.panels.noErrors': '最近没有错误输出，服务状态看起来正常。',
    'admin.codexRegister.panels.eventsTitle': '最近事件',
    'admin.codexRegister.panels.eventsDescription': 'events description',
    'admin.codexRegister.panels.emptyEvents': '暂无事件',
    'admin.codexRegister.accounts.title': '已创建账户',
    'admin.codexRegister.accounts.description': '仅展示 codex-register 自动创建记录',
    'admin.codexRegister.accounts.empty': '暂无账号记录',
    'admin.codexRegister.accounts.columns.email': '邮箱',
    'admin.codexRegister.accounts.columns.accessToken': 'Access Token',
    'admin.codexRegister.accounts.columns.refreshToken': 'Refresh Token',
    'admin.codexRegister.accounts.columns.accountId': 'Account ID',
    'admin.codexRegister.accounts.columns.createdAt': '创建时间',
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
    'admin.codexRegister.debug.resumeUnknown': 'Resume unknown'
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

    const showButtons = wrapper.findAll('button').filter((btn) => btn.text() === '显示')
    expect(showButtons.length).toBe(2)

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

    const resumeButton = wrapper.findAll('button').find((btn) => btn.text() === '继续')
    expect(resumeButton).toBeDefined()

    await resumeButton!.trigger('click')
    await flushPromises()

    expect(codexApiMocks.resume).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('正在创建母号')
  })

  it('switches stop button to retry button in cancelled waiting state', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce({
      enabled: false,
      sleep_min: 12,
      sleep_max: 34,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'waiting_manual:cancelled',
      workflow_id: 'wf-2',
      waiting_reason: 'cancelled',
      can_start: false,
      can_resume: true,
      can_abandon: false
    })

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const controlbar = wrapper.find('[data-testid="codex-controlbar-secondary"]')
    expect(controlbar.text()).toContain('重试')
    expect(controlbar.text()).not.toContain('停止')
  })

  it('calls retry endpoint when cancelled retry button is clicked', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce({
      enabled: false,
      sleep_min: 12,
      sleep_max: 34,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'waiting_manual:cancelled',
      workflow_id: 'wf-2',
      waiting_reason: 'cancelled',
      can_start: false,
      can_resume: true,
      can_abandon: false
    })

    codexApiMocks.retry.mockResolvedValueOnce({
      enabled: true,
      sleep_min: 12,
      sleep_max: 34,
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
    })

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const retryButton = wrapper.findAll('button').find((btn) => btn.text() === '重试')
    expect(retryButton).toBeDefined()

    await retryButton!.trigger('click')
    await flushPromises()

    expect(codexApiMocks.retry).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('正在创建母号')
  })

  it('uses retry as primary action in cancelled waiting state', async () => {
    codexApiMocks.getStatus.mockResolvedValueOnce({
      enabled: false,
      sleep_min: 12,
      sleep_max: 34,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'waiting_manual:cancelled',
      workflow_id: 'wf-2',
      waiting_reason: 'cancelled',
      can_start: false,
      can_resume: true,
      can_abandon: false
    })

    codexApiMocks.retry.mockResolvedValueOnce({
      enabled: true,
      sleep_min: 12,
      sleep_max: 34,
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
    })

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const primaryButton = wrapper.find('[data-testid="codex-controlbar-primary"] button')
    expect(primaryButton.text()).toBe('重试')

    await primaryButton.trigger('click')
    await flushPromises()

    expect(codexApiMocks.retry).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.resume).not.toHaveBeenCalled()
  })

  it('passes selected level and limit to getLogs', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const levelSelect = wrapper.find('[data-testid="codex-log-level"]')
    const limitSelect = wrapper.find('[data-testid="codex-log-limit"]')

    await levelSelect.setValue('warn')
    await limitSelect.setValue('50')
    await flushPromises()

    const lastCall = codexApiMocks.getLogs.mock.calls.at(-1)
    expect(lastCall?.[0]).toEqual({ level: 'warn', limit: 50 })
  })

  it('renders debug snapshot before events and status sections', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const order = wrapper
      .findAll('[data-section-order]')
      .map((node) => node.attributes('data-section-order'))

    expect(order).toEqual(['debug', 'events', 'status'])
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

  it('renders log limit options 50/100/200 and requests logs with selected level/limit', async () => {
    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const limitSelect = wrapper.find('[data-testid="codex-log-limit"]')
    const options = limitSelect.findAll('option').map((option) => option.text())
    expect(options).toEqual(['50', '100', '200'])

    await limitSelect.setValue('100')
    await flushPromises()

    const lastCall = codexApiMocks.getLogs.mock.calls.at(-1)
    expect(lastCall?.[0]).toEqual({ level: undefined, limit: 100 })
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

  it('polls only when active and stops when deactivated', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval')
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: false },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    expect(codexApiMocks.getStatus).not.toHaveBeenCalled()
    expect(codexApiMocks.getLogs).not.toHaveBeenCalled()
    expect(setIntervalSpy).not.toHaveBeenCalled()

    await wrapper.setProps({ active: true })
    await flushPromises()

    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getAccounts).toHaveBeenCalledTimes(1)
    expect(setIntervalSpy).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(10000)
    await flushPromises()

    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getAccounts).toHaveBeenCalledTimes(2)

    await wrapper.setProps({ active: false })
    await flushPromises()

    expect(clearIntervalSpy).toHaveBeenCalled()

    vi.advanceTimersByTime(10000)
    await flushPromises()

    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
    expect(codexApiMocks.getAccounts).toHaveBeenCalledTimes(2)

    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
  })

  it('copies account secrets with copy action', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    const wrapper = mount(CodexRegistrationCard, {
      props: { active: true },
      global: { stubs: { StatCard: StatCardStub } }
    })

    await flushPromises()

    const copyButtons = wrapper.findAll('button').filter((btn) => btn.text() === '复制')
    expect(copyButtons.length).toBeGreaterThan(0)

    await copyButtons[0].trigger('click')
    expect(writeText).toHaveBeenCalled()
  })
})