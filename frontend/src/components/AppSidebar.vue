<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-inner">
      <div class="sidebar-brand" @click="collapsed = !collapsed">
        <div class="brand-mark">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <rect x="2" y="2" width="7" height="7" rx="1.5" fill="currentColor" />
            <rect x="11" y="2" width="7" height="4" rx="1.5" fill="currentColor" opacity="0.4" />
            <rect x="2" y="11" width="7" height="4" rx="1.5" fill="currentColor" opacity="0.4" />
            <rect x="11" y="8" width="7" height="10" rx="1.5" fill="currentColor" opacity="0.7" />
          </svg>
        </div>
        <span v-show="!collapsed" class="brand-text">DataAgent</span>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: $route.name === item.name }"
          :title="collapsed ? item.label : ''"
        >
          <span class="nav-icon-wrap">
            <component :is="item.icon" />
          </span>
          <span v-show="!collapsed" class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div v-show="!collapsed" class="sidebar-hint">
        <span class="hint-role">{{ auth.roleLabel || '未登录' }}</span>
        <span class="hint-perm">{{ auth.permissions.length }} 项权限</span>
      </div>
    </div>

    <div class="sidebar-footer">
      <div v-show="!collapsed" class="user-chip" :title="auth.user?.username">
        <div class="user-avatar">{{ auth.initial }}</div>
        <div class="user-meta">
          <span class="user-name truncate">{{ auth.displayName }}</span>
          <span class="user-role">{{ auth.roleLabel }}</span>
        </div>
      </div>

      <button
        v-show="!collapsed"
        class="icon-btn"
        type="button"
        title="退出登录"
        aria-label="退出登录"
        @click="onLogout"
      >
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M6 2.5H3.5A1.5 1.5 0 002 4v8a1.5 1.5 0 001.5 1.5H6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
          <path d="M10 5l3 3-3 3M13 8H6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>

      <button class="icon-btn" type="button" :title="collapsed ? '展开' : '收起'" @click="collapsed = !collapsed">
        <svg
          width="15"
          height="15"
          viewBox="0 0 16 16"
          fill="none"
          :style="{ transform: collapsed ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }"
        >
          <path d="M10.5 3l-5 5 5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { h, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

const collapsed = ref(localStorage.getItem('sidebar_collapsed') === '1')

watch(collapsed, (value) => {
  localStorage.setItem('sidebar_collapsed', value ? '1' : '0')
})

function icon(paths: { d: string; opacity?: string }[]) {
  return {
    render() {
      return h(
        'svg',
        { width: 17, height: 17, viewBox: '0 0 18 18', fill: 'none' },
        paths.map((item) =>
          h('path', {
            d: item.d,
            stroke: 'currentColor',
            'stroke-width': '1.3',
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
            opacity: item.opacity,
          }),
        ),
      )
    },
  }
}

const ChatIcon = icon([
  { d: 'M2 4.5A2.5 2.5 0 014.5 2h9A2.5 2.5 0 0116 4.5v7A2.5 2.5 0 0113.5 14H9l-3 3v-3H4.5A2.5 2.5 0 012 11.5v-7z' },
])

const DataSourceIcon = icon([
  { d: 'M3 4c0-1.1 2.7-2 6-2s6 .9 6 2-2.7 2-6 2-6-.9-6-2z' },
  { d: 'M3 4v4c0 1.1 2.7 2 6 2s6-.9 6-2V4' },
  { d: 'M3 8v4c0 1.1 2.7 2 6 2s6-.9 6-2V8' },
])

const ReportIcon = icon([
  { d: 'M4.5 1.5h6l4 4V14.5A1.5 1.5 0 0113 16H5a1.5 1.5 0 01-1.5-1.5v-11A1.5 1.5 0 014.5 1.5z' },
  { d: 'M10.5 1.5v4h4' },
  { d: 'M6 9h6M6 11.5h6M6 14h3.5' },
])

const ClockIcon = icon([
  { d: 'M9 16.2A7.2 7.2 0 109 1.8a7.2 7.2 0 000 14.4z' },
  { d: 'M9 5.2v4l2.6 1.6' },
])

const navItems = [
  { path: '/', name: 'Chat', label: '对话', icon: ChatIcon },
  { path: '/datasources', name: 'DataSources', label: '数据源', icon: DataSourceIcon },
  { path: '/reports', name: 'Reports', label: '报告', icon: ReportIcon },
  { path: '/schedules', name: 'Schedules', label: '定时任务', icon: ClockIcon },
]

async function onLogout(): Promise<void> {
  await auth.logout()
  await router.replace({ name: 'Login' })
}
</script>

<style scoped>
.sidebar {
  width: 216px;
  min-width: 216px;
  background: var(--bg-1);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  height: 100vh;
  user-select: none;
  transition: width var(--dur-3) var(--ease-out), min-width var(--dur-3) var(--ease-out);
}

.sidebar.collapsed {
  width: 60px;
  min-width: 60px;
}

.sidebar-inner {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 18px 14px 20px;
  cursor: pointer;
  color: var(--accent);
}

.brand-mark {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--accent-hi);
  border: 1px solid var(--accent-line);
  flex-shrink: 0;
  color: var(--accent);
}

.brand-text {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--fg-0);
  white-space: nowrap;
}

.sidebar.collapsed .sidebar-brand {
  padding: 18px 0 20px;
  justify-content: center;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  color: var(--fg-3);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  transition: all var(--dur-1) var(--ease-out);
  white-space: nowrap;
  position: relative;
}

.nav-icon-wrap {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
  transition: all var(--dur-2) var(--ease-out);
  color: inherit;
}

.nav-item:hover {
  background: var(--bg-3);
  color: var(--fg-1);
}

.nav-item.active {
  background: var(--bg-3);
  color: var(--fg-0);
}

.nav-item.active .nav-icon-wrap {
  background: var(--accent-hi);
  color: var(--accent);
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 16px;
  border-radius: 1px;
  background: var(--accent);
}

.nav-label {
  flex: 1;
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 8px 0;
}

.sidebar.collapsed .nav-item.active::before {
  display: none;
}

.sidebar-hint {
  margin-top: auto;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  border-top: 1px dashed var(--border);
}

.hint-role {
  font-size: 11px;
  color: var(--fg-2);
  font-weight: 500;
}

.hint-perm {
  font-size: 10px;
  color: var(--fg-4);
  font-family: var(--font-mono);
}

.sidebar-footer {
  padding: 8px 10px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-1);
}

.sidebar.collapsed .sidebar-footer {
  flex-direction: column;
  gap: 4px;
}

.user-chip {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.user-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--accent-hi);
  border: 1px solid var(--accent-line);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: #A5B4FC;
  flex-shrink: 0;
}

.user-meta {
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
}

.user-name {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--fg-1);
  max-width: 110px;
}

.user-role {
  font-size: 10px;
  color: var(--fg-4);
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  background: transparent;
  color: var(--fg-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
  flex-shrink: 0;
}

.icon-btn:hover {
  background: var(--bg-3);
  color: var(--fg-1);
}
</style>
