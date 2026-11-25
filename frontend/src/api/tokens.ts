/**
 * Token 持久化：只在这里读写 localStorage，方便统一清理。
 * 刻意不放进 pinia store，避免 axios 拦截器与 store 形成循环依赖。
 */
const ACCESS_TOKEN_KEY = 'data_agent_access_token'
const REFRESH_TOKEN_KEY = 'data_agent_refresh_token'

export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(ACCESS_TOKEN_KEY)
  } catch {
    return null
  }
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY)
  } catch {
    return null
  }
}

export function setTokens(accessToken: string, refreshToken: string): void {
  try {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
    if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
  } catch {
    /* 隐私模式下 localStorage 可能不可写，退化为仅内存态，不影响本次会话 */
  }
}

export function clearTokens(): void {
  try {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  } catch {
    /* ignore */
  }
}
