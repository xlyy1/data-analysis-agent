<template>
  <aside class="sidebar" :class="{ collapsed: collapsed }">
    <div class="sidebar-inner">
      <div class="sidebar-brand" @click="collapsed = !collapsed">
        <div class="brand-mark">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <rect x="2" y="2" width="7" height="7" rx="1.5" fill="currentColor"/>
            <rect x="11" y="2" width="7" height="4" rx="1.5" fill="currentColor" opacity="0.4"/>
            <rect x="2" y="11" width="7" height="4" rx="1.5" fill="currentColor" opacity="0.4"/>
            <rect x="11" y="8" width="7" height="10" rx="1.5" fill="currentColor" opacity="0.7"/>
          </svg>
        </div>
        <transition name="fade">
          <span v-show="!collapsed" class="brand-text">DataAgent</span>
        </transition>
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
          <div class="nav-icon-wrap">
            <component :is="item.icon" />
          </div>
          <transition name="fade">
            <span v-show="!collapsed" class="nav-label">{{ item.label }}</span>
          </transition>
        </router-link>
      </nav>
    </div>

    <div class="sidebar-footer">
      <transition name="fade">
        <div v-show="!collapsed" class="user-chip">
          <div class="user-avatar">A</div>
          <div class="user-meta">
            <span class="user-name">Analyst</span>
            <span class="user-role">Workspace</span>
          </div>
        </div>
      </transition>
      <button class="collapse-btn" :title="collapsed ? '展开' : '收起'" @click="collapsed = !collapsed">
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          :style="{ transform: collapsed ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }"
        >
          <path d="M10.5 3l-5 5 5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, watch, h } from 'vue'

const collapsed = ref(localStorage.getItem('sidebar_collapsed') === '1')

watch(collapsed, (v) => {
  localStorage.setItem('sidebar_collapsed', v ? '1' : '0')
})

const ChatIcon = {
  render() {
    return h('svg', { width: 18, height: 18, viewBox: '0 0 18 18', fill: 'none' }, [
      h('path', { d: 'M2 4.5A2.5 2.5 0 014.5 2h9A2.5 2.5 0 0116 4.5v7A2.5 2.5 0 0113.5 14H9l-3 3v-3H4.5A2.5 2.5 0 012 11.5v-7z', stroke: 'currentColor', 'stroke-width': '1.3', 'stroke-linejoin': 'round' })
    ])
  }
}

const DataSourceIcon = {
  render() {
    return h('svg', { width: 18, height: 18, viewBox: '0 0 18 18', fill: 'none' }, [
      h('ellipse', { cx: '9', cy: '4', rx: '6', ry: '2', stroke: 'currentColor', 'stroke-width': '1.3' }),
      h('path', { d: 'M3 4v4c0 1.1 2.7 2 6 2s6-.9 6-2V4', stroke: 'currentColor', 'stroke-width': '1.3' }),
      h('path', { d: 'M3 8v4c0 1.1 2.7 2 6 2s6-.9 6-2V8', stroke: 'currentColor', 'stroke-width': '1.3' })
    ])
  }
}

const ReportIcon = {
  render() {
    return h('svg', { width: 18, height: 18, viewBox: '0 0 18 18', fill: 'none' }, [
      h('path', { d: 'M4 1.5h6l4 4V14.5A1.5 1.5 0 0112.5 16h-8A1.5 1.5 0 013 14.5v-11A1.5 1.5 0 014.5 2.5', stroke: 'currentColor', 'stroke-width': '1.3', 'stroke-linejoin': 'round' }),
      h('path', { d: 'M10 1.5v4h4', stroke: 'currentColor', 'stroke-width': '1.3', 'stroke-linejoin': 'round' }),
      h('path', { d: 'M5.5 9h6M5.5 11.5h6M5.5 14h4', stroke: 'currentColor', 'stroke-width': '1.2', 'stroke-linecap': 'round' })
    ])
  }
}

const navItems = [
  {
    path: '/',
    name: 'Chat',
    label: '对话',
    icon: ChatIcon,
  },
  {
    path: '/datasources',
    name: 'DataSources',
    label: '数据源',
    icon: DataSourceIcon,
  },
  {
    path: '/reports',
    name: 'Reports',
    label: '报告',
    icon: ReportIcon,
  },
]
</script>

<style scoped>
.sidebar {
  width: 64px;
  min-width: 64px;
  background: var(--bg-1);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  height: 100vh;
  user-select: none;
  transition: width var(--dur-3) var(--ease-out), min-width var(--dur-3) var(--ease-out);
}

.sidebar.collapsed {
  width: 64px;
  min-width: 64px;
}

.sidebar:not(.collapsed) {
  width: 220px;
  min-width: 220px;
}

.sidebar-inner {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 16px 24px;
  cursor: pointer;
  color: var(--accent);
}

.brand-mark {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--accent-hi);
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
  padding: 20px 0 24px;
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
  gap: 12px;
  padding: 9px 12px;
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
  width: 28px;
  height: 28px;
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

.nav-item:hover .nav-icon-wrap {
  color: var(--fg-0);
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
  padding: 9px 0;
}

.sidebar.collapsed .nav-item.active::before {
  display: none;
}

.sidebar-footer {
  padding: 10px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-1);
}

.user-chip {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--bg-3);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--fg-2);
  flex-shrink: 0;
}

.user-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.user-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--fg-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 10px;
  color: var(--fg-3);
}

.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--fg-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
  flex-shrink: 0;
}

.collapse-btn:hover {
  background: var(--bg-3);
  color: var(--fg-1);
}
</style>
