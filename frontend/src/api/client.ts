/**
 * axios 实例 + 统一错误 + 全部接口的类型化封装。
 *
 * 401 处理：只尝试一次 refresh（并发请求共享同一个 refresh Promise），
 * 成功后重放原请求；refresh 失败或没有 refresh token 时清空 token 并跳登录页。
 */
import axios, { type AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

import { clearTokens, getAccessToken, getRefreshToken, setTokens } from './tokens'
import type {
  ApiErrorEnvelope,
  ChatMessage,
  ChatRequestPayload,
  ChatResponse,
  ConversationSummary,
  DataSourceCreatePayload,
  DataSourceDetail,
  DataSourceSummary,
  DataSourceUpdatePayload,
  DatasourceProfile,
  ListResponse,
  LoginRequest,
  RefreshSchemaResponse,
  ReportDetail,
  ReportFormat,
  ReportGenerateRequest,
  ReportGenerateResponse,
  ReportSummary,
  Schedule,
  ScheduleCreatePayload,
  ScheduleRun,
  ScheduleRunResponse,
  ScheduleUpdatePayload,
  StreamEvent,
  SupportedTypesResponse,
  TestConnectionResult,
  TokenResponse,
  UploadResponse,
  User,
} from './types'

// ------------------------------------------------------------------ ApiError

export interface ApiErrorOptions {
  code?: string
  requestId?: string
  status?: number
  details?: unknown
}

/** 前端统一的错误形态：code 用来分支，message 直接展示，requestId 用于报障。 */
export class ApiError extends Error {
  readonly code: string
  readonly requestId: string
  readonly status: number
  readonly details: unknown

  constructor(message: string, options: ApiErrorOptions = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = options.code ?? 'unknown_error'
    this.requestId = options.requestId ?? ''
    this.status = options.status ?? 0
    this.details = options.details ?? null
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }
}

/** 把任意抛出的值收敛成 ApiError，模板里就能安全读 message / requestId。 */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0
    const parsed = parseErrorEnvelope(error.response?.data)
    if (parsed) {
      return new ApiError(parsed.message || fallbackMessage(status), {
        code: parsed.code,
        requestId: parsed.requestId,
        status,
        details: parsed.details,
      })
    }
    if (status === 0) {
      return new ApiError('无法连接后端服务，请确认 API 已启动（默认 8000 端口）', {
        code: 'network_error',
      })
    }
    return new ApiError(fallbackMessage(status), { code: 'http_error', status })
  }
  if (error instanceof Error) return new ApiError(error.message)
  return new ApiError('请求失败，请稍后重试')
}

function fallbackMessage(status: number): string {
  if (status === 400) return '请求不合法'
  if (status === 401) return '登录已过期，请重新登录'
  if (status === 403) return '当前账号无权执行该操作'
  if (status === 404) return '资源不存在或已被删除'
  if (status === 413) return '文件超过大小限制'
  if (status === 429) return '操作过于频繁，请稍后再试'
  if (status >= 500) return '服务内部错误，请稍后重试'
  return `请求失败${status ? `（HTTP ${status}）` : ''}`
}

interface ParsedEnvelope {
  code: string
  message: string
  requestId: string
  details: unknown
}

function parseErrorEnvelope(data: unknown): ParsedEnvelope | null {
  if (!data || typeof data !== 'object') return null
  const body = data as ApiErrorEnvelope
  const nested = body.error && typeof body.error === 'object' ? body.error : null
  const message =
    (nested && typeof nested.message === 'string' && nested.message) ||
    (typeof body.detail === 'string' && body.detail) ||
    ''
  const code = nested && typeof nested.code === 'string' ? nested.code : ''
  const requestId = nested && typeof nested.request_id === 'string' ? nested.request_id : ''
  if (!message && !code) return null
  return { code: code || 'request_error', message, requestId, details: nested?.details ?? null }
}

// ------------------------------------------------------------------ refresh / 跳转

let refreshPromise: Promise<string> | null = null
let redirecting = false

function redirectToLogin(): void {
  clearTokens()
  if (typeof window === 'undefined' || redirecting) return
  if (window.location.pathname === '/login') return
  redirecting = true
  const next = `${window.location.pathname}${window.location.search}`
  window.location.assign(`/login?redirect=${encodeURIComponent(next)}`)
}

