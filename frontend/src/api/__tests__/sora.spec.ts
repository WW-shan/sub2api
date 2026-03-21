import { describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import {
  getProxyStatus,
  getLoopStatus,
  saveProxyList,
  selectProxy,
  testProxy
} from '../admin/codex'
import {
  normalizeGenerationListResponse,
  normalizeModelFamiliesResponse
} from '../sora'

vi.mock('@/i18n', () => ({
  getLocale: () => 'zh-CN'
}))

describe('sora api normalizers', () => {
  it('normalizes generation list from data shape', () => {
    const result = normalizeGenerationListResponse({
      data: [{ id: 1, status: 'pending' }],
      total: 9,
      page: 2
    })

    expect(result.data).toHaveLength(1)
    expect(result.total).toBe(9)
    expect(result.page).toBe(2)
  })

  it('normalizes generation list from items shape', () => {
    const result = normalizeGenerationListResponse({
      items: [{ id: 1, status: 'completed' }],
      total: 1
    })

    expect(result.data).toHaveLength(1)
    expect(result.total).toBe(1)
    expect(result.page).toBe(1)
  })

  it('falls back to empty generation list on invalid payload', () => {
    const result = normalizeGenerationListResponse(null)
    expect(result).toEqual({ data: [], total: 0, page: 1 })
  })

  it('normalizes family model payload', () => {
    const result = normalizeModelFamiliesResponse({
      data: [
        {
          id: 'sora2',
          name: 'Sora 2',
          type: 'video',
          orientations: ['landscape', 'portrait'],
          durations: [10, 15]
        }
      ]
    })

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('sora2')
    expect(result[0].orientations).toEqual(['landscape', 'portrait'])
    expect(result[0].durations).toEqual([10, 15])
  })

  it('normalizes legacy flat model list into families', () => {
    const result = normalizeModelFamiliesResponse({
      items: [
        { id: 'sora2-landscape-10s', type: 'video' },
        { id: 'sora2-portrait-15s', type: 'video' },
        { id: 'gpt-image-square', type: 'image' }
      ]
    })

    const sora2 = result.find((m) => m.id === 'sora2')
    expect(sora2).toBeTruthy()
    expect(sora2?.orientations).toEqual(['landscape', 'portrait'])
    expect(sora2?.durations).toEqual([10, 15])

    const image = result.find((m) => m.id === 'gpt-image')
    expect(image).toBeTruthy()
    expect(image?.type).toBe('image')
    expect(image?.orientations).toEqual(['square'])
  })

  it('falls back to empty families on invalid payload', () => {
    expect(normalizeModelFamiliesResponse(undefined)).toEqual([])
    expect(normalizeModelFamiliesResponse({})).toEqual([])
  })
})

describe('codex proxy api', () => {
  it('normalizes proxy status envelope payload', async () => {
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        success: true,
        data: {
          proxy_enabled: true,
          proxy_current_id: 'p-2',
          proxy_current_name: 'Proxy B',
          proxy_last_used_id: 100,
          proxy_last_used_name: '',
          proxy_last_checked_at: '',
          proxy_last_error: '',
          proxy_last_switch_reason: null,
          proxy_pool: [
            {
              id: 'p-2',
              name: 'Proxy B',
              proxy_url: 'http://127.0.0.1:8080',
              enabled: true,
              last_status: 'ok',
              last_checked_at: '2026-03-21T10:00:00Z',
              last_success_at: '',
              last_failure_at: '',
              cooldown_until: '',
              failure_count: '2'
            }
          ]
        }
      }
    } as any)

    const result = await getProxyStatus()

    expect(getSpy).toHaveBeenCalledWith('/admin/codex/proxy/status')
    expect(result.proxy_enabled).toBe(true)
    expect(result.proxy_current_id).toBe('p-2')
    expect(result.proxy_last_used_id).toBe('100')
    expect(result.proxy_last_used_name).toBeNull()
    expect(result.proxy_pool[0].failure_count).toBe(2)
    expect(result.proxy_pool[0].last_success_at).toBeNull()
    expect(result.proxy_pool[0].cooldown_until).toBeNull()

    getSpy.mockRestore()
  })

  it('normalizes loop status proxy runtime fields', async () => {
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        success: true,
        data: {
          loop_running: true,
          loop_current_round: 4,
          loop_current_proxy_id: 12,
          loop_current_proxy_name: 'Proxy C',
          loop_last_proxy_id: '',
          loop_last_proxy_name: '',
          loop_last_switch_reason: 'probe_ok',
          loop_history: []
        }
      }
    } as any)

    const result = await getLoopStatus()

    expect(getSpy).toHaveBeenCalledWith('/admin/codex/loop/status')
    expect(result.loop_current_proxy_id).toBe('12')
    expect(result.loop_current_proxy_name).toBe('Proxy C')
    expect(result.loop_last_proxy_id).toBeNull()
    expect(result.loop_last_proxy_name).toBeNull()
    expect(result.loop_last_switch_reason).toBe('probe_ok')

    getSpy.mockRestore()
  })

  it('posts proxy actions to expected endpoints', async () => {
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        success: true,
        data: {
          proxy_enabled: false,
          proxy_current_id: null,
          proxy_current_name: null,
          proxy_last_used_id: null,
          proxy_last_used_name: null,
          proxy_last_checked_at: null,
          proxy_last_error: null,
          proxy_last_switch_reason: null,
          proxy_pool: []
        }
      }
    } as any)

    await saveProxyList({
      proxy_enabled: true,
      proxy_pool: [
        { id: 'p-1', name: 'Proxy A', proxy_url: 'http://127.0.0.1:9000', enabled: true }
      ]
    })
    await selectProxy({ proxy_id: 'p-1' })
    await testProxy({ proxy_id: 'p-1' })

    expect(postSpy).toHaveBeenNthCalledWith(
      1,
      '/admin/codex/proxy/list',
      expect.objectContaining({ proxy_enabled: true })
    )
    expect(postSpy).toHaveBeenNthCalledWith(2, '/admin/codex/proxy/select', { proxy_id: 'p-1' })
    expect(postSpy).toHaveBeenNthCalledWith(3, '/admin/codex/proxy/test', { proxy_id: 'p-1' })

    postSpy.mockRestore()
  })
})
