<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1 class="page-title">定时分析</h1>
        <p class="page-desc">
          把常用问题存成定时任务，由调度器按固定间隔自动执行并记录每次运行结果（状态 / 重试次数 / 错误）。
        </p>
      </div>
      <div class="page-actions">
        <button
          class="btn btn-primary"
          type="button"
          :disabled="!canWrite"
          :title="canWrite ? '新建定时任务' : readonlyHint"
          @click="openCreate"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="M7 2.5v9M2.5 7h9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
          新建任务
        </button>
      </div>
    </header>

    <div v-if="!canWrite" class="alert alert-info readonly-banner">
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="6.3" stroke="currentColor" stroke-width="1.1" />
        <path d="M8 7.2v4M8 4.9v.2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
      </svg>
      <div class="alert-body">
        <div class="alert-title">当前角色只读（{{ auth.roleLabel }}）</div>
        可以查看任务与运行历史，但新建、启停、立即执行和删除需要 <span class="mono">schedule:write</span> 权限。
      </div>
    </div>

    <div v-if="runNotice" class="alert alert-success run-notice">
      <div class="alert-body">
        <div class="alert-title">已触发「{{ runNotice.name }}」</div>
        运行记录 <span class="mono">{{ shortId(runNotice.runId) }}</span> · 状态 {{ statusLabel(runNotice.status) }}
        <template v-if="runNotice.taskId">· 任务 <span class="mono">{{ shortId(runNotice.taskId) }}</span></template>
      </div>
      <button class="alert-close" type="button" aria-label="关闭" @click="runNotice = null">✕</button>
    </div>

    <ErrorAlert
      v-if="pageError"
      class="page-alert"
      :error="pageError"
      title="无法加载定时任务"
      retryable
      @retry="load"
      @dismiss="pageError = null"
    />
    <ErrorAlert
      v-if="actionError"
      class="page-alert"
      :error="actionError"
      title="操作失败"
      @dismiss="actionError = null"
    />

    <section class="card">
      <div class="card-head">
        <span class="card-title">任务列表</span>
        <span class="card-sub">{{ schedules.length }} 个 · {{ enabledCount }} 个启用</span>
      </div>

      <div v-if="loading" class="skeleton-list">
        <div v-for="index in 4" :key="index" class="skeleton-row">
          <div class="skeleton skeleton-line" style="width: 28%"></div>
          <div class="skeleton skeleton-line" style="width: 12%"></div>
          <div class="skeleton skeleton-line" style="width: 14%"></div>
          <div class="skeleton skeleton-line" style="width: 20%"></div>
        </div>
      </div>

      <div v-else-if="!schedules.length" class="empty">
        <div class="empty-icon">
          <svg width="42" height="42" viewBox="0 0 44 44" fill="none">
            <circle cx="22" cy="22" r="15" stroke="currentColor" stroke-width="1.5" />
            <path d="M22 13v9.5l6 3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <h3>还没有定时任务</h3>
        <p>把「每天早上看一遍昨日销售额」这类问题存成任务，调度器会按间隔自动执行并留下运行历史。</p>
        <button v-if="canWrite" class="btn btn-primary" type="button" @click="openCreate">创建第一个任务</button>
        <span v-else class="hint">只读角色无法创建定时任务。</span>
      </div>

      <ul v-else class="schedule-list">
        <li v-for="schedule in schedules" :key="schedule.id" class="schedule-item">
          <div class="schedule-main">
            <div class="schedule-title-row">
              <span class="schedule-name truncate">{{ schedule.name }}</span>
              <span class="badge" :class="schedule.enabled ? 'badge-success' : ''">
                {{ schedule.enabled ? '运行中' : '已暂停' }}
              </span>
              <span v-if="schedule.last_status" class="badge" :class="statusBadge(schedule.last_status)">
                上次 {{ statusLabel(schedule.last_status) }}
              </span>
              <span v-if="schedule.consecutive_failures > 0" class="badge badge-danger">
                连续失败 {{ schedule.consecutive_failures }} 次
              </span>
            </div>
            <p class="schedule-question">{{ schedule.question }}</p>
            <div class="schedule-meta">
              <span class="meta-chip mono">{{ formatInterval(schedule.interval_minutes) }}</span>
              <span class="meta-chip">上次 {{ schedule.last_run_at ? formatRelative(schedule.last_run_at) : '未运行' }}</span>
              <span class="meta-chip">下次 {{ schedule.next_run_at ? formatDate(schedule.next_run_at) : '—' }}</span>
            </div>
            <p v-if="schedule.last_error" class="schedule-error">{{ schedule.last_error }}</p>
          </div>

          <div class="schedule-actions">
            <button
              class="btn btn-sm btn-secondary"
              type="button"
              :disabled="!canWrite || runningId === schedule.id"
              :title="canWrite ? '立即触发一次执行' : readonlyHint"
              @click="runNow(schedule)"
            >
              <span v-if="runningId === schedule.id" class="spinner"></span>
              立即执行
            </button>
            <button
              class="btn btn-sm btn-ghost"
              type="button"
              :disabled="!canWrite || togglingId === schedule.id"
              :title="canWrite ? (schedule.enabled ? '暂停任务' : '启用任务') : readonlyHint"
              @click="toggle(schedule)"
            >
              {{ schedule.enabled ? '暂停' : '启用' }}
            </button>
            <button class="btn btn-sm btn-ghost" type="button" @click="openHistory(schedule)">
              运行历史
            </button>
            <button
              class="btn btn-sm btn-ghost danger-text"
              type="button"
              :disabled="!canWrite"
              :title="canWrite ? '删除任务' : readonlyHint"
              @click="askDelete(schedule)"
            >
              删除
            </button>
          </div>
        </li>
      </ul>
    </section>

    <!-- ---------------------------------------------------------------- 新建任务 -->
    <BaseModal
      :open="createOpen"
      title="新建定时任务"
      subtitle="任务会由调度器按固定间隔执行，最短间隔 5 分钟。"
      size="md"
      @close="createOpen = false"
    >
      <div class="form-body">
        <label class="field">
          <span class="label">任务名称</span>
          <input v-model="formName" class="input" type="text" placeholder="例如：每日销售概览" />
        </label>

        <label class="field">
          <span class="label">分析问题</span>
          <textarea
            v-model="formQuestion"
            class="textarea"
            rows="3"
            placeholder="例如：昨天各城市的销售额排名，并指出环比下降的城市"
          ></textarea>
          <span class="hint">问题会原样交给分析 Agent，建议写清时间范围与维度。</span>
        </label>

        <div class="form-grid">
          <label class="field">
            <span class="label">执行间隔</span>
            <select v-model.number="formInterval" class="select">
              <option v-for="preset in intervalPresets" :key="preset.value" :value="preset.value">
                {{ preset.label }}
              </option>
            </select>
          </label>
          <label class="field checkbox-field">
            <span class="label">创建后立即启用</span>
            <label class="checkbox-row">
              <input v-model="formEnabled" type="checkbox" />
              <span>{{ formEnabled ? '启用' : '暂停' }}</span>
            </label>
          </label>
        </div>

        <ErrorAlert v-if="formError" :error="formError" title="创建失败" @dismiss="formError = null" />
      </div>

      <template #footer>
        <button class="btn btn-ghost" type="button" @click="createOpen = false">取消</button>
        <button class="btn btn-primary" type="button" :disabled="creating" @click="submitCreate">
          <span v-if="creating" class="spinner"></span>
          创建任务
        </button>
      </template>
    </BaseModal>

    <!-- ---------------------------------------------------------------- 删除 -->
    <BaseModal
      :open="Boolean(deleteTarget)"
      title="删除定时任务"
      size="sm"
      :close-on-mask="!deleting"
      @close="deleteTarget = null"
    >
      <p class="confirm-text">
        确定删除任务「<strong>{{ deleteTarget?.name }}</strong>」吗？
      </p>
      <p class="hint">删除后不再执行，历史运行记录也会一并移除。</p>
      <ErrorAlert v-if="deleteError" :error="deleteError" title="删除失败" @dismiss="deleteError = null" />
      <template #footer>
        <button class="btn btn-ghost" type="button" :disabled="deleting" @click="deleteTarget = null">取消</button>
        <button class="btn btn-danger" type="button" :disabled="deleting" @click="confirmDelete">
          <span v-if="deleting" class="spinner"></span>
          确认删除
        </button>
      </template>
    </BaseModal>

    <!-- ---------------------------------------------------------------- 运行历史 -->
    <BaseModal
      :open="historyOpen"
      :title="`运行历史 · ${historySchedule?.name ?? ''}`"
      subtitle="最近 20 次调度记录，包含状态、尝试次数与错误信息。"
      size="lg"
      scroll-body
      @close="historyOpen = false"
    >
      <div v-if="runsLoading" class="skeleton-list">
        <div v-for="index in 3" :key="index" class="skeleton skeleton-line" style="width: 100%"></div>
      </div>

      <ErrorAlert
        v-else-if="runsError"
        :error="runsError"
        title="无法加载运行历史"
        retryable
        @retry="reloadHistory"
        @dismiss="runsError = null"
      />

      <div v-else-if="!runs.length" class="empty">
        <h3>还没有运行记录</h3>
        <p>点击「立即执行」触发一次，或等待调度器到点自动执行。</p>
      </div>

      <div v-else class="table-scroll">
        <table class="data-table runs-table">
          <thead>
            <tr>
              <th>计划时间</th>
              <th>状态</th>
              <th class="num">尝试次数</th>
              <th>完成时间</th>
              <th>错误</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in runs" :key="run.id">
              <td class="mono">{{ formatDate(run.scheduled_for) }}</td>
              <td>
                <span class="badge" :class="statusBadge(run.status)">{{ statusLabel(run.status) }}</span>
              </td>
              <td class="num mono">{{ run.attempts }}</td>
              <td class="mono muted">{{ run.finished_at ? formatDate(run.finished_at) : '—' }}</td>
              <td class="run-error">{{ run.error || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <template #footer>
        <button class="btn btn-secondary" type="button" :disabled="runsLoading" @click="reloadHistory">
          刷新
        </button>
        <button class="btn btn-primary" type="button" @click="historyOpen = false">关闭</button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { ApiError, scheduleApi, toApiError } from '../api/client'
import type { Schedule, ScheduleRun } from '../api/types'
import BaseModal from '../components/ui/BaseModal.vue'
import ErrorAlert from '../components/ui/ErrorAlert.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const canWrite = computed(() => auth.has('schedule:write'))
const readonlyHint = '当前角色只读（缺少 schedule:write 权限）'

const schedules = ref<Schedule[]>([])
const loading = ref(true)
const pageError = ref<ApiError | null>(null)
const actionError = ref<ApiError | null>(null)
const enabledCount = computed(() => schedules.value.filter((item) => item.enabled).length)

// 新建
const createOpen = ref(false)
const formName = ref('')
const formQuestion = ref('')
const formInterval = ref(1440)
const formEnabled = ref(true)
const creating = ref(false)
const formError = ref<ApiError | null>(null)

const intervalPresets = [
  { value: 30, label: '每 30 分钟' },
  { value: 60, label: '每 1 小时' },
  { value: 360, label: '每 6 小时' },
  { value: 720, label: '每 12 小时' },
  { value: 1440, label: '每天一次' },
  { value: 10080, label: '每周一次' },
]

// 行内操作
const runningId = ref('')
const togglingId = ref('')
const runNotice = ref<{ name: string; runId: string; taskId: string; status: string } | null>(null)

// 删除
const deleteTarget = ref<Schedule | null>(null)
const deleting = ref(false)
const deleteError = ref<ApiError | null>(null)

// 历史
const historyOpen = ref(false)
const historySchedule = ref<Schedule | null>(null)
const runs = ref<ScheduleRun[]>([])
const runsLoading = ref(false)
const runsError = ref<ApiError | null>(null)

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  loading.value = true
  pageError.value = null
  try {
    schedules.value = await scheduleApi.list()
  } catch (caught) {
    pageError.value = toApiError(caught)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  if (!canWrite.value) return
  formName.value = ''
  formQuestion.value = ''
  formInterval.value = 1440
  formEnabled.value = true
  formError.value = null
  createOpen.value = true
}

async function submitCreate(): Promise<void> {
  if (creating.value) return
  if (!formName.value.trim()) {
    formError.value = new ApiError('请填写任务名称', { code: 'invalid_form' })
    return
  }
  if (formQuestion.value.trim().length < 2) {
    formError.value = new ApiError('分析问题至少 2 个字', { code: 'invalid_form' })
    return
  }
  creating.value = true
  formError.value = null
  try {
    const created = await scheduleApi.create({
      name: formName.value.trim(),
      question: formQuestion.value.trim(),
      interval_minutes: formInterval.value,
      enabled: formEnabled.value,
    })
    schedules.value = [created, ...schedules.value]
    createOpen.value = false
  } catch (caught) {
    formError.value = toApiError(caught)
  } finally {
    creating.value = false
  }
}

async function toggle(schedule: Schedule): Promise<void> {
  if (!canWrite.value || togglingId.value) return
  togglingId.value = schedule.id
  actionError.value = null
  const previous = schedule.enabled
  schedule.enabled = !previous
  try {
    const updated = await scheduleApi.update(schedule.id, { enabled: !previous })
    const index = schedules.value.findIndex((item) => item.id === schedule.id)
    if (index >= 0) schedules.value[index] = updated
  } catch (caught) {
    schedule.enabled = previous
    actionError.value = toApiError(caught)
  } finally {
    togglingId.value = ''
  }
}

async function runNow(schedule: Schedule): Promise<void> {
  if (!canWrite.value || runningId.value) return
  runningId.value = schedule.id
  actionError.value = null
  try {
    const result = await scheduleApi.runNow(schedule.id)
    runNotice.value = {
      name: schedule.name,
      runId: result.run_id,
      taskId: result.task_id,
      status: result.status,
    }
    await load()
    if (historyOpen.value && historySchedule.value?.id === schedule.id) await reloadHistory()
  } catch (caught) {
    actionError.value = toApiError(caught)
  } finally {
    runningId.value = ''
  }
}

function askDelete(schedule: Schedule): void {
  if (!canWrite.value) return
  deleteTarget.value = schedule
  deleteError.value = null
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  deleteError.value = null
  try {
    await scheduleApi.remove(target.id)
    schedules.value = schedules.value.filter((item) => item.id !== target.id)
    deleteTarget.value = null
    if (historySchedule.value?.id === target.id) historyOpen.value = false
  } catch (caught) {
    deleteError.value = toApiError(caught)
  } finally {
    deleting.value = false
  }
}

async function openHistory(schedule: Schedule): Promise<void> {
  historySchedule.value = schedule
  historyOpen.value = true
  runs.value = []
  runsError.value = null
  await loadRuns(schedule.id)
}

async function loadRuns(scheduleId: string): Promise<void> {
  runsLoading.value = true
  runsError.value = null
  try {
    runs.value = await scheduleApi.runs(scheduleId)
  } catch (caught) {
    runsError.value = toApiError(caught)
  } finally {
    runsLoading.value = false
  }
}

async function reloadHistory(): Promise<void> {
  const schedule = historySchedule.value
  if (!schedule) return
  await loadRuns(schedule.id)
}

// ---------------------------------------------------------------- 格式化
function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    pending: '待执行',
    running: '执行中',
    succeeded: '成功',
    success: '成功',
    failed: '失败',
    retrying: '重试中',
  }
  return labels[status] ?? status
}

