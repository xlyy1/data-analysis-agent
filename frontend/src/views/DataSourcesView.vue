<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1 class="page-title">数据源</h1>
        <p class="page-desc">
          上传 Excel / CSV，或连接 SQLite / MySQL / PostgreSQL。上传后会立刻给出清洗报告与数据质量画像（空值率、重复、PII）。
        </p>
      </div>
      <div class="page-actions">
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="!canWrite"
          :title="canWrite ? '新建数据库连接' : readonlyHint"
          @click="openCreate"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="M7 2.5v9M2.5 7h9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
          新建连接
        </button>
        <button
          class="btn btn-primary"
          type="button"
          :disabled="!canWrite"
          :title="canWrite ? '上传 Excel / CSV' : readonlyHint"
          @click="openUpload"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M8 2.5v8m0-8l-2.6 2.6M8 2.5l2.6 2.6M3 11.5v1A1.5 1.5 0 004.5 14h7a1.5 1.5 0 001.5-1.5v-1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          上传文件
        </button>
      </div>
    </header>

    <div v-if="!canWrite" class="alert alert-info readonly-banner">
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="6.3" stroke="currentColor" stroke-width="1.1" />
        <path d="M8 7.2v4M8 4.9v.2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
      </svg>
      <div class="alert-body">
        <div class="alert-title">当前角色为只读（{{ auth.roleLabel }}）</div>
        你可以查看数据源、表结构与数据质量画像，但新增、编辑、刷新和删除需要 <span class="mono">datasource:write</span> 权限（admin / analyst）。
      </div>
    </div>

    <ErrorAlert
      v-if="pageError"
      class="page-alert"
      :error="pageError"
      title="无法加载数据源"
      retryable
      @retry="load()"
      @dismiss="pageError = null"
    />

    <section class="card">
      <div class="card-head">
        <span class="card-title">所有数据源</span>
        <span class="card-sub">{{ items.length }} 个 · 共 {{ formatNumber(totalRows) }} 行</span>
      </div>

      <div v-if="loading" class="skeleton-table">
        <div v-for="index in 4" :key="index" class="skeleton-row">
          <div class="skeleton skeleton-line" style="width: 26%"></div>
          <div class="skeleton skeleton-line" style="width: 12%"></div>
          <div class="skeleton skeleton-line" style="width: 8%"></div>
          <div class="skeleton skeleton-line" style="width: 8%"></div>
          <div class="skeleton skeleton-line" style="width: 16%"></div>
          <div class="skeleton skeleton-line" style="width: 18%"></div>
        </div>
      </div>

      <div v-else-if="!items.length" class="empty">
        <div class="empty-icon">
          <svg width="42" height="42" viewBox="0 0 44 44" fill="none">
            <ellipse cx="22" cy="11" rx="14" ry="4.6" stroke="currentColor" stroke-width="1.5" />
            <path d="M8 11v10c0 2.5 6.3 4.6 14 4.6s14-2.1 14-4.6V11" stroke="currentColor" stroke-width="1.5" />
            <path d="M8 21v10c0 2.5 6.3 4.6 14 4.6s14-2.1 14-4.6V21" stroke="currentColor" stroke-width="1.5" />
          </svg>
        </div>
        <h3>还没有数据源</h3>
        <p>上传一份 Excel / CSV，或连接已有数据库。上传后会自动完成清洗、列类型推断与数据质量画像。</p>
        <button v-if="canWrite" class="btn btn-primary" type="button" @click="openUpload">上传第一份数据</button>
        <span v-else class="hint">只读角色无法创建数据源，请联系管理员。</span>
      </div>

      <div v-else class="table-scroll">
        <table class="data-table ds-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th class="num">表数</th>
              <th class="num">行数</th>
              <th>创建时间</th>
              <th class="actions-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ds in items" :key="ds.id">
              <td>
                <button class="name-cell" type="button" @click="openDetail(ds)">
                  <span class="ds-dot" :class="`dot-${ds.type}`"></span>
                  <span class="name-text">
                    <span class="name-title truncate">{{ ds.name }}</span>
                    <span class="name-sub">
                      <span v-if="ds.seeded" class="badge badge-accent">样例</span>
                      <span v-if="ds.config.table" class="mono">{{ ds.config.table }}</span>
                    </span>
                  </span>
                </button>
              </td>
              <td><span class="badge" :class="typeBadge(ds.type)">{{ typeLabel(ds.type) }}</span></td>
              <td class="num mono">{{ ds.table_count }}</td>
              <td class="num mono">{{ formatNumber(ds.row_count) }}</td>
              <td class="muted mono">{{ formatDate(ds.created_at) }}</td>
              <td>
                <div class="row-actions">
                  <button class="btn btn-sm btn-ghost" type="button" @click="openDetail(ds)">详情</button>
                  <button
                    class="btn btn-sm btn-ghost"
                    type="button"
                    :disabled="!canWrite || refreshingId === ds.id"
                    :title="canWrite ? '重新读取表结构与画像' : readonlyHint"
                    @click="refreshSchema(ds)"
                  >
                    <span v-if="refreshingId === ds.id" class="spinner"></span>
                    刷新
                  </button>
                  <button
                    class="btn btn-sm btn-ghost"
                    type="button"
                    :disabled="!canWrite"
                    :title="canWrite ? '编辑名称 / 连接配置' : readonlyHint"
                    @click="openEdit(ds)"
                  >
                    编辑
                  </button>
                  <button
                    class="btn btn-sm btn-ghost danger-text"
                    type="button"
                    :disabled="!canWrite"
                    :title="canWrite ? '删除数据源' : readonlyHint"
                    @click="askDelete(ds)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ---------------------------------------------------------------- 上传 -->
    <BaseModal
      :open="uploadOpen"
      title="上传数据文件"
      subtitle="支持 .xlsx / .xls / .csv；解析后会先清洗再入库，并给出清洗报告。"
      size="md"
      @close="closeUpload"
    >
      <div v-if="!uploadResult" class="upload-body">
        <div
          class="drop-zone"
          :class="{ active: dragActive, filled: Boolean(uploadFile) }"
          @click="fileInput?.click()"
          @dragover.prevent="dragActive = true"
          @dragleave.prevent="dragActive = false"
          @drop.prevent="onDrop"
        >
          <div class="drop-icon">
            <svg width="34" height="34" viewBox="0 0 36 36" fill="none">
              <rect x="6" y="6" width="24" height="24" rx="4" stroke="currentColor" stroke-width="1.5" />
              <path d="M18 12v10M13 17l5-5 5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <p class="drop-title">{{ uploadFile ? uploadFile.name : '拖拽文件到此处，或点击选择' }}</p>
          <p class="drop-sub">
            {{ uploadFile ? `${formatBytes(uploadFile.size)} · 点击可重新选择` : '支持 .xlsx / .xls / .csv' }}
          </p>
          <input ref="fileInput" class="hidden-input" type="file" accept=".xlsx,.xls,.csv" @change="onFileChange" />
        </div>

        <label class="append-row">
          <input v-model="uploadAppend" type="checkbox" />
          <span>增量追加（append=true）</span>
          <span class="hint">表已存在时按行哈希去重后追加，而不是整表覆盖</span>
        </label>

        <ErrorAlert v-if="uploadError" :error="uploadError" title="上传失败" @dismiss="uploadError = null" />
      </div>

      <div v-else class="upload-result">
        <div class="alert alert-success">
          <div class="alert-body">
            <div class="alert-title">上传成功，已建为数据源「{{ uploadResult.name }}」</div>
            表名 <span class="mono">{{ uploadResult.ingest.table }}</span> · 列表页刷新后可见
          </div>
        </div>

        <div class="clean-grid">
          <div class="clean-stat">
            <span class="clean-label">读取行数</span>
            <span class="clean-value mono">{{ formatNumber(uploadResult.ingest.rows_in) }}</span>
          </div>
          <div class="clean-stat">
            <span class="clean-label">写入行数</span>
            <span class="clean-value mono accent">{{ formatNumber(uploadResult.ingest.rows_written) }}</span>
          </div>
          <div class="clean-stat">
            <span class="clean-label">丢弃空行</span>
            <span class="clean-value mono">{{ formatNumber(uploadResult.ingest.dropped_blank) }}</span>
          </div>
          <div class="clean-stat">
            <span class="clean-label">丢弃重复行</span>
            <span class="clean-value mono">{{ formatNumber(uploadResult.ingest.dropped_duplicate) }}</span>
          </div>
        </div>

        <div class="clean-meta">
          <span v-if="uploadResult.ingest.encoding" class="badge badge-mono">编码 {{ uploadResult.ingest.encoding }}</span>
          <span v-if="uploadResult.ingest.sheet" class="badge badge-mono">Sheet {{ uploadResult.ingest.sheet }}</span>
          <span class="badge">{{ uploadResult.ingest.columns.length }} 列</span>
        </div>

        <div v-if="uploadResult.ingest.notes.length" class="notes-block">
          <div class="notes-title">清洗备注</div>
          <ul>
            <li v-for="(note, index) in uploadResult.ingest.notes" :key="index">{{ note }}</li>
          </ul>
        </div>
      </div>

      <template #footer>
        <template v-if="!uploadResult">
          <button class="btn btn-ghost" type="button" @click="closeUpload">取消</button>
          <button class="btn btn-primary" type="button" :disabled="!uploadFile || uploading" @click="submitUpload">
            <span v-if="uploading" class="spinner"></span>
            {{ uploading ? '解析并入库…' : '开始上传' }}
          </button>
        </template>
        <button v-else class="btn btn-primary" type="button" @click="closeUpload">完成</button>
      </template>
    </BaseModal>

    <!-- ---------------------------------------------------------------- 新建 / 编辑连接 -->
    <BaseModal
      :open="formOpen"
      :title="formMode === 'create' ? '新建数据库连接' : `编辑「${formName || '数据源'}」`"
      subtitle="连接信息只用于后端建连；密码不会回显到前端。"
      size="md"
      @close="formOpen = false"
    >
      <div class="form-body">
        <label class="field">
          <span class="label">名称</span>
          <input v-model="formName" class="input" type="text" placeholder="例如：生产库只读副本" />
        </label>

        <div v-if="editingFileSource" class="alert alert-info">
          <div class="alert-body">
            文件类数据源（{{ editingSummary ? typeLabel(editingSummary.type) : '文件' }}）只能修改名称。
            <template v-if="editingSummary?.config.file_name">
              原文件 <span class="mono">{{ editingSummary.config.file_name }}</span>。
            </template>
            如需换文件请重新上传。
          </div>
        </div>

        <template v-else>
          <label class="field">
            <span class="label">类型</span>
            <select v-model="formType" class="select" :disabled="formMode === 'edit'">
              <option value="sqlite">SQLite 文件</option>
              <option value="mysql">MySQL</option>
              <option value="postgres">PostgreSQL</option>
            </select>
            <span v-if="formMode === 'edit'" class="hint">类型创建后不可修改，如需换库请新建数据源。</span>
          </label>

          <template v-if="formType === 'sqlite'">
            <label class="field">
              <span class="label">文件路径（后端可访问的绝对路径）</span>
              <input v-model="formConfig.db_path" class="input mono" type="text" placeholder="D:\\data\\sample.db" />
              <span class="hint">路径必须存在于 API 所在机器上，否则保存时会返回「SQLite 文件不存在」。</span>
            </label>
          </template>

          <template v-else>
            <div class="form-grid">
              <label class="field span-2">
                <span class="label">主机</span>
                <input v-model="formConfig.host" class="input mono" type="text" placeholder="127.0.0.1" />
              </label>
              <label class="field">
                <span class="label">端口</span>
                <input v-model="formConfig.port" class="input mono" type="number" min="1" max="65535" />
              </label>
              <label class="field">
                <span class="label">数据库名</span>
                <input v-model="formConfig.database" class="input mono" type="text" placeholder="analytics" />
              </label>
              <label class="field">
                <span class="label">用户名</span>
                <input v-model="formConfig.user" class="input mono" type="text" autocomplete="off" />
              </label>
              <label class="field">
                <span class="label">密码</span>
                <input
                  v-model="formConfig.password"
                  class="input mono"
                  type="password"
                  autocomplete="new-password"
                  :placeholder="formMode === 'edit' ? '留空表示不修改' : ''"
                />
              </label>
            </div>
          </template>

          <div class="test-row">
            <button class="btn btn-secondary" type="button" :disabled="testing" @click="runTest">
              <span v-if="testing" class="spinner"></span>
              测试连接
            </button>
            <span class="hint">不会写入数据库，只建连并读取表名</span>
          </div>

          <div v-if="testResult" class="alert" :class="testResult.ok ? 'alert-success' : 'alert-error'">
            <div class="alert-body">
              <div class="alert-title">{{ testResult.ok ? '连接成功' : '连接失败' }}</div>
              <div>{{ testResult.message }}</div>
              <div v-if="testResult.detail" class="alert-meta">{{ testResult.detail }}</div>
              <div v-if="testResult.tables?.length" class="alert-meta">
                发现表：{{ testResult.tables?.map((t) => `${t.name}(${t.columns} 列)`).join('、') }}
              </div>
              <div v-if="testResult.latency_ms !== undefined" class="alert-meta">耗时 {{ testResult.latency_ms }} ms</div>
            </div>
          </div>
        </template>

        <ErrorAlert v-if="formError" :error="formError" title="保存失败" @dismiss="formError = null" />
      </div>

      <template #footer>
        <button class="btn btn-ghost" type="button" @click="formOpen = false">取消</button>
        <button class="btn btn-primary" type="button" :disabled="formSubmitting" @click="submitForm">
          <span v-if="formSubmitting" class="spinner"></span>
          {{ formMode === 'create' ? '创建并读取表结构' : '保存修改' }}
        </button>
      </template>
    </BaseModal>

    <!-- ---------------------------------------------------------------- 删除确认 -->
    <BaseModal
      :open="Boolean(deleteTarget)"
      title="删除数据源"
      size="sm"
      :close-on-mask="!deleting"
      @close="deleteTarget = null"
    >
      <p class="confirm-text">
        确定删除数据源「<strong>{{ deleteTarget?.name }}</strong>」吗？
      </p>
      <p class="hint">删除后该数据源不再出现在列表里，历史对话与报告不受影响。此操作不可撤销。</p>
      <ErrorAlert v-if="deleteError" :error="deleteError" title="删除失败" @dismiss="deleteError = null" />

      <template #footer>
        <button class="btn btn-ghost" type="button" :disabled="deleting" @click="deleteTarget = null">取消</button>
        <button class="btn btn-danger" type="button" :disabled="deleting" @click="confirmDelete">
          <span v-if="deleting" class="spinner"></span>
          确认删除
        </button>
      </template>
    </BaseModal>

    <!-- ---------------------------------------------------------------- 详情抽屉 -->
    <Teleport to="body">
      <transition name="drawer">
        <div v-if="detailOpen" class="drawer-mask" @mousedown.self="closeDetail">
          <aside class="drawer">
            <header class="drawer-head">
              <div class="drawer-head-text">
                <div class="drawer-title-row">
                  <h3 class="drawer-title truncate">{{ detail?.name || '数据源详情' }}</h3>
                  <span v-if="detail" class="badge" :class="typeBadge(detail.type)">{{ typeLabel(detail.type) }}</span>
                  <span v-if="detail?.seeded" class="badge badge-accent">样例</span>
                </div>
                <p class="drawer-sub mono">{{ detail?.id || '' }}</p>
              </div>
              <div class="row">
                <button
                  v-if="detail && canWrite"
                  class="btn btn-sm btn-secondary"
                  type="button"
                  :disabled="refreshingDetail"
                  @click="refreshDetail"
                >
                  <span v-if="refreshingDetail" class="spinner"></span>
                  刷新 Schema / 画像
                </button>
                <button class="drawer-close" type="button" aria-label="关闭" @click="closeDetail">✕</button>
              </div>
            </header>

            <div v-if="detailLoading" class="drawer-body">
              <div class="skeleton skeleton-line" style="width: 40%; height: 14px"></div>
              <div class="skeleton skeleton-line" style="width: 88%"></div>
              <div class="skeleton skeleton-line" style="width: 72%"></div>
              <div class="skeleton" style="height: 120px; margin-top: 14px"></div>
            </div>

            <template v-else-if="detail">
              <nav class="drawer-tabs">
                <button
                  v-for="tab in tabs"
                  :key="tab.key"
                  class="drawer-tab"
                  :class="{ active: detailTab === tab.key }"
                  type="button"
                  @click="detailTab = tab.key"
                >
                  {{ tab.label }}
                  <span v-if="tab.key === 'quality' && detail.profile?.risk_count" class="tab-dot">
                    {{ detail.profile.risk_count }}
                  </span>
                </button>
              </nav>

              <div class="drawer-body">
                <ErrorAlert v-if="detailError" :error="detailError" title="加载详情失败" @dismiss="detailError = null" />

                <template v-if="detailTab === 'overview'">
                  <div class="meta-grid">
                    <div class="meta-item">
                      <span class="meta-label">表数量</span>
                      <span class="meta-value mono">{{ detail.table_count }}</span>
                    </div>
                    <div class="meta-item">
                      <span class="meta-label">总行数</span>
                      <span class="meta-value mono">{{ formatNumber(detail.row_count) }}</span>
                    </div>
                    <div class="meta-item">
                      <span class="meta-label">创建时间</span>
                      <span class="meta-value mono">{{ formatDate(detail.created_at) }}</span>
                    </div>
                    <div class="meta-item">
                      <span class="meta-label">状态</span>
                      <span class="meta-value">
                        <span class="badge" :class="detail.is_active ? 'badge-success' : 'badge-danger'">
                          {{ detail.is_active ? '可用' : '不可用' }}
                        </span>
                      </span>
                    </div>
                  </div>

                  <div class="section">
                    <h4 class="section-title">连接配置</h4>
                    <dl class="kv-list">
                      <template v-for="(value, key) in detail.config" :key="key">
                        <dt>{{ key }}</dt>
                        <dd class="mono">{{ formatConfigValue(value) }}</dd>
                      </template>
                    </dl>
                  </div>

                  <div v-if="detail.config.cleaning" class="section">
                    <h4 class="section-title">清洗报告</h4>
                    <div class="clean-grid compact">
                      <div class="clean-stat">
                        <span class="clean-label">读取</span>
                        <span class="clean-value mono">{{ formatNumber(detail.config.rows ?? 0) }}</span>
                      </div>
                      <div class="clean-stat">
                        <span class="clean-label">丢弃空行</span>
                        <span class="clean-value mono">{{ formatNumber(detail.config.cleaning?.dropped_blank ?? 0) }}</span>
                      </div>
                      <div class="clean-stat">
                        <span class="clean-label">丢弃重复</span>
                        <span class="clean-value mono">{{ formatNumber(detail.config.cleaning?.dropped_duplicate ?? 0) }}</span>
                      </div>
                    </div>
                    <ul v-if="detail.config.cleaning?.notes?.length" class="notes-list">
                      <li v-for="(note, index) in detail.config.cleaning?.notes ?? []" :key="index">{{ note }}</li>
                    </ul>
                  </div>
                </template>

                <template v-else-if="detailTab === 'schema'">
                  <div v-if="schemaTables.length" class="schema-list">
                    <div v-for="table in schemaTables" :key="table.name" class="schema-card">
                      <div class="schema-head">
                        <div class="row">
                          <h4 class="schema-name mono">{{ table.name }}</h4>
                          <span v-if="table.role" class="badge" :class="table.role === 'fact' ? 'badge-accent' : ''">
                            {{ table.role === 'fact' ? '事实表' : '维度表' }}
                          </span>
                        </div>
                        <span class="card-sub">{{ formatNumber(table.row_count) }} 行 · {{ table.columns.length }} 列</span>
                      </div>
                      <div class="table-scroll">
                        <table class="data-table compact">
                          <thead>
                            <tr>
                              <th>列名</th>
                              <th>类型</th>
                              <th>样本值</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr v-for="column in table.columns" :key="column.name">
                              <td class="mono">{{ column.name }}</td>
                              <td class="mono muted">{{ column.dtype }}</td>
                              <td class="samples">
                                <span v-if="column.sample_values?.length" class="sample-chips">
                                  <span v-for="(sample, index) in column.sample_values.slice(0, 5)" :key="index" class="chip">
                                    {{ String(sample) }}
                                  </span>
                                </span>
                                <span v-else class="muted">—</span>
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <div v-if="detail.schema?.relations?.length" class="section">
                      <h4 class="section-title">推断出的表关系</h4>
                      <ul class="relation-list">
                        <li v-for="(relation, index) in detail.schema.relations" :key="index">
                          <span class="mono">{{ relation.left }}</span>
                          <span class="muted">→</span>
                          <span class="mono">{{ relation.right }}</span>
                          <span class="badge">{{ relation.type }}</span>
                          <span class="badge" :class="relation.confidence === 'high' ? 'badge-success' : ''">
                            {{ relation.confidence }}
                          </span>
                        </li>
                      </ul>
                    </div>
                  </div>
                  <div v-else class="empty">
                    <h3>暂无表结构</h3>
                    <p>该数据源还没有读取过 Schema，点击右上角「刷新 Schema / 画像」重试。</p>
                  </div>
                </template>

                <template v-else>
                  <div v-if="detail.profile" class="quality">
                    <div class="meta-grid">
                      <div class="meta-item">
                        <span class="meta-label">已画像表</span>
                        <span class="meta-value mono">
                          {{ detail.profile.profiled_tables }} / {{ detail.profile.table_count }}
                        </span>
                      </div>
                      <div class="meta-item">
                        <span class="meta-label">总行数</span>
                        <span class="meta-value mono">{{ formatNumber(detail.profile.total_rows) }}</span>
                      </div>
                      <div class="meta-item">
                        <span class="meta-label">风险项</span>
                        <span class="meta-value mono" :class="{ 'risk-text': detail.profile.risk_count > 0 }">
                          {{ detail.profile.risk_count }}
                        </span>
                      </div>
                    </div>

                    <div v-if="detail.profile.truncated" class="alert alert-warn">
                      <div class="alert-body">表数量较多，仅对前 {{ detail.profile.profiled_tables }} 张表做了画像。</div>
                    </div>

                    <div v-for="table in profileTables" :key="table.table" class="schema-card">
                      <div class="schema-head">
                        <div class="row">
                          <h4 class="schema-name mono">{{ table.table }}</h4>
                          <span v-if="table.error" class="badge badge-danger">画像失败</span>
                          <span v-else-if="table.risks.length" class="badge badge-warn">{{ table.risks.length }} 项风险</span>
                          <span v-else class="badge badge-success">无风险</span>
                        </div>
                        <span class="card-sub">{{ formatNumber(table.row_count) }} 行 · {{ table.column_count }} 列</span>
                      </div>

                      <p v-if="table.error" class="table-error">{{ table.error }}</p>

                      <ul v-if="table.risks.length" class="risk-list">
                        <li v-for="(risk, index) in table.risks" :key="index">{{ risk }}</li>
                      </ul>

                      <div v-if="table.columns.length" class="table-scroll">
                        <table class="data-table compact">
                          <thead>
                            <tr>
                              <th>列名</th>
                              <th>类型</th>
                              <th class="num">缺失率</th>
                              <th class="num">唯一值</th>
                              <th>标记</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr v-for="column in table.columns" :key="column.name">
                              <td class="mono">{{ column.name }}</td>
                              <td class="mono muted">{{ column.dtype }}</td>
                              <td class="num">
                                <div class="null-bar">
                                  <div class="null-track">
                                    <div
                                      class="null-fill"
                                      :class="{ warn: column.null_rate >= 0.3, danger: column.null_rate >= 0.5 }"
                                      :style="{ width: `${Math.min(100, Math.round(column.null_rate * 100))}%` }"
                                    ></div>
                                  </div>
                                  <span class="mono null-value">{{ formatPercent(column.null_rate) }}</span>
                                </div>
                              </td>
                              <td class="num mono">{{ formatNumber(column.distinct_count) }}</td>
                              <td>
                                <span v-if="column.is_pii" class="badge badge-warn">PII · {{ piiLabel(column.pii_kind) }}</span>
                                <span v-else-if="column.is_unique" class="badge">唯一键</span>
                                <span v-else class="muted">—</span>
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                  <div v-else class="empty">
                    <h3>暂无数据质量画像</h3>
                    <p>点击右上角「刷新 Schema / 画像」生成每个表的空值率、重复与 PII 标记。</p>
                  </div>
                </template>
              </div>
            </template>

            <div v-else class="drawer-body">
              <ErrorAlert v-if="detailError" :error="detailError" title="加载详情失败" @dismiss="detailError = null" />
            </div>
          </aside>
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { ApiError, datasourceApi, toApiError } from '../api/client'
import type {
  DataSourceDetail,
  DataSourceSummary,
  TestConnectionResult,
  UploadResponse,
} from '../api/types'
import BaseModal from '../components/ui/BaseModal.vue'
import ErrorAlert from '../components/ui/ErrorAlert.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const canWrite = computed(() => auth.has('datasource:write'))
const readonlyHint = '当前角色只读（缺少 datasource:write 权限）'