/** 用 refresh token 换新的 access token（后端会轮换 refresh token）。 */
export function refreshSession(): Promise<string> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    redirectToLogin()
    return Promise.reject(new ApiError('登录已过期，请重新登录', { code: 'no_refresh_token', status: 401 }))
  }
  if (!refreshPromise) {
    refreshPromise = axios
      .post<TokenResponse>('/api/auth/refresh', { refresh_token: refreshToken })
      .then((response) => {
        setTokens(response.data.access_token, response.data.refresh_token)
        return response.data.access_token
      })
      .catch((error: unknown) => {
        redirectToLogin()
        throw toApiError(error)
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

// ------------------------------------------------------------------ axios 实例

export const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

function isAuthEndpoint(url?: string): boolean {
  if (!url) return false
  return url.includes('/auth/login') || url.includes('/auth/refresh')
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: unknown) => {
    const axiosError = error as AxiosError
    const config = axiosError.config as RetriableConfig | undefined
    if (axiosError.response?.status === 401 && config && !isAuthEndpoint(config.url)) {
      if (!config._retried && getRefreshToken()) {
        config._retried = true
        try {
          const token = await refreshSession()
          config.headers.set('Authorization', `Bearer ${token}`)
          return await api.request(config)
        } catch {
          /* 落到下面统一抛错 */
        }
      } else {
        redirectToLogin()
      }
    }
    throw toApiError(error)
  },
)

/** fetch 版鉴权请求：SSE 不能用 axios，但同样要带 token 且支持一次 refresh。 */
async function authorizedFetch(url: string, init: RequestInit, allowRefresh = true): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(url, { ...init, headers })
  if (response.status === 401 && allowRefresh && getRefreshToken()) {
    try {
      const nextToken = await refreshSession()
      const retryHeaders = new Headers(init.headers)
      retryHeaders.set('Authorization', `Bearer ${nextToken}`)
      return await fetch(url, { ...init, headers: retryHeaders })
    } catch {
      redirectToLogin()
    }
  }
  return response
}

// ------------------------------------------------------------------ auth

export const authApi = {
  login(payload: LoginRequest): Promise<TokenResponse> {
    return api.post<TokenResponse>('/auth/login', payload).then((response) => response.data)
  },
  me(): Promise<User> {
    return api.get<User>('/auth/me').then((response) => response.data)
  },
  logout(refreshToken: string): Promise<{ status: string }> {
    return api
      .post<{ status: string }>('/auth/logout', { refresh_token: refreshToken })
      .then((response) => response.data)
  },
}

// ------------------------------------------------------------------ datasource

export const datasourceApi = {
  list(): Promise<DataSourceSummary[]> {
    return api
      .get<ListResponse<DataSourceSummary>>('/datasources')
      .then((response) => response.data.items ?? [])
  },
  get(id: string): Promise<DataSourceDetail> {
    return api.get<DataSourceDetail>(`/datasources/${id}`).then((response) => response.data)
  },
  create(payload: DataSourceCreatePayload): Promise<DataSourceDetail> {
    return api.post<DataSourceDetail>('/datasources', payload).then((response) => response.data)
  },
  update(id: string, payload: DataSourceUpdatePayload): Promise<DataSourceDetail> {
    return api
      .patch<DataSourceDetail>(`/datasources/${id}`, payload)
      .then((response) => response.data)
  },
  remove(id: string): Promise<{ status: string }> {
    return api.delete<{ status: string }>(`/datasources/${id}`).then((response) => response.data)
  },
  test(payload: DataSourceCreatePayload): Promise<TestConnectionResult> {
    return api
      .post<TestConnectionResult>('/datasources/test', payload)
      .then((response) => response.data)
  },
  upload(file: File, append = false): Promise<UploadResponse> {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<UploadResponse>('/datasources/upload', form, {
        params: { append },
        timeout: 180000,
      })
      .then((response) => response.data)
  },
  refreshSchema(id: string): Promise<RefreshSchemaResponse> {
    return api
      .post<RefreshSchemaResponse>(`/datasources/${id}/refresh-schema`)
      .then((response) => response.data)
  },
  profile(id: string, refresh = false): Promise<DatasourceProfile> {
    return api
      .get<DatasourceProfile>(`/datasources/${id}/profile`, { params: { refresh } })
      .then((response) => response.data)
  },
  supportedTypes(): Promise<SupportedTypesResponse> {
    return api
      .get<SupportedTypesResponse>('/datasources/supported-types')
      .then((response) => response.data)
  },
}

// ------------------------------------------------------------------ conversation

export const conversationApi = {
  list(): Promise<ConversationSummary[]> {
    return api
      .get<ConversationSummary[]>('/conversations/')
      .then((response) => response.data ?? [])
  },
  create(): Promise<ConversationSummary> {
    return api
      .post<ConversationSummary>('/conversations/')
      .then((response) => response.data)
  },
  remove(id: string): Promise<{ status: string }> {
    return api
      .delete<{ status: string }>(`/conversations/${id}`)
      .then((response) => response.data)
  },
  messages(id: string): Promise<ChatMessage[]> {
    return api
      .get<ChatMessage[]>(`/conversations/${id}/messages`)
      .then((response) => response.data ?? [])
  },
  chat(payload: ChatRequestPayload): Promise<ChatResponse> {
    return api
      .post<ChatResponse>('/conversations/chat', payload)
      .then((response) => response.data)
  },
}

/**
 * SSE 流式对话：`fetch` + ReadableStream（EventSource 无法带 Authorization 头）。
 * 每个事件回调一次；收到 `data: [DONE]` 即结束。
 */
export async function streamChat(
  payload: ChatRequestPayload,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await authorizedFetch('/api/conversations/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    const raw = await response.text()
    let parsed: unknown = raw
    try {
      parsed = JSON.parse(raw)
    } catch {
      /* 非 JSON 错误体，保留原文 */
    }
    const envelope = parseErrorEnvelope(parsed)
    throw new ApiError(envelope?.message || fallbackMessage(response.status), {
      code: envelope?.code ?? 'stream_error',
      requestId: envelope?.requestId ?? response.headers.get('x-request-id') ?? '',
      status: response.status,
    })
  }
  if (!response.body) {
    throw new ApiError('当前浏览器不支持流式响应', { code: 'stream_unsupported' })
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const rawEvent = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        if (dispatchSseEvent(rawEvent, onEvent)) {
          await reader.cancel().catch(() => undefined)
          return
        }
        boundary = buffer.indexOf('\n\n')
      }
    }
    // 流意外关闭时，把残留的一条事件也解析掉
    if (buffer.trim()) dispatchSseEvent(buffer, onEvent)
  } finally {
    reader.releaseLock()
  }
}

