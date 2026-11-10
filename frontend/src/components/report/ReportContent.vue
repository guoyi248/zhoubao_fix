<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ content?: Record<string, unknown> | null }>();
const fields = [
  ["completed", "本周完成"], ["results", "关键结果"], ["risks", "问题与风险"],
  ["blockers", "需要协助"], ["next_week", "下周计划"],
] as const;

const sections = computed(() => fields.flatMap(([key, label]) => {
  const value = props.content?.[key];
  const items = Array.isArray(value) ? value : [value];
  const lines = items.filter((item): item is string => typeof item === "string" && !!item.trim());
  return lines.length ? [{ key, label, lines }] : [];
}));
</script>

<template>
  <el-descriptions v-if="sections.length" :column="1" border>
    <el-descriptions-item v-for="section in sections" :key="section.key" :label="section.label">
      <ul><li v-for="(line, i) in section.lines" :key="i">{{ line }}</li></ul>
    </el-descriptions-item>
  </el-descriptions>
  <slot v-else />
</template>

<style scoped>
ul { padding-left: 1.2em; }
li { white-space: pre-wrap; }
</style>