const items = ref<DataSourceSummary[]>([])
const loading = ref(true)
const pageError = ref<ApiError | null>(null)
const refreshingId = ref('')

const totalRows = computed(() => items.value.reduce((sum, item) => sum + (item.row_count || 0), 0))

// ---------------------------------------------------------------- 上传
const uploadOpen = ref(false)
const uploadFile = ref<File | null>(null)
const uploadAppend = ref(false)
const uploading = ref(false)
const uploadError = ref<ApiError | null>(null)
const uploadResult = ref<UploadResponse | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const dragActive = ref(false)

// ---------------------------------------------------------------- 新建 / 编辑
const formOpen = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const formId = ref('')
const formName = ref('')
const formType = ref<'sqlite' | 'mysql' | 'postgres'>('sqlite')
const formSubmitting = ref(false)
const formError = ref<ApiError | null>(null)
const testing = ref(false)
const testResult = ref<TestConnectionResult | null>(null)
/** excel / csv 是文件类数据源：连接配置由上传流程写死，编辑时只允许改名 */
const editingFileSource = ref(false)
const editingSummary = ref<DataSourceSummary | null>(null)
const formConfig = reactive({
  db_path: '',
  host: '127.0.0.1',
  port: '3306',
  database: '',
  user: '',
  password: '',
})

