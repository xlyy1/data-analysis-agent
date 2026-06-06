<template>
  <aside class="sidebar" :class="{ collapsed: collapsed }">
    <div class="sidebar-brand" @click="collapsed = !collapsed">
      <span class="brand-icon">◆</span>
      <span v-show="!collapsed" class="brand-text">DataAgent</span>
    </div>

    <nav class="sidebar-nav">
      <router-link to="/" class="nav-item" :class="{ active: $route.name === 'Chat' }" :title="collapsed ? '对话分析' : ''">
        <t-icon name="chat" />
        <span v-show="!collapsed">对话分析</span>
      </router-link>
      <router-link to="/datasources" class="nav-item" :class="{ active: $route.name === 'DataSources' }" :title="collapsed ? '数据源' : ''">
        <t-icon name="folder-open" />
        <span v-show="!collapsed">数据源</span>
      </router-link>
      <router-link to="/reports" class="nav-item" :class="{ active: $route.name === 'Reports' }" :title="collapsed ? '报告' : ''">
        <t-icon name="file-paste" />
        <span v-show="!collapsed">报告</span>
      </router-link>
    </nav>

    <div class="sidebar-footer" v-show="!collapsed">
      <t-button variant="text" size="small" @click="collapsed = !collapsed" class="collapse-btn">
        <t-icon name="chevron-left" />
      </t-button>
    </div>
    <div class="sidebar-footer" v-show="collapsed">
      <t-button variant="text" size="small" @click="collapsed = !collapsed" class="collapse-btn">
        <t-icon name="chevron-right" />
      </t-button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const collapsed = ref(localStorage.getItem('sidebar_collapsed') === '1')

// Persist state
const originalToggle = collapsed.value
import { watch } from 'vue'
watch(collapsed, (v) => {
  localStorage.setItem('sidebar_collapsed', v ? '1' : '0')
})
</script>

<style scoped>
.sidebar {
  width: 220px;
  min-width: 220px;
  background: var(--bg-primary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  height: 100vh;
  user-select: none;
  transition: width 0.2s ease;
}

.sidebar.collapsed {
  width: 60px;
  min-width: 60px;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px 24px;
  cursor: pointer;
}

.sidebar.collapsed .sidebar-brand {
  padding: 20px 0;
  justify-content: center;
}

.brand-icon {
  font-size: 24px;
  color: var(--accent);
  filter: drop-shadow(0 0 8px var(--accent-glow));
  flex-shrink: 0;
}

.brand-text {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--text-primary);
  white-space: nowrap;
}

.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0 10px;
}

.sidebar.collapsed .sidebar-nav {
  padding: 0 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: var(--radius);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 10px 0;
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--bg-surface);
  color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent-glow);
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: center;
}

.collapse-btn {
  color: var(--text-muted) !important;
  min-width: unset;
}

.collapse-btn:hover {
  color: var(--text-primary) !important;
}
</style>
