<script lang="ts">
import { ref } from "vue";

// All report readers in this workspace use the same relative scale.
const storageKey = "weekly-report.reader-scale";
const minScale = 0.25;
const maxScale = 3;
function savedScale() {
  try {
    const value = Number(localStorage.getItem(storageKey));
    if (Number.isFinite(value) && value >= minScale && value <= maxScale) return value;
  } catch { /* Storage can be unavailable in an embedded browser. */ }
  return 1;
}
const scale = ref(savedScale());
</script>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, watch } from "vue";
import api from "@/utils/api";
import ReportContent from "./ReportContent.vue";

const props = defineProps<{
  attachmentId: string | null;
  content: Record<string, unknown>;
  author: string;
  meeting?: boolean;
}>();
const firstPage = ref("");
const pageCount = ref(0);
const width = ref(1);
const height = ref(1);
const visible = ref(0);
const loading = ref(false);
const failed = ref(false);
const failedPages = ref<number[]>([]);
const retry = ref(0);
const tail = ref<HTMLElement>();
const viewport = ref<HTMLElement>();
const pageAspects = ref<Record<number, number>>({});
const original = computed(() => "/api/v1/attachments/" + props.attachmentId + "/preview-content");
function rememberPage(page: number, event: Event) {
  const image = event.currentTarget as HTMLImageElement;
  if (image.naturalHeight) pageAspects.value[page] = image.naturalWidth / image.naturalHeight;
}
async function zoomWithWheel(event: WheelEvent) {
  if (!event.ctrlKey) return;
  event.preventDefault();
  const reader = viewport.value;
  if (!reader || !event.deltaY || loading.value) return;

  // A wheel can report pixels, lines, or pages. Limit large bursts on fast wheels.
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? reader.clientHeight : 1;
  const delta = Math.max(-180, Math.min(180, event.deltaY * unit));
  const next = Math.min(maxScale, Math.max(minScale, scale.value * Math.exp(-delta / 650)));
  if (next === scale.value) return;

  const pages = Array.from(reader.querySelectorAll<HTMLElement>(".sheet, .text-paper"));
  const page = pages.find(p => p.getBoundingClientRect().bottom >= event.clientY) ?? pages.at(-1);
  if (!page) return;
  const before = page.getBoundingClientRect();
  if (!before.width || !before.height) return;
  const x = Math.max(0, Math.min(1, (event.clientX - before.left) / before.width));
  const y = Math.max(0, Math.min(1, (event.clientY - before.top) / before.height));
  scale.value = next;
  try { localStorage.setItem(storageKey, String(next)); } catch { /* In-memory zoom still applies. */ }
  await nextTick();
  if (!page.isConnected) return;
  const after = page.getBoundingClientRect();
  reader.scrollLeft += after.left - before.left + x * (after.width - before.width);
  reader.scrollTop += after.top - before.top + y * (after.height - before.height);
}
watch(viewport, (reader, _, cleanup) => {
  if (!reader) return;
  reader.addEventListener("wheel", zoomWithWheel, { passive: false });
  cleanup(() => reader.removeEventListener("wheel", zoomWithWheel));
}, { flush: "post" });
function pagePath(page: number) {
  return "/attachments/" + props.attachmentId + "/presentation-pages/" + page;
}
function resetFirstPage() {
  if (firstPage.value) URL.revokeObjectURL(firstPage.value);
  firstPage.value = "";
}
watch(() => [props.attachmentId, retry.value] as const, ([id], _, cleanup) => {
  const request = new AbortController();
  cleanup(() => request.abort());
  resetFirstPage();
  pageCount.value = 0;
  visible.value = 0;
  pageAspects.value = {};
  viewport.value?.scrollTo(0, 0);
  failedPages.value = [];
  failed.value = false;
  loading.value = !!id;
  if (!id) return;
  async function load() {
    try {
      const {data, headers} = await api.get<Blob>(pagePath(1), { responseType: "blob", signal: request.signal });
      if (request.signal.aborted) return;
      const count = Number(headers["x-page-count"]);
      if (!Number.isInteger(count) || count < 1 || !data.type.startsWith("image/")) throw Error();
      pageCount.value = count;
      width.value = Number(headers["x-page-width"]) || 1;
      height.value = Number(headers["x-page-height"]) || 1;
      visible.value = Math.min(count, 6);
      firstPage.value = URL.createObjectURL(data);
    } catch {
      if (!request.signal.aborted) failed.value = true;
    } finally {
      if (!request.signal.aborted) loading.value = false;
    }
  }
  void load();
}, { immediate: true });