// ---------------------------------------------------------------- 删除
const deleteTarget = ref<DataSourceSummary | null>(null)
const deleting = ref(false)
const deleteError = ref<ApiError | null>(null)

// ---------------------------------------------------------------- 详情抽屉
const detailOpen = ref(false)
const detailLoading = ref(false)
const detail = ref<DataSourceDetail | null>(null)
const detailError = ref<ApiError | null>(null)
const detailTab = ref<'overview' | 'schema' | 'quality'>('overview')
const refreshingDetail = ref(false)

const tabs = [
  { key: 'overview' as const, label: '概览' },
  { key: 'schema' as const, label: '表结构' },
  { key: 'quality' as const, label: '数据质量' },
]

const schemaTables = computed(() => detail.value?.schema?.tables ?? [])
const profileTables = computed(() => detail.value?.profile?.tables ?? [])

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  loading.value = true
  pageError.value = null
  try {
    items.value = await datasourceApi.list()
  } catch (caught) {
    pageError.value = toApiError(caught)
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------- 上传逻辑
function openUpload(): void {
  if (!canWrite.value) return
  uploadOpen.value = true
  uploadFile.value = null
  uploadAppend.value = false
  uploadError.value = null
  uploadResult.value = null
}

function closeUpload(): void {
  uploadOpen.value = false
  uploadFile.value = null
  uploadError.value = null
  const uploaded = uploadResult.value
  uploadResult.value = null
  dragActive.value = false
  if (uploaded) void load()
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  uploadFile.value = input.files?.[0] ?? null
  uploadError.value = null
}

function onDrop(event: DragEvent): void {
  dragActive.value = false
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  const name = file.name.toLowerCase()
  if (!/\.(xlsx|xls|csv)$/.test(name)) {
    uploadError.value = new ApiError('仅支持 .xlsx / .xls / .csv 文件', { code: 'invalid_file' })
    return
  }
  uploadFile.value = file
  uploadError.value = null
}

async function submitUpload(): Promise<void> {
  if (!uploadFile.value || uploading.value) return
  uploading.value = true
  uploadError.value = null
  try {
    uploadResult.value = await datasourceApi.upload(uploadFile.value, uploadAppend.value)
  } catch (caught) {
    uploadError.value = toApiError(caught)
  } finally {
    uploading.value = false
  }
}

// ---------------------------------------------------------------- 新建 / 编辑
function resetForm(): void {
  formName.value = ''
  formType.value = 'sqlite'
  formConfig.db_path = ''
  formConfig.host = '127.0.0.1'
  formConfig.port = '3306'
  formConfig.database = ''
  formConfig.user = ''
  formConfig.password = ''
  formError.value = null
  testResult.value = null
  editingFileSource.value = false
  editingSummary.value = null
}

function openCreate(): void {
  if (!canWrite.value) return
  resetForm()
  formMode.value = 'create'
  formId.value = ''
  formOpen.value = true
}

function openEdit(ds: DataSourceSummary): void {
  if (!canWrite.value) return
  resetForm()
  formMode.value = 'edit'
  formId.value = ds.id
  formName.value = ds.name
  editingSummary.value = ds
  editingFileSource.value = ds.type === 'excel' || ds.type === 'csv'
  if (ds.type === 'sqlite' || ds.type === 'mysql' || ds.type === 'postgres') {
    formType.value = ds.type
  }
  const config = ds.config
  formConfig.db_path = config.db_path ?? ''
  formConfig.host = config.host ?? '127.0.0.1'
  formConfig.port = config.port ? String(config.port) : formType.value === 'postgres' ? '5432' : '3306'
  formConfig.database = config.database ?? ''
  formConfig.user = config.user ?? ''
  formConfig.password = ''
  formOpen.value = true
}

function buildConfig(): Record<string, unknown> {
  if (formType.value === 'sqlite') {
    return { db_path: formConfig.db_path.trim() }
  }
  return {
    host: formConfig.host.trim(),
    port: Number(formConfig.port),
    user: formConfig.user.trim(),
    password: formConfig.password,
    database: formConfig.database.trim(),
  }
}

function validateForm(): string {
  if (!formName.value.trim()) return '请填写数据源名称'
  if (editingFileSource.value) return ''
  if (formType.value === 'sqlite' && !formConfig.db_path.trim()) return '请填写 SQLite 文件路径'
  if (formType.value !== 'sqlite') {
    if (!formConfig.host.trim()) return '请填写主机地址'
    if (!Number(formConfig.port)) return '请填写合法端口'
    if (!formConfig.user.trim()) return '请填写用户名'
    if (!formConfig.database.trim()) return '请填写数据库名'
    if (formMode.value === 'create' && !formConfig.password) return '请填写密码'
  }
  return ''
}

async function runTest(): Promise<void> {
  if (testing.value) return
  const reason = validateForm()
  if (reason) {
    formError.value = new ApiError(reason, { code: 'invalid_form' })
    return
  }
  testing.value = true
  formError.value = null
  testResult.value = null
  try {
    testResult.value = await datasourceApi.test({
      name: formName.value.trim(),
      type: formType.value,
      config: buildConfig(),
    })
  } catch (caught) {
    formError.value = toApiError(caught)
  } finally {
    testing.value = false
  }
}

async function submitForm(): Promise<void> {
  if (formSubmitting.value) return
  const reason = validateForm()
  if (reason) {
    formError.value = new ApiError(reason, { code: 'invalid_form' })
    return
  }
  formSubmitting.value = true
  formError.value = null
  try {
    if (formMode.value === 'create') {
      await datasourceApi.create({
        name: formName.value.trim(),
        type: formType.value,
        config: buildConfig(),
      })
    } else if (editingFileSource.value) {
      // 文件类数据源只改名称，不重发连接配置
      await datasourceApi.update(formId.value, { name: formName.value.trim() })
    } else {
      await datasourceApi.update(formId.value, {
        name: formName.value.trim(),
        config: buildConfig(),
      })
    }
    formOpen.value = false
    await load()
  } catch (caught) {
    formError.value = toApiError(caught)
  } finally {
    formSubmitting.value = false
  }
}

async function refreshSchema(ds: DataSourceSummary): Promise<void> {
  if (!canWrite.value || refreshingId.value) return
  refreshingId.value = ds.id
  pageError.value = null
  try {
    await datasourceApi.refreshSchema(ds.id)
    await load()
  } catch (caught) {
    pageError.value = toApiError(caught)
  } finally {
    refreshingId.value = ''
  }
}

// ---------------------------------------------------------------- 删除
function askDelete(ds: DataSourceSummary): void {
  if (!canWrite.value) return
  deleteTarget.value = ds
  deleteError.value = null
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  deleteError.value = null
  try {
    await datasourceApi.remove(target.id)
    deleteTarget.value = null
    if (detail.value?.id === target.id) closeDetail()
    await load()
  } catch (caught) {
    deleteError.value = toApiError(caught)
  } finally {
    deleting.value = false
  }
}

// ---------------------------------------------------------------- 详情
async function openDetail(ds: DataSourceSummary | DataSourceDetail): Promise<void> {
  detailOpen.value = true
  detailTab.value = 'overview'
  detail.value = null
  detailError.value = null
  detailLoading.value = true
  try {
    const loaded = await datasourceApi.get(ds.id)
    detail.value = loaded
    if (!loaded.profile) {
      // 画像可能是空（老数据源），只读权限也能补算
      try {
        const profile = await datasourceApi.profile(ds.id)
        if (detail.value?.id === loaded.id) detail.value = { ...loaded, profile }
      } catch {
        /* 画像失败不阻塞详情展示 */
      }
    }
  } catch (caught) {
    detailError.value = toApiError(caught)
  } finally {
    detailLoading.value = false
  }
}

function closeDetail(): void {
  detailOpen.value = false
  detail.value = null
  detailError.value = null
  detailTab.value = 'overview'
}

async function refreshDetail(): Promise<void> {
  const current = detail.value
  if (!current || refreshingDetail.value) return
  refreshingDetail.value = true
  detailError.value = null
  try {
    const result = await datasourceApi.refreshSchema(current.id)
    detail.value = { ...current, schema: result.schema, profile: result.profile }
    await load()
  } catch (caught) {
    detailError.value = toApiError(caught)
  } finally {
    refreshingDetail.value = false
  }
}

// ---------------------------------------------------------------- 格式化
function typeLabel(type: string): string {
  const labels: Record<string, string> = {
    sqlite: 'SQLite',
    mysql: 'MySQL',
    postgres: 'PostgreSQL',
    excel: 'Excel',
    csv: 'CSV',
  }
  return labels[type] ?? type
}

function typeBadge(type: string): string {
  if (type === 'mysql' || type === 'postgres') return 'badge-accent'
  if (type === 'excel' || type === 'csv') return 'badge-success'
  return ''
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value ?? 0)
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  const normalized = iso.includes('T') && !/[Z+-]\d/.test(iso.slice(10)) ? `${iso}Z` : iso
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (input: number): string => String(input).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatPercent(value: number): string {
  return `${(Math.max(0, Math.min(1, value ?? 0)) * 100).toFixed(1)}%`
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatConfigValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function piiLabel(kind: string): string {
  const labels: Record<string, string> = {
    phone: '手机号',
    email: '邮箱',
    id_card: '身份证',
    address: '地址',
    name: '姓名',
  }
  return labels[kind] ?? kind
}
</script>

<style scoped>
.page-alert {
  margin-bottom: 16px;
}

.readonly-banner {
  margin-bottom: 16px;
}

.page-title {
  font-size: 22px;
}

.ds-table .name-cell {
  display: flex;
  align-items: center;
  gap: 9px;
  border: none;
  background: transparent;
  color: inherit;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
  padding: 0;
  max-width: 340px;
}

.name-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.name-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--fg-0);
  max-width: 300px;
}

