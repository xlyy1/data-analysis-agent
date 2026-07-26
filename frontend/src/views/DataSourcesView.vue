<template>
  <div class="datasource-view">
    <div class="page-header">
      <div class="header-left">
        <h1>数据源</h1>
        <p class="page-desc">管理连接的数据库和上传的文件</p>
      </div>
      <button class="btn-primary" @click="showUpload = true">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M8 2.5v8m0-8l-2.5 2.5M8 2.5l2.5 2.5M3 11.5v1a1.5 1.5 0 001.5 1.5h7a1.5 1.5 0 001.5-1.5v-1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span>上传文件</span>
      </button>
    </div>

    <t-dialog v-model:visible="showUpload" header="上传数据文件" :footer="false" width="480px">
      <t-upload
        :action="'/api/datasources/upload'"
        :headers="{}"
        :accept="'.xlsx,.xls,.csv'"
        :max="1"
        theme="file-flow"
        @success="onUploadSuccess"
        @fail="onUploadFail"
      >
        <template #file-list-display>
          <div class="upload-hint">
            <div class="upload-icon">
              <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
                <rect x="6" y="6" width="24" height="24" rx="4" stroke="currentColor" stroke-width="1.5"/>
                <path d="M18 12v10M13 17l5-5 5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            <p class="upload-title">拖拽文件到此处或点击上传</p>
            <p class="upload-sub">支持 .xlsx / .xls / .csv 格式</p>
          </div>
        </template>
      </t-upload>
    </t-dialog>

    <div class="table-card">
      <div class="table-header">
        <span class="table-title">所有数据源</span>
        <span class="table-count">{{ datasources.length }} 个</span>
      </div>
      <t-table
        :data="datasources"
        :columns="columns"
        row-key="id"
        :loading="loading"
        class="ds-table"
      >
        <template #type="{ row }">
          <span class="type-badge" :class="typeClass(row.type)">{{ typeLabel(row.type) }}</span>
        </template>
        <template #actions="{ row }">
          <div class="row-actions">
            <button class="link-btn" @click="viewSchema(row.id)">查看 Schema</button>
            <t-popconfirm content="确定删除?" @confirm="deleteDs(row.id)">
              <button class="link-btn danger">删除</button>
            </t-popconfirm>
          </div>
        </template>
      </t-table>
    </div>

    <t-dialog v-model:visible="showSchema" header="数据表结构" width="640px" :footer="false">
      <div v-if="schemaLoading" class="schema-loading">加载中...</div>
      <div v-else-if="schema?.tables?.length" v-for="table in schema?.tables" :key="table.name" class="schema-block">
        <div class="schema-head">
          <h4>{{ table.name }}</h4>
          <span class="schema-count">{{ table.row_count }} 行</span>
        </div>
        <t-table :data="table.columns" :columns="schemaColumns" size="small" />
      </div>
      <div v-else class="schema-empty">暂无表结构数据</div>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api/client'

const datasources = ref<any[]>([])
const loading = ref(false)
const showUpload = ref(false)
const showSchema = ref(false)
const schema = ref<any>(null)
const schemaLoading = ref(false)

const columns = [
  { colKey: 'name', title: '名称', ellipsis: true },
  { colKey: 'type', title: '类型', width: 140 },
  { colKey: 'created_at', title: '创建时间', width: 200 },
  { colKey: 'actions', title: '操作', width: 180 },
]

const schemaColumns = [
  { colKey: 'name', title: '列名' },
  { colKey: 'dtype', title: '数据类型' },
]

function typeClass(type: string) {
  const map: Record<string, string> = { excel: 'type-success', csv: 'type-success', mysql: 'type-primary', postgres: 'type-warning', sqlite: 'type-default' }
  return map[type] || 'type-default'
}

function typeLabel(type: string) {
  const map: Record<string, string> = { excel: 'Excel', csv: 'CSV', mysql: 'MySQL', postgres: 'PostgreSQL', sqlite: 'SQLite' }
  return map[type] || type
}

