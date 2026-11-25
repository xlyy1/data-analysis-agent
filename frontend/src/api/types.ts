/** 后端 API 的数据契约。字段名与 backend/app/api/*.py 的响应保持一致。 */

export type Role = 'admin' | 'analyst' | 'viewer'

export type CellValue = string | number | boolean | null

export type EChartsOption = Record<string, unknown>

export interface ListResponse<T> {
  items: T[]
}

export interface ApiErrorEnvelope {
  error?: {
    code?: string
    message?: string
    details?: unknown
    request_id?: string
  }
  /** 兼容 FastAPI 默认错误体，新代码优先读 error.* */
  detail?: string
}

// ------------------------------------------------------------------ auth

export interface User {
  id: string
  username: string
  display_name: string
  role: Role
  is_active?: boolean
  permissions: string[]
  created_at?: string
  last_login_at?: string | null
}

export interface LoginRequest {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: User
}

// ------------------------------------------------------------------ conversation

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at?: string
}

export interface ChartConfig {
  chart_type?: string
  title?: string
  echarts_option?: EChartsOption
}

export interface DatasourceStatus {
  id?: string
  name?: string
  status?: string
  detail?: string
}

export interface MessageMetadata {
  sql?: string
  executed_sql?: string
  sql_explanation?: string
  analysis_type?: string
  chart_config?: ChartConfig | null
  diagnosis_causes?: string[]
  diagnosis_suggestions?: string[]
  result_warnings?: string[]
  datasource_status?: DatasourceStatus[]
  trace_id?: string
  data_columns?: string[]
  data_rows?: CellValue[][]
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  metadata?: MessageMetadata | null
  created_at: string
  /** 澄清问题的可选项，仅前端使用 */
  options?: string[]
}

export interface ChatRequestPayload {
  conversation_id?: string
  message: string
}

export interface ChatResponse {
  conversation_id: string
  message_id: string
  role: string
  content: string
  metadata?: MessageMetadata | null
  needs_clarification: boolean
  clarification_question: string
  clarification_options: string[]
  sql_needs_confirmation: boolean
}

/** SSE 事件（POST /api/conversations/chat/stream） */
export type StreamEvent =
  | { type: 'node'; node: string; error?: string }
  | { type: 'text'; content: string }
  | { type: 'metadata'; content: MessageMetadata }
  | { type: 'clarification'; content: string; options?: string[] }
  | { type: 'confirm_sql'; sql: string; blocked?: boolean }
  | { type: 'error'; content: string; detail?: string; request_id?: string }

// ------------------------------------------------------------------ datasource

export interface CleaningReport {
  dropped_blank?: number
  dropped_duplicate?: number
  notes?: string[]
  encoding?: string
  sheet?: string
}

export interface DataSourceConfig {
  [key: string]: unknown
  db_path?: string
  host?: string
  port?: number
  user?: string
  password?: string
  database?: string
  file_name?: string
  file_path?: string
  table?: string
  rows?: number
  cleaning?: CleaningReport
  seeded?: boolean
}

export interface SchemaColumn {
  name: string
  dtype: string
  sample_values?: unknown[]
}

export interface SchemaTable {
  name: string
  columns: SchemaColumn[]
  row_count: number
  role?: string
}

export interface SchemaRelation {
  left: string
  right: string
  type: string
  confidence: string
}

export interface DatasourceSchema {
  tables: SchemaTable[]
  relations?: SchemaRelation[]
  column_lookup?: Record<string, string[]>
  join_hint?: string
}

export interface ProfileTopValue {
  value: unknown
  count: number
}

export interface ProfileColumn {
  name: string
  dtype: string
  non_null: number
  null_count: number
  null_rate: number
  distinct_count: number
  distinct_rate: number
  min: unknown
  max: unknown
  top_values: ProfileTopValue[]
  is_numeric: boolean
  is_unique: boolean
  is_pii: boolean
  pii_kind: string
}

export interface ProfileTable {
  table: string
  row_count: number
  column_count: number
  duplicate_groups: number
  risks: string[]
  columns: ProfileColumn[]
  error?: string
}

export interface DatasourceProfile {
  table_count: number
  profiled_tables: number
  total_rows: number
  risk_count: number
  tables: ProfileTable[]
  truncated: boolean
}

export interface DataSourceSummary {
  id: string
  name: string
  type: string
  owner_id: string
  is_active: boolean
  table_count: number
  row_count: number
  created_at: string
  updated_at: string
  config: DataSourceConfig
  seeded: boolean
}

export interface DataSourceDetail extends DataSourceSummary {
  schema?: DatasourceSchema | null
  profile?: DatasourceProfile | null
}

export interface DataSourceCreatePayload {
  name: string
  type: string
  config: Record<string, unknown>
}

export interface DataSourceUpdatePayload {
  name?: string
  config?: Record<string, unknown>
}

export interface TestConnectionResult {
  ok: boolean
  message: string
  detail?: string
  latency_ms?: number
  tables?: { name: string; columns: number; row_count: number }[]
}

export interface IngestResult {
  table: string
  db_path: string
  rows_in: number
  rows_written: number
  dropped_blank: number
  dropped_duplicate: number
  columns: string[]
  dtypes: Record<string, string>
  encoding: string
  sheet: string
  notes: string[]
}

export interface UploadResponse extends DataSourceDetail {
  ingest: IngestResult
}

export interface SupportedType {
  type: string
  label: string
  fields: string[]
  upload?: boolean
}

export interface SupportedTypesResponse {
  types: SupportedType[]
  max_upload_mb: number
}

export interface RefreshSchemaResponse {
  schema: DatasourceSchema | null
  profile: DatasourceProfile | null
}

// ------------------------------------------------------------------ report

export type ReportFormat = 'markdown' | 'html' | 'pdf'

export interface ReportSummary {
  id: string
  title: string
  conversation_id: string
  created_at: string
}

export interface ReportDetail extends ReportSummary {
  markdown: string
}

export interface ReportGenerateRequest {
  conversation_id: string
  format: 'json' | ReportFormat
}

export interface ReportGenerateResponse {
  id: string
  title: string
  created_at: string
  markdown_preview: string
  download: Record<string, string>
}

// ------------------------------------------------------------------ schedule

export interface Schedule {
  id: string
  name: string
  question: string
  datasource_ids: string[]
  interval_minutes: number
  enabled: boolean
  last_run_at: string | null
  next_run_at: string | null
  last_status: string | null
  last_error: string | null
  consecutive_failures: number
  created_at: string | null
}

export interface ScheduleRun {
  id: string
  scheduled_for: string
  status: string
  attempts: number
  task_id: string | null
  error: string | null
  finished_at: string | null
}

export interface ScheduleCreatePayload {
  name: string
  question: string
  datasource_ids?: string[]
  interval_minutes?: number
  enabled?: boolean
}

export interface ScheduleUpdatePayload {
  name?: string
  question?: string
  datasource_ids?: string[]
  interval_minutes?: number
  enabled?: boolean
}

export interface ScheduleRunResponse {
  run_id: string
  task_id: string
  status: string
}
