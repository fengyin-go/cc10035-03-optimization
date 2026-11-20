/** 快照差异数据视图与质量报告的前端契约，与 page_snapshot / quality_check 服务返回一致。 */

export type SnapshotRowView = {
  id: number
  快照ID: string
  抓取时间: string
  DOM哈希: string
  文本哈希: string
  页面URI: string
  采集序号: number
  迟到: boolean
}

export type SnapshotIntervalView = {
  区间ID: string
  采集序号: number | null
  前快照ID: number
  后快照ID: number
  前抓取时间: string
  后抓取时间: string
  前DOM哈希: string
  后DOM哈希: string
  前文本哈希: string
  后文本哈希: string
  DOM是否变化: boolean
  文本是否变化: boolean
  变化项数: number
  来源: '当前报告' | '迟到快照' | '未引用'
  当前相邻: boolean
  与报告冲突: boolean
  迟到快照涉及: boolean
  说明?: string
  报告区间序号?: number
}

export type CheckItem = {
  name: string
  passed: boolean
  detail: string
}

export type ReportConflict = {
  报告编号: string
  报告快照对: number[]
  当前实际相邻快照对: number[] | null
  迟到快照ID: number[]
  说明: string
}

export type QualityReportView = {
  id: number
  报告编号: string
  页面URI: string
  生成时间: string
  证据来源: string
  采用快照对: number[][]
  采用快照标识: string
  证据明细: {
    left_snapshot_id: number
    right_snapshot_id: number
    left_time: string | null
    right_time: string | null
    change_count: number
    dom_changed: boolean
    text_changed: boolean
  }[]
  DOM结论: string
  文本结论: string
  变化项数: number
  检查清单: CheckItem[]
  规则更新建议: boolean
  迟到快照ID: number[]
  冲突: ReportConflict[]
  状态: '有效' | '需复核' | '缺证据'
  是否需复核: boolean
}

export type DuplicateRegistration = {
  duplicate_id: number
  snapshot_id: string
  页面URI?: string
  canonical_id: number
  抓取时间: string
  attempted_at?: string
}

export type SnapshotDifferenceView = {
  ok: boolean
  页面URI: string
  快照数: number
  重复登记数: number
  快照: SnapshotRowView[]
  比较区间: SnapshotIntervalView[]
  迟到快照: SnapshotRowView[]
  重复登记: DuplicateRegistration[]
  当前报告: QualityReportView | null
  当前报告采用的证据: SnapshotIntervalView[]
  报告采用快照对仍相邻: boolean
  迟到快照涉及的新比较区间: SnapshotIntervalView[]
  冲突: ReportConflict[]
  变化项数合计: number
  报告变化项数: number
}

export type ReportListResult = {
  ok: boolean
  items: QualityReportView[]
  total: number
}