onMounted(fetchDataSources)

async function fetchDataSources() {
  loading.value = true
  try {
    const res = await api.get('/datasources/')
    datasources.value = res.data
  } finally {
    loading.value = false
  }
}

function onUploadSuccess() {
  showUpload.value = false
  fetchDataSources()
}

function onUploadFail(err: any) {
  console.error('Upload failed:', err)
}

async function viewSchema(id: string) {
  schemaLoading.value = true
  showSchema.value = true
  try {
    const res = await api.get(`/datasources/${id}/schema`)
    schema.value = res.data
  } finally {
    schemaLoading.value = false
  }
}

async function deleteDs(id: string) {
  await api.delete(`/datasources/${id}`)
  fetchDataSources()
}
</script>

<style scoped>
.datasource-view {
  padding: 32px 48px;
  max-width: 1200px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 32px;
}

.header-left h1 {
  font-size: 24px;
  font-weight: 600;
  color: var(--fg-0);
  letter-spacing: -0.02em;
}

.page-desc {
  font-size: 14px;
  color: var(--fg-2);
  margin-top: 6px;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 18px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}

.btn-primary:hover {
  background: var(--accent-dim);
}

.btn-primary:active {
  transform: translateY(0);
}

.table-card {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.table-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg-1);
}

.table-count {
  font-size: 12px;
  color: var(--fg-3);
  font-family: var(--font-mono);
}

.type-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 500;
}

.type-success { background: rgba(74, 222, 128, 0.1); color: #4ADE80; }
.type-primary { background: var(--accent-hi); color: var(--accent); }
.type-warning { background: rgba(251, 191, 36, 0.1); color: var(--warning); }
.type-default { background: var(--bg-3); color: var(--fg-2); }

.row-actions {
  display: flex;
  gap: 2px;
}

.link-btn {
  background: transparent;
  border: none;
  color: var(--fg-3);
  font-size: 13px;
  font-family: var(--font-sans);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  transition: all var(--dur-1) var(--ease-out);
}

.link-btn:hover {
  background: var(--bg-3);
  color: var(--fg-1);
}

.link-btn.danger {
  color: var(--danger);
}

.link-btn.danger:hover {
  background: rgba(248, 113, 113, 0.08);
}

.upload-hint {
  text-align: center;
  padding: 40px 24px;
  color: var(--fg-2);
}

.upload-icon {
  display: flex;
  justify-content: center;
  color: var(--accent);
  margin-bottom: 16px;
}

.upload-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--fg-1);
  margin-bottom: 6px;
}

.upload-sub {
  font-size: 12px;
  color: var(--fg-3);
}

.schema-loading,
.schema-empty {
  text-align: center;
  padding: 40px;
  color: var(--fg-2);
  font-size: 13px;
}

.schema-block {
  margin-bottom: 24px;
}

.schema-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.schema-head h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg-0);
}

.schema-count {
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-3);
  font-size: 12px;
  color: var(--fg-2);
  font-family: var(--font-mono);
}

:deep(.t-table) {
  background: transparent !important;
}

:deep(.t-table__thead) {
  background: var(--bg-2) !important;
}

:deep(.t-table__th) {
  color: var(--fg-2) !important;
  font-weight: 600 !important;
  font-size: 13px !important;
  border-bottom: 1px solid var(--border) !important;
}

:deep(.t-table__td) {
  color: var(--fg-1) !important;
  border-bottom: 1px solid var(--border) !important;
}

:deep(.t-table__row:hover td) {
  background: var(--bg-3) !important;
}

:deep(.t-dialog) {
  background: var(--bg-1) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
}

:deep(.t-dialog__header) {
  border-bottom: 1px solid var(--border) !important;
  color: var(--fg-0) !important;
}

:deep(.t-dialog__body) {
  padding: 24px !important;
}
</style>