.name-cell:hover .name-title {
  color: var(--accent);
}

.name-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10.5px;
  color: var(--fg-4);
}

.ds-dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex-shrink: 0;
  background: var(--fg-4);
}

.dot-sqlite {
  background: #A1A1AA;
}
.dot-mysql {
  background: #6366F1;
}
.dot-postgres {
  background: #38BDF8;
}
.dot-excel,
.dot-csv {
  background: #4ADE80;
}

.num {
  text-align: right;
}

.actions-col {
  text-align: right;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
}

.danger-text {
  color: var(--danger);
}

.danger-text:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger);
}

.skeleton-table {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-row {
  display: flex;
  gap: 24px;
  align-items: center;
}

.skeleton-row .skeleton-line {
  margin: 0;
}

/* ---------------------------------------------------------------- 上传 */

.upload-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 34px 24px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  background: var(--bg-2);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
  text-align: center;
}

.drop-zone:hover,
.drop-zone.active {
  border-color: var(--border-accent);
  background: var(--accent-hi);
}

.drop-zone.filled {
  border-style: solid;
  border-color: var(--accent-line);
}

.drop-icon {
  color: var(--accent);
  margin-bottom: 6px;
}

.drop-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--fg-1);
  word-break: break-all;
}

.drop-sub {
  font-size: 11.5px;
  color: var(--fg-3);
}

