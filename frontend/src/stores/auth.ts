import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi, toApiError } from '../api/client'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '../api/tokens'
import type { Role, TokenResponse, User } from '../api/types'

const ROLE_LABELS: Record<Role, string> = {
  admin: '管理员',
  analyst: '数据分析师',
  viewer: '只读访客',
}

/**
 * 登录态：token 落 localStorage，user/permissions 来自后端（不自己猜权限）。
 * logout 只清本地 + 尽力吊销 refresh token，跳转交给路由。
 */
export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const permissions = ref<string[]>([])
  const accessToken = ref<string | null>(getAccessToken())
  const loading = ref(false)
  const restoring = ref(false)
  const error = ref('')

  const isAuthenticated = computed(() => Boolean(accessToken.value))
  const isAdmin = computed(() => user.value?.role === 'admin')
  const displayName = computed(() => user.value?.display_name || user.value?.username || '未登录')
  const roleLabel = computed(() => (user.value ? ROLE_LABELS[user.value.role] ?? user.value.role : ''))
  const initial = computed(() => displayName.value.slice(0, 1).toUpperCase())

  /** 权限点来自 /api/auth/login 或 /api/auth/me 返回的 permissions。 */
  function has(permission: string): boolean {
    if (!permission) return true
    return permissions.value.includes(permission)
  }

  function applyUser(next: User): void {
    user.value = next
    permissions.value = next.permissions ?? []
  }

  function applyTokens(tokens: TokenResponse): void {
    setTokens(tokens.access_token, tokens.refresh_token)
    accessToken.value = tokens.access_token
    applyUser(tokens.user)
  }

  function clearSession(): void {
    clearTokens()
    accessToken.value = null
    user.value = null
    permissions.value = []
  }

  async function login(username: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = ''
    try {
      const tokens = await authApi.login({ username: username.trim(), password })
      applyTokens(tokens)
      return true
    } catch (caught) {
      error.value = toApiError(caught).message
      return false
    } finally {
      loading.value = false
    }
  }

  /** 冷启动时用已有 token 拉当前用户；失败说明彻底过期，清空本地态。 */
  async function restore(): Promise<boolean> {
    if (!getAccessToken()) {
      clearSession()
      return false
    }
    if (user.value) return true
    restoring.value = true
    try {
      applyUser(await authApi.me())
      accessToken.value = getAccessToken()
      return true
    } catch {
      clearSession()
      return false
    } finally {
      restoring.value = false
    }
  }

  async function logout(): Promise<void> {
    const refreshToken = getRefreshToken()
    error.value = ''
    try {
      // 先尽力吊销 refresh token（此时 access token 还在，请求能带上 Authorization）
      if (refreshToken) await authApi.logout(refreshToken)
    } catch {
      /* refresh token 可能已过期；本地登出不受影响 */
    } finally {
      clearSession()
    }
  }

  function clearError(): void {
    error.value = ''
  }

  return {
    user,
    permissions,
    accessToken,
    loading,
    restoring,
    error,
    isAuthenticated,
    isAdmin,
    displayName,
    roleLabel,
    initial,
    has,
    login,
    logout,
    restore,
    clearSession,
    clearError,
  }
})
