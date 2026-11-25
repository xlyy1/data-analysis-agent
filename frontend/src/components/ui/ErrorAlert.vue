<template>
  <div v-if="error" class="alert alert-error" role="alert">
    <svg class="alert-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.4" stroke="currentColor" stroke-width="1.2" />
      <path d="M8 4.8v4M8 11.2v.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
    </svg>
    <div class="alert-body">
      <div v-if="title" class="alert-title">{{ title }}</div>
      <div>{{ error.message }}</div>
      <div v-if="error.requestId" class="alert-meta">request_id: {{ error.requestId }}（报障时请附上）</div>
      <div v-else-if="error.code" class="alert-meta">错误码: {{ error.code }}</div>
      <div v-if="retryable" class="alert-action">
        <button class="btn btn-sm btn-secondary" type="button" @click="$emit('retry')">重试</button>
      </div>
    </div>
    <button v-if="dismissible" class="alert-close" type="button" aria-label="关闭" @click="$emit('dismiss')">
      ✕
    </button>
  </div>
</template>

<script setup lang="ts">
import type { ApiError } from '../../api/client'

withDefaults(
  defineProps<{
    error: ApiError | null
    title?: string
    retryable?: boolean
    dismissible?: boolean
  }>(),
  { title: '', retryable: false, dismissible: true },
)

defineEmits<{ retry: []; dismiss: [] }>()
</script>

<style scoped>
.alert-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

.alert-action {
  margin-top: 8px;
}
</style>