.hidden-input {
  display: none;
}

.append-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--fg-2);
  cursor: pointer;
  flex-wrap: wrap;
}

.append-row input {
  accent-color: var(--accent);
}

.upload-result {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.clean-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.clean-grid.compact {
  grid-template-columns: repeat(3, 1fr);
}

.clean-stat {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 13px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-2);
}

.clean-label {
  font-size: 11px;
  color: var(--fg-3);
}

.clean-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--fg-0);
}

.clean-value.accent {
  color: var(--accent);
}

.clean-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.notes-block,
.notes-list {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-2);
  padding: 12px 14px;
  font-size: 12px;
}

.notes-title {
  font-weight: 600;
  color: var(--fg-2);
  margin-bottom: 6px;
  font-size: 12px;
}

.notes-block ul,
.notes-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: var(--fg-2);
  line-height: 1.6;
}

.notes-block li::before,
.notes-list li::before {
  content: '·';
  color: var(--accent);
  margin-right: 6px;
}

/* ---------------------------------------------------------------- 表单 */

.form-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.span-2 {
  grid-column: span 2;
}

.test-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 4px;
  border-top: 1px dashed var(--border);
  margin-top: 4px;
  padding-top: 12px;
}

.confirm-text {
  font-size: 13.5px;
  color: var(--fg-1);
  margin-bottom: 8px;
}

