<template>
  <Teleport to="body">
    <transition name="modal">
      <div v-if="open" class="modal-mask" @mousedown.self="onMaskDown">
        <div
          class="modal"
          :class="[`modal-${size}`, { 'modal-scroll': scrollBody }]"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
        >
          <header class="modal-head">
            <div class="modal-head-text">
              <h3 class="modal-title">{{ title }}</h3>
              <p v-if="subtitle" class="modal-sub">{{ subtitle }}</p>
            </div>
            <button class="modal-close" type="button" aria-label="关闭" @click="close">✕</button>
          </header>
          <div class="modal-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="modal-foot">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    subtitle?: string
    size?: 'sm' | 'md' | 'lg'
    closeOnMask?: boolean
    scrollBody?: boolean
  }>(),
  { size: 'md', closeOnMask: true, scrollBody: false, subtitle: '' },
)

const emit = defineEmits<{ close: [] }>()

function close(): void {
  emit('close')
}

function onMaskDown(): void {
  if (props.closeOnMask) close()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') close()
}

watch(
  () => props.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
  { immediate: true },
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(5, 5, 7, 0.72);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}

.modal {
  width: 100%;
  background: var(--bg-1);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 48px);
}

.modal-sm {
  max-width: 420px;
}
.modal-md {
  max-width: 620px;
}
.modal-lg {
  max-width: 860px;
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--border);
}

.modal-head-text {
  min-width: 0;
}

.modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg-0);
  letter-spacing: -0.01em;
}

.modal-sub {
  font-size: 12px;
  color: var(--fg-3);
  margin-top: 4px;
  line-height: 1.6;
}

.modal-close {
  border: none;
  background: transparent;
  color: var(--fg-3);
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  transition: all var(--dur-1) var(--ease-out);
  flex-shrink: 0;
}

.modal-close:hover {
  background: var(--bg-3);
  color: var(--fg-0);
}

.modal-body {
  padding: 20px 22px;
  overflow-y: auto;
  min-height: 0;
}

.modal-scroll .modal-body {
  max-height: 60vh;
}

.modal-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 22px 18px;
  border-top: 1px solid var(--border);
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity var(--dur-2) var(--ease-out);
}
.modal-enter-active .modal,
.modal-leave-active .modal {
  transition: transform var(--dur-2) var(--ease-out);
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from .modal,
.modal-leave-to .modal {
  transform: translateY(8px) scale(0.99);
}
</style>
