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
  runOnce: vi.fn(),
  resume: vi.fn()
}))

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
    'admin.codexRegister.badge.running': '运行中',
    'admin.codexRegister.badge.stopped': '已停止',
    'admin.codexRegister.badge.attention': '需关注',
    'admin.codexRegister.badge.healthy': '暂无错误',
    'admin.codexRegister.actions.start': '开启',
    'admin.codexRegister.actions.stop': '关闭',
    'admin.codexRegister.actions.resume': '恢复',
    'admin.codexRegister.actions.runOnce': '手动执行一次',
    'admin.codexRegister.actions.refreshing': '刷新中…',
    'admin.codexRegister.actions.copy': '复制',
    'admin.codexRegister.summary.totalCreated': '累计生成账号数',
    'admin.codexRegister.summary.lastSuccess': '最近成功时间',
    'admin.codexRegister.summary.proxy': '是否配置代理',
    'admin.codexRegister.summary.sleepRange': '休眠区间（秒）',
    'admin.codexRegister.summary.proxyConfigured': '已配置',
    'admin.codexRegister.summary.proxyMissing': '未配置',
    'admin.codexRegister.summary.rangeValue': 'range',
    'admin.codexRegister.summary.rangeValueWithUnit': 'range with unit',
    'admin.codexRegister.panels.statusTitle': '当前状态',
    'admin.codexRegister.panels.statusDescription': 'status description',
    'admin.codexRegister.panels.serviceStatus': '服务状态',
    'admin.codexRegister.panels.serviceEnabled': '当前状态：已开启自动注册',
    'admin.codexRegister.panels.serviceDisabled': '当前状态：已关闭自动注册',
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
    'admin.codexRegister.accounts.columns.password': '密码',
    'admin.codexRegister.accounts.columns.accessToken': 'Access Token',
    'admin.codexRegister.accounts.columns.refreshToken': 'Refresh Token',
    'admin.codexRegister.accounts.columns.accountId': 'Account ID',
    'admin.codexRegister.accounts.columns.createdAt': '创建时间'
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

    codexApiMocks.getStatus.mockResolvedValue({
      enabled: true,
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
      can_abandon: true
    })

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
        password: 'pw-123',
        access_token: 'at-123',
        refresh_token: 'rt-123',
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

  it('renders operational status, summary, and logs', async () => {
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

    const wrapper = mount(CodexRegistrationCard, {
      props: {
        active: true
      },
      global: {
        stubs: {
          StatCard: StatCardStub
        }
      }
    })

    await flushPromises()

    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getAccounts).toHaveBeenCalledTimes(1)

    const cardText = wrapper.text()

    expect(cardText).toContain('当前状态')
    expect(cardText).toContain('手动执行一次')
    expect(cardText).toContain('恢复')
    expect(cardText).toContain('12 - 34 秒')
    expect(cardText).toContain('18')
    expect(cardText).toContain('最近成功时间')
    expect(cardText).toContain('是否配置代理')
    expect(cardText).toContain('休眠区间（秒）')
    expect(cardText).toContain('工作流阶段')
    expect(cardText).toContain('waiting_manual:db_connect_failed')
    expect(cardText).toContain('等待原因')
    expect(cardText).toContain('db_connect_failed')
    expect(cardText).toContain('最近错误日志')
    expect(cardText).toContain('最近事件')
    expect(cardText).toContain('run completed')
    expect(cardText).toContain('已创建账户')
    expect(cardText).toContain('a@example.com')
    expect(cardText).toContain('pw-123')
    expect(cardText).toContain('at-123')
    expect(cardText).toContain('rt-123')

    const buttons = wrapper.findAll('button')
    const startButton = buttons.find((btn) => btn.text() === '开启')
    const stopButton = buttons.find((btn) => btn.text() === '关闭')
    const resumeButton = buttons.find((btn) => btn.text() === '恢复')
    const runOnceButton = buttons.find((btn) => btn.text() === '手动执行一次')

    expect(startButton?.attributes('disabled')).toBeDefined()
    expect(stopButton?.attributes('disabled')).toBeUndefined()
    expect(resumeButton?.attributes('disabled')).toBeUndefined()
    expect(runOnceButton?.attributes('disabled')).toBeDefined()

    wrapper.unmount()
    expect(clearIntervalSpy).toHaveBeenCalled()
    clearIntervalSpy.mockRestore()
  })

  it('polls only when active and stops when deactivated', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval')
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

    const wrapper = mount(CodexRegistrationCard, {
      props: {
        active: false
      },
      global: {
        stubs: {
          StatCard: StatCardStub
        }
      }
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

  it('calls resume endpoint when resume action is clicked', async () => {
    codexApiMocks.resume.mockResolvedValueOnce({
      enabled: true,
      sleep_min: 12,
      sleep_max: 34,
      total_created: 19,
      last_success: '2026-03-06 10:05:00',
      last_error: null,
      proxy: true,
      job_phase: 'running:create_parent',
      workflow_id: 'wf-2',
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

    const resumeButton = wrapper
      .findAll('button')
      .find((btn) => btn.text() === '恢复')

    expect(resumeButton).toBeDefined()

    await resumeButton!.trigger('click')
    await flushPromises()

    expect(codexApiMocks.resume).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('running:create_parent')
  })

  it('shows error details when initial requests fail', async () => {
    codexApiMocks.getStatus.mockRejectedValueOnce(new Error('status failed'))
    codexApiMocks.getLogs.mockRejectedValueOnce(new Error('logs failed'))
    codexApiMocks.getAccounts.mockResolvedValueOnce([])

    const wrapper = mount(CodexRegistrationCard, {
      props: {
        active: true
      },
      global: {
        stubs: {
          StatCard: StatCardStub
        }
      }
    })

    await flushPromises()

    const cardText = wrapper.text()

    expect(cardText).toContain('logs failed')
    expect(cardText).toContain('未知')
    expect(cardText).toContain('暂无事件')
    expect(cardText).not.toContain('当前状态：已关闭自动注册')
    expect(cardText).not.toContain('已配置代理，容器可按当前出口执行注册')
  })
})