.confirm-text strong {
  color: var(--fg-0);
}

/* ---------------------------------------------------------------- 抽屉 */

.drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 900;
  background: rgba(5, 5, 7, 0.6);
  backdrop-filter: blur(3px);
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: min(760px, 92vw);
  height: 100vh;
  background: var(--bg-1);
  border-left: 1px solid var(--border-strong);
  display: flex;
  flex-direction: column;
  box-shadow: -24px 0 64px rgba(0, 0, 0, 0.5);
}

.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--border);
}

.drawer-head-text {
  min-width: 0;
}

.drawer-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.drawer-title {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--fg-0);
}

.drawer-sub {
  font-size: 10.5px;
  color: var(--fg-4);
  margin-top: 4px;
  word-break: break-all;
}

.drawer-close {
  border: none;
  background: transparent;
  color: var(--fg-3);
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
}

.drawer-close:hover {
  background: var(--bg-3);
  color: var(--fg-0);
}

.drawer-tabs {
  display: flex;
  gap: 2px;
  padding: 8px 18px 0;
  border-bottom: 1px solid var(--border);
}

.drawer-tab {
  position: relative;
  border: none;
  background: transparent;
  color: var(--fg-3);
  font-family: var(--font-sans);
  font-size: 13px;
  padding: 8px 12px 11px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: color var(--dur-1);
}

