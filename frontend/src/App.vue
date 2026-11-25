<template>
  <router-view v-if="isAuthLayout" />

  <div v-else class="app-shell">
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
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import AppSidebar from './components/AppSidebar.vue'

const route = useRoute()
const isAuthLayout = computed(() => route.meta.layout === 'auth')
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

/* ---------------------------------------------------------------- 页面骨架 */

.page {
  padding: 28px 40px 56px;
  max-width: 1240px;
  margin: 0 auto;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
  flex-wrap: wrap;
}

.page-title {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--fg-0);
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-desc {
  font-size: 13px;
  color: var(--fg-2);
  margin-top: 6px;
  max-width: 640px;
  line-height: 1.7;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.section-stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
}

/* ---------------------------------------------------------------- 卡片 */

.card {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.015), transparent);
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--fg-1);
}

.card-title svg {
  color: var(--accent);
}

.card-sub {
  font-size: 12px;
  color: var(--fg-3);
  font-family: var(--font-mono);
}

.card-body {
  padding: 18px;
}

.card-body.tight {
  padding: 12px;
}

/* ---------------------------------------------------------------- 按钮 */

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--fg-1);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--dur-1) var(--ease-out), border-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out), transform var(--dur-1) var(--ease-out);
  white-space: nowrap;
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--accent);
  color: #ffffff;
}
.btn-primary:hover:not(:disabled) {
  background: var(--accent-dim);
}
.btn-primary:active:not(:disabled) {
  transform: scale(0.985);
}

.btn-secondary {
  background: var(--bg-3);
  border-color: var(--border);
  color: var(--fg-1);
}
.btn-secondary:hover:not(:disabled) {
  background: var(--bg-4);
  border-color: var(--border-strong);
}

.btn-ghost {
  color: var(--fg-2);
  border-color: transparent;
}
.btn-ghost:hover:not(:disabled) {
  background: var(--bg-3);
  color: var(--fg-0);
}

.btn-danger {
  color: var(--danger);
  border-color: rgba(248, 113, 113, 0.25);
  background: rgba(248, 113, 113, 0.08);
}
.btn-danger:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.16);
}

.btn-sm {
  padding: 4px 9px;
  font-size: 12px;
  gap: 5px;
}

.btn-block {
  width: 100%;
}

/* ---------------------------------------------------------------- 表单 */

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.label {
  font-size: 12px;
  font-weight: 500;
  color: var(--fg-2);
  display: flex;
  align-items: center;
  gap: 6px;
}

.input,
.select,
.textarea {
  width: 100%;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--fg-0);
  font-family: var(--font-sans);
  font-size: 13px;
  padding: 8px 11px;
  outline: none;
  transition: border-color var(--dur-1) var(--ease-out), box-shadow var(--dur-2) var(--ease-out),
    background var(--dur-1) var(--ease-out);
}

.input:focus,
.select:focus,
.textarea:focus {
  border-color: var(--border-accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
  background: var(--bg-1);
}

.input::placeholder,
.textarea::placeholder {
  color: var(--fg-4);
}

.input:disabled,
.select:disabled,
.textarea:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.textarea {
  resize: vertical;
  min-height: 78px;
  line-height: 1.65;
}

.select {
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12' fill='none'%3E%3Cpath d='M3 4.5L6 7.5L9 4.5' stroke='%2371717A' stroke-width='1.3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  padding-right: 30px;
  cursor: pointer;
}

.hint {
  font-size: 11.5px;
  color: var(--fg-3);
  line-height: 1.6;
}

/* ---------------------------------------------------------------- 提示 / 徽标 */

.alert {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 14px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--bg-2);
  font-size: 13px;
  color: var(--fg-1);
  line-height: 1.6;
}

.alert-body {
  flex: 1;
  min-width: 0;
}

.alert-title {
  font-weight: 600;
  margin-bottom: 2px;
}

.alert-meta {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--fg-3);
  margin-top: 4px;
  word-break: break-all;
}

.alert-error {
  border-color: rgba(248, 113, 113, 0.3);
  background: rgba(248, 113, 113, 0.08);
  color: #FCA5A5;
}
.alert-warn {
  border-color: rgba(251, 191, 36, 0.28);
  background: rgba(251, 191, 36, 0.07);
  color: var(--warning);
}
.alert-info {
  border-color: var(--accent-line);
  background: var(--accent-hi);
  color: #C7D2FE;
}
.alert-success {
  border-color: rgba(74, 222, 128, 0.28);
  background: rgba(74, 222, 128, 0.07);
  color: #86EFAC;
}

.alert-close {
  border: none;
  background: transparent;
  color: inherit;
  opacity: 0.6;
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  padding: 0 2px;
  font-family: var(--font-sans);
}
.alert-close:hover {
  opacity: 1;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 500;
  background: var(--bg-3);
  color: var(--fg-2);
  line-height: 1.6;
}

.badge-accent {
  background: var(--accent-hi);
  color: #A5B4FC;
}
.badge-success {
  background: rgba(74, 222, 128, 0.12);
  color: var(--success);
}
.badge-warn {
  background: rgba(251, 191, 36, 0.12);
  color: var(--warning);
}
.badge-danger {
  background: rgba(248, 113, 113, 0.12);
  color: var(--danger);
}
.badge-mono {
  font-family: var(--font-mono);
}

/* ---------------------------------------------------------------- 骨架屏 / 空态 */

.skeleton {
  position: relative;
  overflow: hidden;
  background: var(--bg-2);
  border-radius: var(--radius-sm);
}

.skeleton::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.05), transparent);
  animation: skeletonSweep 1.5s infinite;
}

@keyframes skeletonSweep {
  100% {
    transform: translateX(100%);
  }
}

.skeleton-line {
  height: 12px;
  margin: 7px 0;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 10px;
  padding: 56px 24px;
  color: var(--fg-2);
}

.empty-icon {
  color: var(--accent);
  opacity: 0.75;
  display: flex;
  margin-bottom: 6px;
}

.empty h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg-1);
}

.empty p {
  font-size: 13px;
  color: var(--fg-3);
  max-width: 400px;
  line-height: 1.7;
}

.spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.22);
  border-top-color: currentColor;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

.spinner.lg {
  width: 22px;
  height: 22px;
  border-width: 2.5px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ---------------------------------------------------------------- 表格 / 文本工具 */

.table-scroll {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13px;
}

.data-table th {
  text-align: left;
  font-size: 11.5px;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--fg-3);
  font-weight: 600;
  padding: 10px 14px;
  background: var(--bg-2);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.data-table td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--fg-1);
  vertical-align: middle;
}

.data-table tbody tr:last-child td {
  border-bottom: none;
}

.data-table tbody tr:hover td {
  background: rgba(255, 255, 255, 0.018);
}

.mono {
  font-family: var(--font-mono);
}

.muted {
  color: var(--fg-3);
}

.truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ---------------------------------------------------------------- Markdown */

.markdown-content {
  line-height: 1.75;
  font-size: 14px;
  color: var(--fg-1);
  word-break: break-word;
}
.markdown-content > :first-child {
  margin-top: 0;
}
.markdown-content > :last-child {
  margin-bottom: 0;
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
  color: #A5B4FC;
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
.markdown-content pre code.hljs {
  background: transparent;
  padding: 0;
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
