<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { headingPrefix, renderKnowledgeMarkdown } from "@/utils/knowledgeMarkdown";
import { renderKnowledgeDiagrams } from "@/utils/knowledgeDiagrams";

const props = defineProps<{ source: string; title?: string; preview?: boolean }>();
const route = useRoute();
const prose = ref<HTMLDivElement>();
const html = computed(() => renderKnowledgeMarkdown(props.source, props.title, props.preview));
function locate(hash: string) {
  let id;
  try { id = decodeURIComponent(hash.slice(1)); } catch { return; }
  if (!id) return;
  const anchor = document.getElementById(id) || document.getElementById(headingPrefix + id);
  if (anchor && prose.value?.contains(anchor)) anchor.scrollIntoView({ block: "start" });
}
async function restoreFragment() {
  if (!props.preview && route.hash) { await nextTick(); locate(route.hash); }
}
function previewLink(event: MouseEvent) {
  if (!props.preview || !(event.target instanceof Element)) return;
  const href = event.target.closest("a")?.getAttribute("href");
  if (href?.startsWith("#")) { event.preventDefault(); locate(href); }
}
async function enhanceDiagrams() {
  if (prose.value) await renderKnowledgeDiagrams(prose.value);
}
onMounted(() => { enhanceDiagrams(); restoreFragment(); });
watch(html, enhanceDiagrams, { flush: "post" });
watch(() => [route.hash, html.value], restoreFragment, { flush: "post" });
</script>

<template>
  <div ref="prose" class="knowledge-prose" @click="previewLink" v-html="html"></div>
</template>

<style scoped>
.knowledge-prose { font-size:15px; line-height:1.85; overflow-wrap:anywhere; color:var(--ink); }
.knowledge-prose :deep(h1), .knowledge-prose :deep(h2), .knowledge-prose :deep(h3) { line-height:1.5; margin:1.4em 0 .45em; }
.knowledge-prose :deep(h1) { font-size:1.65em; }
.knowledge-prose :deep(h2) { font-size:1.3em; }
.knowledge-prose :deep(h3) { font-size:1.13em; }
.knowledge-prose :deep(:is(h4,h5,h6)) { margin:1.2em 0 .4em; font-size:1em; }
.knowledge-prose :deep([id]) { scroll-margin-top:16px; }
.knowledge-prose :deep(a) { text-decoration:underline; text-underline-offset:3px; }
.knowledge-prose :deep(p), .knowledge-prose :deep(ul), .knowledge-prose :deep(ol), .knowledge-prose :deep(pre), .knowledge-prose :deep(table), .knowledge-prose :deep(blockquote) { margin:.7em 0; }
.knowledge-prose :deep(ul), .knowledge-prose :deep(ol) { padding-left:1.65em; }
.knowledge-prose :deep(li + li) { margin-top:.2em; }
.knowledge-prose :deep(blockquote) { border-left:3px solid #b6d0b9; padding:.1em 1em; color:var(--muted); }
.knowledge-prose :deep(code) { font-family:"IBM Plex Mono",Consolas,monospace; font-size:.9em; background:rgb(199 218 197 / 44%); padding:.12em .35em; border-radius:3px; }
.knowledge-prose :deep(pre) { overflow-x:auto; background:rgb(237 245 238 / 72%); border:1px solid var(--line); padding:14px 17px; border-radius:7px; line-height:1.55; }
.knowledge-prose :deep(pre code) { background:none; padding:0; white-space:pre; }
.knowledge-prose :deep(table) { display:block; width:max-content; max-width:100%; overflow-x:auto; border-collapse:collapse; background:rgb(255 255 255 / 34%); }
.knowledge-prose :deep(td), .knowledge-prose :deep(th) { border:1px solid var(--line); padding:5px 12px; text-align:left; }
.knowledge-prose :deep(th) { background:rgb(212 229 212 / 62%); }
.knowledge-prose :deep(hr) { border:0; border-top:1px solid var(--line); margin:1.25em 0; }
.knowledge-prose :deep(img) { max-width:100%; height:auto; }
.knowledge-prose :deep(.knowledge-diagram) { margin:1em 0; padding:12px; border:1px solid var(--line); border-radius:7px; background:rgb(255 255 255 / 49%); }
.knowledge-prose :deep(.knowledge-diagram img) { display:block; margin:auto; }
.knowledge-prose :deep(.knowledge-diagram summary) { color:var(--muted); font-size:12px; cursor:pointer; }
.knowledge-prose :deep(.knowledge-diagram details) { margin-top:8px; }
.knowledge-prose :deep(> :first-child) { margin-top:0; }
</style>