watch(tail, (element, _, cleanup) => {
  if (!element) return;
  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) visible.value = Math.min(pageCount.value, visible.value + 6);
  }, { root: viewport.value, rootMargin: "600px" });
  observer.observe(element);
  cleanup(() => observer.disconnect());
}, { flush: "post" });
onUnmounted(resetFirstPage);
</script>

<template>
  <div class="document-view" :class="{ meeting, 'text-only': !attachmentId }" :style="{ '--factor': scale }">
    <div ref="viewport" class="document-viewport" tabindex="0" role="region" aria-label="周报阅读区"
      aria-description="按住 Ctrl 并滚动鼠标滚轮可放大或缩小周报">
      <p v-if="loading" class="reader-message" role="status">正在打开周报…</p>
      <div v-else-if="firstPage" class="paper-stack">
        <div v-for="n in visible" :key="n" class="sheet" :style="{ '--aspect': pageAspects[n] || width / height }">
          <p v-if="failedPages.includes(n)" class="reader-message">第 {{ n }} 页加载失败。<button class="link-button" @click="retry++">重新加载</button> · <a :href="original" target="_blank" rel="noopener">打开 PDF</a></p>
          <img v-else :src="n === 1 ? firstPage : '/api/v1'+pagePath(n)" :alt="author+'的周报，第 '+n+' 页，共 '+pageCount+' 页'"
            :width="width" :height="height" :loading="n===1 ? 'eager' : 'lazy'" @load="rememberPage(n, $event)" @error="failedPages.push(n)" />
        </div>
        <div v-if="visible<pageCount" :key="'tail-'+visible" ref="tail" aria-hidden="true"></div>
      </div>
      <article v-else class="text-paper">
        <p v-if="failed" class="reader-message">附件预览加载失败。<button class="link-button" @click="retry++">重试</button> · <a :href="original" target="_blank" rel="noopener">打开 PDF</a></p>
        <h1>{{ author }}的周报</h1>
        <ReportContent :content="content"><p class="muted">{{ failed ? '这版周报没有另外填写的正文。' : '这版周报暂无可展示的正文或附件。' }}</p></ReportContent>
      </article>
    </div>
  </div>
</template>

<style scoped>
.document-view { min-width: 0; }
.document-view.meeting { display: flex; flex: 1; min-height: 0; }
.document-viewport {
  width: 100%;
  height: min(74dvh, 880px);
  overflow: auto;
  overflow-anchor: none;
  container-type: size;
  background: #e9eeeb;
  padding: clamp(8px, 1.4vw, 22px);
  scrollbar-gutter: stable both-edges;
}
.meeting .document-viewport { flex: 1; min-width: 0; min-height: 0; height: auto; overscroll-behavior: contain; }
.document-view.text-only:not(.meeting) .document-viewport { height: auto; max-height: 74dvh; container-type: inline-size; }
.document-viewport:focus-visible { outline: 2px solid var(--teal); outline-offset: -2px; }
.sheet, .text-paper { margin-inline: auto; background: white; box-shadow: 0 2px 9px #182e2214; }
.sheet { width: calc(min(100cqw, 100cqh * var(--aspect)) * var(--factor)); }
.sheet + .sheet { margin-top: 12px; }
.sheet img { display: block; width: 100%; height: auto; }
.text-paper {
  width: calc(min(100cqw, 48rem) * var(--factor));
  padding: calc(clamp(14px, 3vw, 36px) * var(--factor));
  font-size: calc(16px * var(--factor));
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.text-paper h1 { font-size: 1.45em; margin: 0 0 1em; }
.text-paper :deep(.el-descriptions__cell) { font-size: calc(16px * var(--factor)); line-height: 1.7; }
.text-paper :deep(.el-descriptions__label) { white-space: nowrap; }
.reader-message { padding: 22px; color: var(--muted); font-size: 14px; }
.text-paper .reader-message { padding: 0 0 12px; }
@media (max-width: 600px) { .document-viewport { scrollbar-gutter: auto; } }
</style>