.drawer-tab:hover {
  color: var(--fg-1);
}

.drawer-tab.active {
  color: var(--fg-0);
}

.drawer-tab.active::after {
  content: '';
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: -1px;
  height: 2px;
  border-radius: 1px;
  background: var(--accent);
}

.tab-dot {
  font-family: var(--font-mono);
  font-size: 10px;
  background: rgba(251, 191, 36, 0.16);
  color: var(--warning);
  border-radius: 999px;
  padding: 0 5px;
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 12px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.meta-label {
  font-size: 11px;
  color: var(--fg-3);
}

.meta-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--fg-0);
}

.risk-text {
  color: var(--warning);
}

.section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--fg-2);
  letter-spacing: 0.01em;
}

.kv-list {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 7px 14px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-2);
  margin: 0;
  font-size: 12px;
}

.kv-list dt {
  color: var(--fg-3);
}

.kv-list dd {
  color: var(--fg-1);
  margin: 0;
  word-break: break-all;
}

.schema-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.schema-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg-2);
}

.schema-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  background: var(--bg-1);
  border-bottom: 1px solid var(--border);
}

.schema-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--fg-0);
}

.data-table.compact th,
.data-table.compact td {
  padding: 7px 12px;
  font-size: 12px;
}

.samples {
  max-width: 260px;
}

