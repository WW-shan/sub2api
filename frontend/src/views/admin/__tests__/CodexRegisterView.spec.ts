import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CodexRegisterView from '../CodexRegisterView.vue'

const codexApiMocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getLogs: vi.fn(),
  enable: vi.fn(),
  disable: vi.fn(),
  runOnce: vi.fn()
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
    'admin.codexRegister.title': 'Codex 注册',
    'admin.codexRegister.heroDescription': '管理 Codex 自动注册服务的运行状态、执行节奏和最近事件，让这套能力和后台其他运维页面保持同一视觉与信息层级。',
    'admin.codexRegister.badge.adminConsole': '后台控制台',
    'admin.codexRegister.badge.running': '运行中',
    'admin.codexRegister.badge.stopped': '已停止',
    'admin.codexRegister.badge.attention': '需关注',
    'admin.codexRegister.badge.healthy': '暂无错误',
    'admin.codexRegister.actions.start': '开启',
    'admin.codexRegister.actions.stop': '关闭',
    'admin.codexRegister.actions.runOnce': '手动执行一次',
    'admin.codexRegister.actions.refreshing': '刷新中…',
    'admin.codexRegister.summary.totalCreated': '累计生成账号数',
    'admin.codexRegister.summary.lastSuccess': '最近成功时间',
    'admin.codexRegister.summary.proxy': '是否配置代理',
    'admin.codexRegister.summary.sleepRange': '休眠区间（秒）',
    'admin.codexRegister.summary.empty': '暂无',
    'admin.codexRegister.summary.proxyConfigured': '已配置',
    'admin.codexRegister.summary.proxyMissing': '未配置',
    'admin.codexRegister.panels.statusTitle': '当前状态',
    'admin.codexRegister.panels.statusDescription': '统一查看当前开关状态、代理配置和最近一次失败信息。',
    'admin.codexRegister.panels.serviceStatus': '服务状态',
    'admin.codexRegister.panels.serviceEnabled': '当前状态：已开启自动注册',
    'admin.codexRegister.panels.serviceDisabled': '当前状态：已关闭自动注册',
    'admin.codexRegister.panels.proxyConfig': '代理配置',
    'admin.codexRegister.panels.proxyConfiguredDetail': '已配置代理，容器可按当前出口执行注册',
    'admin.codexRegister.panels.proxyMissingDetail': '未配置代理，请确认网络出口要求',
    'admin.codexRegister.panels.lastSuccessTitle': '最近成功时间',
    'admin.codexRegister.panels.lastSuccessEmpty': '暂无成功记录',
    'admin.codexRegister.panels.sleepRangeTitle': '休眠区间',
    'admin.codexRegister.panels.errorTitle': '最近错误日志',
    'admin.codexRegister.panels.noErrors': '最近没有错误输出，服务状态看起来正常。',
    'admin.codexRegister.panels.eventsTitle': '最近事件',
    'admin.codexRegister.panels.eventsDescription': '展示服务最近的运行记录和错误，便于快速排查容器执行情况。',
    'admin.codexRegister.panels.emptyEvents': '暂无事件'
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

describe('CodexRegisterView', () => {
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
      proxy: true
    })

    codexApiMocks.getLogs.mockResolvedValue([
      {
        level: 'info',
        time: '2026-03-06 10:00:01',
        message: 'run completed'
      }
    ])
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('keeps operational sections and removes intro/cumulative content', async () => {
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

    const wrapper = mount(CodexRegisterView, {
      global: {
        stubs: {
          AppLayout: {
            template: '<div><slot /></div>'
          }
        }
      }
    })
    await flushPromises()

    expect(codexApiMocks.getStatus).toHaveBeenCalledTimes(1)
    expect(codexApiMocks.getLogs).toHaveBeenCalledTimes(1)

    const pageText = wrapper.text()

    expect(pageText).toContain('当前状态')
    expect(pageText).toContain('手动执行一次')
    expect(pageText).toContain('累计生成账号数')
    expect(pageText).toContain('18')
    expect(pageText).toContain('最近成功时间')
    expect(pageText).toContain('是否配置代理')
    expect(pageText).toContain('休眠区间（秒）')
    expect(pageText).toContain('最近错误日志')
    expect(pageText).toContain('最近事件')
    expect(pageText).toContain('run completed')

    expect(pageText).not.toContain('该页面用于说明 Codex 自动注册容器的工作方式')
    expect(pageText).not.toContain('累计创建账号数')
    expect(pageText).not.toContain('累计更新账号数')
    expect(pageText).not.toContain('累计跳过次数')
    expect(pageText).not.toContain('本轮处理记录数')
    expect(pageText).not.toContain('快速入口')

    wrapper.unmount()
    expect(clearIntervalSpy).toHaveBeenCalled()
    clearIntervalSpy.mockRestore()
  })

  it('clears stale status content when initial requests fail', async () => {
    codexApiMocks.getStatus.mockRejectedValueOnce(new Error('status failed'))
    codexApiMocks.getLogs.mockRejectedValueOnce(new Error('logs failed'))

    const wrapper = mount(CodexRegisterView, {
      global: {
        stubs: {
          AppLayout: {
            template: '<div><slot /></div>'
          }
        }
      }
    })

    await flushPromises()

    const pageText = wrapper.text()

    expect(pageText).toContain('logs failed')
    expect(pageText).toContain('未知')
    expect(pageText).toContain('暂无事件')
    expect(pageText).not.toContain('当前状态：已关闭自动注册')
    expect(pageText).not.toContain('已配置代理，容器可按当前出口执行注册')
  })
})
