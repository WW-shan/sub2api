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

    expect(pageText).toContain('Codex 注册')
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
})