function statusBadge(status: string): string {
  if (status === 'succeeded' || status === 'success') return 'badge-success'
  if (status === 'failed') return 'badge-danger'
  if (status === 'running' || status === 'retrying') return 'badge-warn'
  return ''
}

function formatInterval(minutes: number): string {
  if (minutes % 1440 === 0) return `每 ${minutes / 1440} 天`
  if (minutes % 60 === 0) return `每 ${minutes / 60} 小时`
  return `每 ${minutes} 分钟`
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  const normalized = iso.includes('T') && !/[Z+-]\d/.test(iso.slice(10)) ? `${iso}Z` : iso
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (input: number): string => String(input).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatRelative(iso: string): string {
  const normalized = iso.includes('T') && !/[Z+-]\d/.test(iso.slice(10)) ? `${iso}Z` : iso
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return iso
  const diff = Date.now() - date.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return `${Math.floor(diff / 86_400_000)} 天前`
}

function shortId(id: string): string {
  return id ? id.slice(0, 8) : '—'
}
</script>

<style scoped>
.readonly-banner,
.page-alert,
.run-notice {
  margin-bottom: 16px;
}

.run-notice {
  align-items: flex-start;
}

.skeleton-list {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.skeleton-row {
  display: flex;
  gap: 24px;
}

.skeleton-row .skeleton-line {
  margin: 0;
}

.schedule-list {
  list-style: none;
  display: flex;
  flex-direction: column;
}

.schedule-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--border);
  transition: background var(--dur-1);
}

