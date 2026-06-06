<template>
  <div class="datasource-view">
    <div class="page-header">
      <h2>数据源管理</h2>
      <t-button theme="primary" @click="showUpload = true">
        <t-icon name="upload" /> 上传文件
      </t-button>
    </div>

    <!-- 上传对话框 -->
    <t-dialog
      v-model:visible="showUpload"
      header="上传数据文件"
      :footer="false"
      width="480px"
    >
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
          <div class="upload-tip">
            <p>支持 .xlsx / .xls / .csv 格式</p>
            <p class="tip-sub">文件将自动解析表头与数据类型</p>
          </div>
        </template>
      </t-upload>
    </t-dialog>

    <!-- 数据源列表 -->
    <t-table
      :data="datasources"
      :columns="columns"
      row-key="id"
      hover
      stripe
      :loading="loading"
      class="ds-table"
    >
      <template #type="{ row }">
        <t-tag :theme="typeTheme(row.type)" variant="light" size="small">
          {{ typeLabel(row.type) }}
        </t-tag>
      </template>
      <template #actions="{ row }">
        <t-space>
          <t-button variant="text" size="small" @click="viewSchema(row.id)">
            查看 Schema
          </t-button>
          <t-popconfirm content="确定删除？" @confirm="deleteDs(row.id)">
            <t-button variant="text" size="small" theme="danger">删除</t-button>
          </t-popconfirm>
        </t-space>
      </template>
    </t-table>

    <!-- Schema 对话框 -->
    <t-dialog
      v-model:visible="showSchema"
      header="数据表结构"
      width="600px"
      :footer="false"
    >
      <div v-if="schemaLoading" class="schema-loading">加载中...</div>
      <div v-else v-for="table in schema?.tables" :key="table.name" class="schema-table">
        <h4>{{ table.name }} <t-tag size="small">{{ table.row_count }} 行</t-tag></h4>
        <t-table
          :data="table.columns"
          :columns="schemaColumns"
          size="small"
        />
      </div>
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
  { colKey: 'type', title: '类型', width: 100 },
  { colKey: 'created_at', title: '创建时间', width: 180 },
  { colKey: 'actions', title: '操作', width: 180 },
]

const schemaColumns = [
  { colKey: 'name', title: '列名' },
  { colKey: 'dtype', title: '数据类型' },
]

function typeTheme(type: string) {
  const map: Record<string, string> = { excel: 'success', csv: 'success', mysql: 'primary', postgres: 'warning', sqlite: 'default' }
  return map[type] || 'default'
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
  padding: 24px 32px;
  max-width: 1000px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.page-header h2 {
  font-size: 20px;
  font-weight: 600;
}

.upload-tip {
  text-align: center;
  padding: 20px;
  color: var(--text-secondary);
}

.tip-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.ds-table {
  margin-top: 8px;
}

.schema-loading {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
}

.schema-table {
  margin-bottom: 20px;
}

.schema-table h4 {
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
