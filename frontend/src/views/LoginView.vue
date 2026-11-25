<template>
  <div class="login-view">
    <div class="login-bg" aria-hidden="true"></div>

    <section class="login-brand">
      <div class="brand-top">
        <div class="brand-mark">
          <svg width="22" height="22" viewBox="0 0 20 20" fill="none">
            <rect x="2" y="2" width="7" height="7" rx="1.5" fill="currentColor" />
            <rect x="11" y="2" width="7" height="4" rx="1.5" fill="currentColor" opacity="0.4" />
            <rect x="2" y="11" width="7" height="4" rx="1.5" fill="currentColor" opacity="0.4" />
            <rect x="11" y="8" width="7" height="10" rx="1.5" fill="currentColor" opacity="0.7" />
          </svg>
        </div>
        <div class="brand-name">
          DataAgent
          <span class="brand-tag">v1.0</span>
        </div>
      </div>

      <h1 class="brand-headline">
        用一句话，<br />
        问出你的数据答案
      </h1>
      <p class="brand-sub">
        自然语言 → SQL → 结果表 + 图表 + 中文结论。只读执行、自动补 LIMIT，
        每个回答都能追溯到 SQL 与 request_id。
      </p>

      <ul class="brand-points">
        <li v-for="point in points" :key="point.title">
          <span class="point-dot"></span>
          <div>
            <strong>{{ point.title }}</strong>
            <span>{{ point.desc }}</span>
          </div>
        </li>
      </ul>

      <div class="brand-foot">角色分级 · admin / analyst / viewer</div>
    </section>

    <section class="login-panel">
      <form class="login-card" @submit.prevent="onSubmit">
        <div class="card-top">
          <h2 class="login-title">登录工作台</h2>
          <p class="login-sub">使用分配给你的账号继续</p>
        </div>

        <div v-if="auth.error" class="alert alert-error login-error" role="alert">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="8" cy="8" r="6.4" stroke="currentColor" stroke-width="1.2" />
            <path d="M8 4.8v4M8 11.2v.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
          <div class="alert-body">{{ auth.error }}</div>
        </div>

        <label class="field">
          <span class="label">用户名</span>
          <input
            v-model="username"
            class="input"
            type="text"
            autocomplete="username"
            placeholder="admin"
            :disabled="auth.loading"
            required
            @input="auth.clearError()"
          />
        </label>

        <label class="field">
          <span class="label">密码</span>
          <div class="password-wrap">
            <input
              v-model="password"
              class="input"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="请输入密码"
              :disabled="auth.loading"
              required
              @input="auth.clearError()"
            />
            <button
              class="password-toggle"
              type="button"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              {{ showPassword ? '隐藏' : '显示' }}
            </button>
          </div>
        </label>

        <button class="btn btn-primary btn-block login-submit" type="submit" :disabled="auth.loading">
          <span v-if="auth.loading" class="spinner"></span>
          {{ auth.loading ? '登录中…' : '登录' }}
        </button>

        <div class="demo-hint">
          <div class="demo-text">
            <span class="badge badge-accent">演示账号</span>
            <span class="mono">admin / admin12345</span>
          </div>
          <button class="btn btn-sm btn-ghost" type="button" :disabled="auth.loading" @click="fillDemo">
            一键填入
          </button>
        </div>
      </form>

      <p class="login-foot">登录后所有业务接口都会携带 Bearer Token，401 会自动刷新一次。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const showPassword = ref(false)

const points = [
  { title: '只读执行', desc: '注入 / 删表 / 改数据一律拦截，查询超时与行数都有上限' },
  { title: '结果可追溯', desc: 'SQL、执行计划、请求 ID 全保留，出错能直接定位' },
  { title: '数据质量先行', desc: '上传即出清洗报告与空值率 / PII 画像' },
]

function fillDemo(): void {
  username.value = 'admin'
  password.value = 'admin12345'
  auth.clearError()
}

async function onSubmit(): Promise<void> {
  if (auth.loading) return
  if (!username.value.trim() || !password.value) {
    auth.error = '请填写用户名和密码'
    return
  }
  const ok = await auth.login(username.value, password.value)
  if (!ok) return
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
  // 只允许站内相对路径，避免 //evil.com 这类开放重定向
  const target = redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/'
  await router.replace(target)
}
</script>

<style scoped>
.login-view {
  position: relative;
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  min-height: 100vh;
  background: var(--bg-0);
  overflow: hidden;
}

.login-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(560px 420px at 12% 18%, rgba(99, 102, 241, 0.16), transparent 70%),
    radial-gradient(620px 480px at 82% 88%, rgba(79, 70, 229, 0.12), transparent 72%),
    linear-gradient(rgba(255, 255, 255, 0.028) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.028) 1px, transparent 1px);
  background-size: auto, auto, 56px 56px, 56px 56px;
  mask-image: radial-gradient(circle at 40% 40%, #000 30%, transparent 82%);
}

.login-brand {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 56px clamp(40px, 6vw, 88px);
  border-right: 1px solid var(--border);
  gap: 22px;
}

.brand-top {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}

.brand-mark {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: var(--accent-hi);
  border: 1px solid var(--accent-line);
  color: var(--accent);
}

.brand-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.brand-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  color: var(--fg-3);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 7px;
}

.brand-headline {
  font-size: clamp(30px, 3.4vw, 42px);
  line-height: 1.24;
  font-weight: 600;
  letter-spacing: -0.03em;
  color: var(--fg-0);
}

.brand-sub {
  font-size: 13.5px;
  color: var(--fg-2);
  line-height: 1.8;
  max-width: 460px;
}

.brand-points {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 8px;
  max-width: 460px;
}

.brand-points li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.point-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  margin-top: 7px;
  flex-shrink: 0;
  box-shadow: 0 0 0 3px var(--accent-glow);
}

.brand-points strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-1);
}

.brand-points span:not(.point-dot) {
  font-size: 12.5px;
  color: var(--fg-3);
  line-height: 1.65;
}

.brand-foot {
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--fg-4);
  font-family: var(--font-mono);
}

.login-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 32px;
  gap: 16px;
}

.login-card {
  width: 100%;
  max-width: 360px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 28px 26px;
  background: rgba(17, 17, 19, 0.86);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(10px);
}

.card-top {
  margin-bottom: 2px;
}

.login-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--fg-0);
}

.login-sub {
  font-size: 12.5px;
  color: var(--fg-3);
  margin-top: 4px;
}

.login-error {
  font-size: 12.5px;
  padding: 9px 12px;
}

.password-wrap {
  position: relative;
}

.password-wrap .input {
  padding-right: 52px;
}

.password-toggle {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  border: none;
  background: transparent;
  color: var(--fg-3);
  font-size: 11.5px;
  font-family: var(--font-sans);
  cursor: pointer;
  padding: 3px 7px;
  border-radius: 4px;
}

.password-toggle:hover {
  color: var(--fg-1);
  background: var(--bg-3);
}

.login-submit {
  height: 38px;
  margin-top: 2px;
}

.demo-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 11px;
  border: 1px dashed var(--accent-line);
  border-radius: var(--radius-sm);
  background: var(--accent-hi);
  margin-top: 2px;
}

.demo-text {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--fg-2);
  flex-wrap: wrap;
}

.login-foot {
  font-size: 11px;
  color: var(--fg-4);
  max-width: 360px;
  text-align: center;
  line-height: 1.7;
}

@media (max-width: 900px) {
  .login-view {
    grid-template-columns: 1fr;
  }
  .login-brand {
    display: none;
  }
}
</style>
