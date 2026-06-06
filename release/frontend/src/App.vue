<template>
  <div class="app-shell">
    <AppSidebar />
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup lang="ts">
import AppSidebar from './components/AppSidebar.vue'
</script>

<style>
/* === Global Reset & Variables === */
:root {
  --bg-primary: #0f1923;
  --bg-secondary: #182533;
  --bg-surface: #1e3044;
  --bg-hover: #253d56;
  --text-primary: #e8edf2;
  --text-secondary: #8fa3b8;
  --text-muted: #5a7188;
  --accent: #4da6ff;
  --accent-glow: rgba(77, 166, 255, 0.25);
  --danger: #ff6b6b;
  --success: #4ecdc4;
  --warning: #ffd93d;
  --border: #2a4259;
  --radius: 8px;
  --radius-lg: 12px;
  --shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
  --font-sans: 'Inter', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-sans);
  background: var(--bg-primary);
  color: var(--text-primary);
  overflow: hidden;
  height: 100vh;
}

#app {
  height: 100vh;
}

.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.app-main {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-secondary);
}

/* Scrollbar */
.app-main::-webkit-scrollbar {
  width: 6px;
}
.app-main::-webkit-scrollbar-track {
  background: transparent;
}
.app-main::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}

/* Transition */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Markdown Content */
.markdown-content h1 { font-size: 1.4em; margin: 16px 0 8px; color: var(--text-primary); }
.markdown-content h2 { font-size: 1.2em; margin: 14px 0 6px; color: var(--accent); }
.markdown-content h3 { font-size: 1.05em; margin: 12px 0 4px; color: var(--text-secondary); }
.markdown-content p { margin: 6px 0; line-height: 1.7; }
.markdown-content ul, .markdown-content ol { margin: 8px 0; padding-left: 20px; }
.markdown-content li { margin: 4px 0; line-height: 1.6; }
.markdown-content code {
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.9em;
  color: var(--accent);
}
.markdown-content pre {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 16px;
  overflow-x: auto;
  margin: 10px 0;
}
.markdown-content pre code {
  background: none;
  padding: 0;
  color: var(--text-primary);
}
.markdown-content blockquote {
  border-left: 3px solid var(--accent);
  padding: 8px 16px;
  margin: 10px 0;
  background: var(--bg-surface);
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--text-secondary);
}
.markdown-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
}
.markdown-content th, .markdown-content td {
  border: 1px solid var(--border);
  padding: 8px 12px;
  text-align: left;
}
.markdown-content th {
  background: var(--bg-surface);
  color: var(--accent);
  font-weight: 600;
}
.markdown-content strong {
  color: var(--text-primary);
}
</style>