.schedule-item:last-child {
  border-bottom: none;
}

.schedule-item:hover {
  background: rgba(255, 255, 255, 0.018);
}

.schedule-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.schedule-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.schedule-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--fg-0);
  max-width: 360px;
}

.schedule-question {
  font-size: 12.5px;
  color: var(--fg-2);
  line-height: 1.65;
  max-width: 780px;
  word-break: break-word;
}

.schedule-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.meta-chip {
  font-size: 11px;
  color: var(--fg-3);
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 9px;
}

.schedule-error {
  font-size: 11.5px;
  color: var(--danger);
  line-height: 1.6;
  word-break: break-word;
}

.schedule-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
  flex-shrink: 0;
  max-width: 340px;
}

.danger-text {
  color: var(--danger);
}

.danger-text:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.1);
}

.form-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  align-items: end;
}

.checkbox-field {
  justify-content: flex-end;
}

.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--fg-2);
  cursor: pointer;
  padding: 8px 0;
}

.checkbox-row input {
  accent-color: var(--accent);
}

.confirm-text {
  font-size: 13.5px;
  color: var(--fg-1);
  margin-bottom: 8px;
}

.confirm-text strong {
  color: var(--fg-0);
}

.runs-table .run-error {
  font-size: 11.5px;
  color: var(--fg-2);
  max-width: 320px;
  word-break: break-word;
}

.num {
  text-align: right;
}

@media (max-width: 900px) {
  .schedule-item {
    flex-direction: column;
  }
  .schedule-actions {
    justify-content: flex-start;
    max-width: none;
  }
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
