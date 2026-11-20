<template>
  <section v-if="pageUri" class="snapshot-diff" data-testid="snapshot-diff">
    <header class="diff-head">
      <div>
        <h3>快照差异数据视图</h3>
        <p class="diff-sub">{{ pageUri }}</p>
      </div>
      <div class="diff-actions">
        <button
          class="btn"
          type="button"
          data-testid="diff-generate-report"
          :disabled="busy || snapshots.length < 2"
          @click="generateReport"
        >
          生成质量报告
        </button>
        <button class="btn ghost" type="button" data-testid="diff-refresh" @click="reload">
          刷新
        </button>
      </div>
    </header>

    <p v-if="message" class="error-text" data-testid="diff-message">{{ message }}</p>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">同页快照</span>
        <strong class="stat-value" data-testid="diff-snapshot-count">{{ view?.快照数 ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">比较区间</span>
        <strong class="stat-value" data-testid="diff-interval-count">{{ view?.比较区间.length ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">当前区间变化项</span>
        <strong class="stat-value" data-testid="diff-change-count">{{ view?.变化项数合计 ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">报告变化项</span>
        <strong class="stat-value" data-testid="diff-report-change-count">
          {{ view?.报告变化项数 ?? 0 }}
        </strong>
      </article>
    </div>

    <p class="diff-sub" data-testid="diff-freshness">{{ freshness }}</p>

    <h4 class="diff-title">快照与比较区间（按抓取时间）</h4>
    <table class="data-table" data-testid="diff-interval-table">
      <thead>
        <tr>
          <th>#</th>
          <th>前快照</th>
          <th>抓取时间</th>
          <th>DOM哈希</th>
          <th>文本哈希</th>
          <th>后快照</th>
          <th>抓取时间</th>
          <th>DOM哈希</th>
          <th>文本哈希</th>
          <th>变化项</th>
          <th>来源</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in intervals"
          :key="`${item.区间ID}-${item.报告区间序号 ?? ''}`"
          :data-testid="`interval-${item.区间ID}`"
          :data-source="item.来源"
          :class="{ 'row-conflict': item.与报告冲突 }"
        >
          <td>{{ item.采集序号 ?? '—' }}</td>
          <td>#{{ item.前快照ID }}</td>
          <td>{{ item.前抓取时间 ?? '—' }}</td>
          <td class="hash">{{ item.前DOM哈希 || '—' }}</td>
          <td class="hash">{{ item.前文本哈希 || '—' }}</td>
          <td>#{{ item.后快照ID }}</td>
          <td>{{ item.后抓取时间 ?? '—' }}</td>
          <td class="hash">{{ item.后DOM哈希 || '—' }}</td>
          <td class="hash">{{ item.后文本哈希 || '—' }}</td>
          <td>{{ item.变化项数 }}</td>
          <td>
            <span class="tag" :class="`tag-${item.来源}`">{{ item.来源 }}</span>
            <span v-if="item.与报告冲突" class="tag tag-conflict">与报告冲突</span>
            <span v-if="item.说明" class="diff-note">{{ item.说明 }}</span>
          </td>
        </tr>
        <tr v-if="!intervals.length">
          <td colspan="11" class="empty-state">同页快照不足两份，暂无比较区间</td>
        </tr>
      </tbody>
    </table>

    <div class="diff-columns">
      <section>
        <h4 class="diff-title">当前报告采用的证据</h4>
        <ul class="diff-list" data-testid="diff-adopted">
          <li v-for="item in adoptedEvidence" :key="item.区间ID">
            #{{ item.前快照ID }}（{{ item.前抓取时间 }}）→ #{{ item.后快照ID }}（{{
              item.后抓取时间
            }}），变化 {{ item.变化项数 }} 项
            <span v-if="item.与报告冲突" class="tag tag-conflict">已不相邻</span>
          </li>
          <li v-if="!adoptedEvidence.length" class="empty-state">尚未生成质量报告</li>
        </ul>
      </section>
      <section>
        <h4 class="diff-title">迟到快照涉及的新比较区间</h4>
        <ul class="diff-list" data-testid="diff-late-intervals">
          <li v-for="item in lateIntervals" :key="item.区间ID">
            #{{ item.前快照ID }}（{{ item.前抓取时间 }}）→ #{{ item.后快照ID }}（{{
              item.后抓取时间
            }}），变化 {{ item.变化项数 }} 项
            <span v-if="item.与报告冲突" class="tag tag-conflict">与报告冲突</span>
          </li>
          <li v-if="!lateIntervals.length" class="empty-state">没有迟到快照影响比较区间</li>
        </ul>
      </section>
    </div>

    <div v-if="view?.当前报告" class="diff-report" data-testid="diff-report">
      <header class="diff-head">
        <h4 class="diff-title">
          质量报告 {{ view.当前报告.报告编号 }}
          <span class="tag" :class="`tag-${view.当前报告.状态}`">{{ view.当前报告.状态 }}</span>
        </h4>
        <span class="diff-sub">来源：{{ view.当前报告.证据来源 }}</span>
      </header>
      <p class="diff-sub">
        DOM：{{ view.当前报告.DOM结论 }}；文本：{{ view.当前报告.文本结论 }}；变化项
        {{ view.当前报告.变化项数 }} 项；规则更新建议：
        {{ view.当前报告.规则更新建议 ? '需要' : '不需要' }}
      </p>
      <ul class="diff-list" data-testid="diff-checklist">
        <li v-for="item in view.当前报告.检查清单" :key="item.name">
          <span class="tag" :class="item.passed ? 'tag-通过' : 'tag-需复核'">
            {{ item.passed ? '通过' : '预警' }}
          </span>
          {{ item.name }}：{{ item.detail }}
        </li>
      </ul>
      <ul v-if="view.冲突.length" class="diff-list" data-testid="diff-conflicts">
        <li v-for="item in view.冲突" :key="item.报告编号">
          {{ item.说明 }}：报告引用 #{{ item.报告快照对[0] }}→#{{ item.报告快照对[1] }}，当前实际相邻
          <template v-if="item.当前实际相邻快照对">
            #{{ item.当前实际相邻快照对[0] }}→#{{ item.当前实际相邻快照对[1] }}
          </template>
          <template v-else>区间已不存在</template>
        </li>
      </ul>
    </div>
    <p v-else class="diff-sub">尚未生成质量报告，生成后报告将引用当前相邻的两份快照。</p>

    <p v-if="duplicates.length" class="diff-sub" data-testid="diff-duplicates">
      重复登记（未产生新比较区间）：
      <span v-for="item in duplicates" :key="`${item.duplicate_id}-${item.attempted_at}`">
        #{{ item.canonical_id }} {{ item.snapshot_id }}；</span>
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  generateSnapshotReport,
  loadSnapshotDifference,
} from '@/api/backend-service'
import type { SnapshotDifferenceView, SnapshotIntervalView } from '@/data/snapshot'

const props = defineProps<{ pageUri: string; refreshKey?: number }>()
const view = ref<SnapshotDifferenceView | null>(null)
const message = ref('')
const busy = ref(false)

const snapshots = computed(() => view.value?.快照 ?? [])
const intervals = computed<SnapshotIntervalView[]>(() => {
  const current = view.value?.比较区间 ?? []
  const adopted = view.value?.当前报告采用的证据 ?? []
  const extra = adopted.filter((item) => !current.some((row) => row.区间ID === item.区间ID))
  return [...current, ...extra]
})
const adoptedEvidence = computed(() => view.value?.当前报告采用的证据 ?? [])
const lateIntervals = computed(() => view.value?.迟到快照涉及的新比较区间 ?? [])
const duplicates = computed(() => view.value?.重复登记 ?? [])
const freshness = computed(() => {
  if (!view.value?.当前报告) return '尚无报告'
  return view.value.报告采用快照对仍相邻 ? '报告证据仍为当前相邻区间' : '报告证据已被迟到快照拆开'
})

async function reload() {
  if (!props.pageUri) return
  message.value = ''
  try {
    view.value = await loadSnapshotDifference(props.pageUri)
  } catch (error) {
    view.value = null
    message.value = error instanceof Error ? error.message : '快照差异视图读取失败'
  }
}

async function generateReport() {
  busy.value = true
  message.value = ''
  try {
    const result = await generateSnapshotReport(props.pageUri)
    message.value = result.message
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '生成质量报告失败'
  } finally {
    busy.value = false
  }
}

onMounted(reload)
watch(() => [props.pageUri, props.refreshKey], reload)
</script>

<style scoped>
.snapshot-diff {
  margin-top: 20px;
  padding: 16px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.diff-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.diff-title { margin: 12px 0 8px; font-size: 14px; }
.diff-sub { color: var(--muted); font-size: 12px; margin: 4px 0; }
.diff-actions { display: flex; gap: 8px; }
.diff-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.diff-list { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.8; }
.diff-note { display: block; color: var(--muted); font-size: 11px; }
.hash { font-family: monospace; font-size: 12px; max-width: 140px; overflow: hidden; text-overflow: ellipsis; }
.tag { display: inline-block; padding: 1px 6px; border-radius: 10px; font-size: 11px; background: #e2e8f0; color: #334155; }
.tag-当前报告 { background: #dbeafe; color: #1d4ed8; }
.tag-迟到快照 { background: #fef3c7; color: #b45309; }
.tag-未引用 { background: #e2e8f0; color: #475569; }
.tag-conflict { background: #fee2e2; color: #b42318; margin-left: 4px; }
.tag-有效, .tag-通过 { background: #dcfce7; color: #15803d; }
.tag-需复核 { background: #fef3c7; color: #b45309; }
.tag-缺证据 { background: #fee2e2; color: #b42318; }
.row-conflict { background: #fff7ed; }
.diff-report { margin-top: 16px; border-top: 1px solid var(--border); padding-top: 8px; }
</style>