/** 返回 true 表示收到 [DONE]。 */
function dispatchSseEvent(rawEvent: string, onEvent: (event: StreamEvent) => void): boolean {
  for (const line of rawEvent.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed.startsWith('data:')) continue
    const data = trimmed.slice(5).trim()
    if (!data) continue
    if (data === '[DONE]') return true
    try {
      onEvent(JSON.parse(data) as StreamEvent)
    } catch {
      /* 单条事件解析失败不影响后续事件 */
    }
  }
  return false
}

// ------------------------------------------------------------------ report

export interface DownloadedFile {
  blob: Blob
  filename: string
}

function filenameFromDisposition(disposition: string | undefined, fallback: string): string {
  if (!disposition) return fallback
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8?.[1]) return decodeURIComponent(utf8[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain?.[1] ?? fallback
}

export const reportApi = {
  list(): Promise<ReportSummary[]> {
    return api
      .get<ListResponse<ReportSummary>>('/reports')
      .then((response) => response.data.items ?? [])
  },
  get(id: string): Promise<ReportDetail> {
    return api.get<ReportDetail>(`/reports/${id}`).then((response) => response.data)
  },
  generate(payload: ReportGenerateRequest): Promise<ReportGenerateResponse> {
    return api
      .post<ReportGenerateResponse>('/reports/generate', payload)
      .then((response) => response.data)
  },
  async download(id: string, format: ReportFormat): Promise<DownloadedFile> {
    const response = await api.get<Blob>(`/reports/${id}/download`, {
      params: { format },
      responseType: 'blob',
      timeout: 180000,
    })
    const disposition = response.headers?.['content-disposition']
    const extensions: Record<ReportFormat, string> = { markdown: 'md', html: 'html', pdf: 'pdf' }
    const blob = response.data
    const typeName = blob.type || 'application/octet-stream'
    return {
      blob: blob instanceof Blob ? new Blob([blob], { type: typeName }) : blob,
      filename: filenameFromDisposition(
        typeof disposition === 'string' ? disposition : undefined,
        `report-${id.slice(0, 8)}.${extensions[format]}`,
      ),
    }
  },
}

// ------------------------------------------------------------------ schedule

export const scheduleApi = {
  list(): Promise<Schedule[]> {
    return api
      .get<ListResponse<Schedule>>('/schedules')
      .then((response) => response.data.items ?? [])
  },
  create(payload: ScheduleCreatePayload): Promise<Schedule> {
    return api.post<Schedule>('/schedules', payload).then((response) => response.data)
  },
  update(id: string, payload: ScheduleUpdatePayload): Promise<Schedule> {
    return api.patch<Schedule>(`/schedules/${id}`, payload).then((response) => response.data)
  },
  remove(id: string): Promise<{ status: string }> {
    return api.delete<{ status: string }>(`/schedules/${id}`).then((response) => response.data)
  },
  runNow(id: string): Promise<ScheduleRunResponse> {
    return api
      .post<ScheduleRunResponse>(`/schedules/${id}/run`)
      .then((response) => response.data)
  },
  runs(id: string): Promise<ScheduleRun[]> {
    return api
      .get<ListResponse<ScheduleRun>>(`/schedules/${id}/runs`)
      .then((response) => response.data.items ?? [])
  },
}
