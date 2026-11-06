<template>
  <div class="app-shell">
    <AppSidebar />
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="view-fade" mode="out-in">
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
:root {
  --bg-0: #0A0A0B;
  --bg-1: #111113;
  --bg-2: #17171A;
  --bg-3: #1F1F23;
  --bg-4: #2A2A30;

  --fg-0: #FAFAFA;
  --fg-1: #E4E4E7;
  --fg-2: #A1A1AA;
  --fg-3: #71717A;
  --fg-4: #3F3F46;

  --accent: #6366F1;
  --accent-dim: #4F46E5;
  --accent-hi: rgba(99, 102, 241, 0.08);
  --accent-line: rgba(99, 102, 241, 0.3);
  --accent-glow: rgba(99, 102, 241, 0.15);

  --danger: #F87171;
  --success: #4ADE80;
  --warning: #FBBF24;

  --border: rgba(255, 255, 255, 0.06);
  --border-strong: rgba(255, 255, 255, 0.1);
  --border-accent: rgba(99, 102, 241, 0.35);

  --radius-sm: 6px;
  --radius: 8px;
  --radius-lg: 12px;

  --font-sans: 'Geist', 'PingFang SC', 'Microsoft YaHei', system-ui, -apple-system, sans-serif;
  --font-mono: 'Geist Mono', 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;

  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease: cubic-bezier(0.4, 0, 0.2, 1);
  --dur-1: 120ms;
  --dur-2: 200ms;
  --dur-3: 300ms;
}

*,
*::before,
*::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  font-family: var(--font-sans);
  background: var(--bg-0);
  color: var(--fg-0);
  overflow: hidden;
  height: 100vh;
  font-size: 14px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  font-feature-settings: 'cv02', 'cv03', 'cv04', 'cv11';
}

#app {
  height: 100vh;
}

::selection {
  background: var(--accent-glow);
  color: var(--fg-0);
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.14);
}

.app-shell {
  display: flex;
  height: 100vh;
  background: var(--bg-0);
}

.app-main {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-0);
  position: relative;
}

.app-main::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border-strong), transparent);
  pointer-events: none;
  z-index: 10;
}

.view-fade-enter-active,
.view-fade-leave-active {
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out);
}
.view-fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.view-fade-leave-to {
  opacity: 0;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--dur-2) var(--ease-out);
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.markdown-content {
  line-height: 1.75;
  font-size: 14px;
  color: var(--fg-1);
}
.markdown-content h1 {
  font-size: 1.4em;
  margin: 20px 0 10px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--fg-0);
}
.markdown-content h2 {
  font-size: 1.2em;
  margin: 18px 0 8px;
  font-weight: 600;
  color: var(--fg-0);
}
.markdown-content h3 {
  font-size: 1.08em;
  margin: 16px 0 6px;
  font-weight: 600;
  color: var(--fg-1);
}
.markdown-content h4 {
  font-size: 1em;
  margin: 14px 0 6px;
  font-weight: 600;
  color: var(--fg-2);
}
.markdown-content p {
  margin: 8px 0;
  line-height: 1.75;
  color: var(--fg-1);
}
.markdown-content ul,
.markdown-content ol {
  margin: 12px 0;
  padding-left: 22px;
}
.markdown-content li {
  margin: 6px 0;
  line-height: 1.7;
  color: var(--fg-2);
}
.markdown-content li::marker {
  color: var(--accent);
}
.markdown-content code {
  background: var(--bg-2);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.85em;
  color: var(--accent);
}
.markdown-content pre {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 20px;
  overflow-x: auto;
  margin: 14px 0;
}
.markdown-content pre code {
  background: none;
  padding: 0;
  color: var(--fg-1);
  font-size: 13px;
  line-height: 1.6;
  border: none;
}
.markdown-content blockquote {
  border-left: 2px solid var(--accent);
  padding: 12px 16px;
  margin: 14px 0;
  background: var(--accent-hi);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  color: var(--fg-2);
}
.markdown-content table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  margin: 16px 0;
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--border);
}
.markdown-content th,
.markdown-content td {
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.markdown-content th {
  background: var(--bg-2);
  color: var(--fg-2);
  font-weight: 600;
  font-size: 0.9em;
}
.markdown-content tr:last-child td {
  border-bottom: none;
}
.markdown-content strong {
  color: var(--fg-0);
  font-weight: 600;
}
.markdown-content a {
  color: var(--accent);
  text-decoration: none;
  transition: color var(--dur-1);
}
.markdown-content a:hover {
  color: var(--accent-dim);
}
.markdown-content hr {
  border: none;
  height: 1px;
  background: var(--border);
  margin: 20px 0;
}
</style>