.sample-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chip {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-3);
  color: var(--fg-2);
  font-size: 10.5px;
  font-family: var(--font-mono);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.relation-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}

.relation-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-2);
}

.null-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
  min-width: 120px;
}

.null-track {
  width: 64px;
  height: 4px;
  border-radius: 2px;
  background: var(--bg-4);
  overflow: hidden;
}

.null-fill {
  height: 100%;
  background: var(--success);
  border-radius: 2px;
}

.null-fill.warn {
  background: var(--warning);
}

.null-fill.danger {
  background: var(--danger);
}

.null-value {
  font-size: 11px;
  color: var(--fg-2);
  width: 42px;
  text-align: right;
}

.risk-list {
  list-style: none;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  border-bottom: 1px solid var(--border);
}

.risk-list li {
  font-size: 12px;
  color: var(--warning);
  line-height: 1.6;
}

.risk-list li::before {
  content: '⚠';
  margin-right: 6px;
  font-size: 11px;
}

.table-error {
  padding: 10px 14px;
  font-size: 12px;
  color: var(--danger);
}

.quality {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity var(--dur-2) var(--ease-out);
}

.drawer-enter-active .drawer,
.drawer-leave-active .drawer {
  transition: transform var(--dur-3) var(--ease-out);
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .drawer,
.drawer-leave-to .drawer {
  transform: translateX(24px);
}

@media (max-width: 900px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .span-2 {
    grid-column: span 1;
  }
  .clean-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .meta-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
