import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  EntryRow,
  OverviewResult,
  PageResult,
} from '@/data/types'
import type {
  ReportListResult,
  SnapshotDifferenceView,
} from '@/data/snapshot'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export async function loadSnapshotDifference(
  pageUri: string,
): Promise<SnapshotDifferenceView> {
  const query = new URLSearchParams({ 页面URI: pageUri }).toString()
  const response = await request(`/api/page_snapshot/snapshot-difference?${query}`)
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail ?? `快照差异视图读取失败（${response.status}）`)
  }
  return await response.json()
}

export async function loadSnapshotReports(pageUri: string): Promise<ReportListResult> {
  const query = new URLSearchParams({ 页面URI: pageUri }).toString()
  const response = await request(`/api/quality_check/reports?${query}`)
  if (!response.ok) throw new Error('质量报告读取失败')
  return await response.json()
}

export async function generateSnapshotReport(
  pageUri: string,
  snapshotIds?: number[],
): Promise<{ ok: boolean; message: string }> {
  const values: Record<string, unknown> = { 页面URI: pageUri }
  if (snapshotIds?.length) values.snapshot_ids = snapshotIds
  const response = await request('/api/quality_check/reports', {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}
