<script setup lang="ts">
import { ref, watch } from "vue";
import PresentationDocument from "./PresentationDocument.vue";
import api from "@/utils/api";
import type { ReportRow } from "@/utils/week";

const props = defineProps<{ row?: ReportRow; admin: boolean }>();
defineEmits<{ close: [] }>();
interface Original {
  confirmed_pdf_attachment_id: string | null;
  structured_content_json: Record<string, unknown>;
}
const original = ref<Original>();
const error = ref("");
const retry = ref(0);
watch(() => [props.row, retry.value] as const, async ([row], _, cleanup) => {
  const request = new AbortController();
  cleanup(() => request.abort());
  original.value = undefined;
  error.value = "";
  if (!row?.current_revision_id) return;
  try {
    const prefix = props.admin ? "/admin/reports/" : "/me/reports/";
    const { data } = await api.get<Original>(prefix + row.id + "/revisions/" + row.current_revision_id, { signal: request.signal });
    if (!request.signal.aborted) original.value = data;
  } catch (cause) {
    if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : "周报读取失败";
  }
}, { immediate: true });
</script>

<template>
  <el-drawer :model-value="!!row" :title="row?.owner_name + ' · 周报原文'" size="min(860px, 100%)" @close="$emit('close')">
    <template v-if="row">
      <p v-if="error" role="alert">{{ error }} <button class="link-button" @click="retry++">重新打开</button></p>
      <PresentationDocument v-else-if="original" :author="row.owner_name"
        :attachment-id="original.confirmed_pdf_attachment_id" :content="original.structured_content_json" />
      <p v-else class="muted" role="status">正在打开周报…</p>
    </template>
  </el-drawer>
</template>
