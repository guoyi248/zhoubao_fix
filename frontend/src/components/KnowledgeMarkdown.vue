<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useRoute } from "vue-router";
import { headingPrefix, renderKnowledgeMarkdown } from "@/utils/knowledgeMarkdown";
import { renderKnowledgeDiagrams } from "@/utils/knowledgeDiagrams";
const props = defineProps<{
    source: string;
    title?: string;
    preview?: boolean;
}>();
const route = useRoute();
const prose = ref<HTMLDivElement>();
const html = computed(() => renderKnowledgeMarkdown(props.source, props.title, props.preview));
const headings = ref<{
    id: string;
    title: string;
    level: number;
}[]>([]);
const activeHeading = ref("");
const enlargedImage = ref("");
let observer: IntersectionObserver | undefined;
function enhanceReading() {
    observer?.disconnect();
    if (!prose.value || props.preview)
        return;
    const nodes = Array.from(prose.value.querySelectorAll<HTMLHeadingElement>("h1[id],h2[id],h3[id]"));
    headings.value = nodes.map(node => ({ id: node.id, title: node.textContent || "", level: Number(node.tagName[1]) }));
    activeHeading.value = nodes[0]?.id || "";
    observer = new IntersectionObserver(entries => {
        const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0])
            activeHeading.value = visible[0].target.id;
    }, { rootMargin: "-5% 0px -60% 0px" });
    nodes.forEach(node => observer!.observe(node));
    for (const block of prose.value.querySelectorAll("pre")) {
        if (block.querySelector(".code-copy") || block.closest(".knowledge-diagram"))
            continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "code-copy";
        button.textContent = "复制";
        button.setAttribute("aria-label", "复制代码");
        button.onclick = async () => {
            try {
                await navigator.clipboard.writeText(block.querySelector("code")?.textContent || "");
                ElMessage.success("代码已复制");
            }
            catch {
                ElMessage.error("复制失败，请选中代码手动复制");
            }
        };
        block.prepend(button);
    }
}
function jump(id: string) {
    locate("#" + id);
    activeHeading.value = id;
    const url = new URL(window.location.href);
    url.hash = id;
    window.history.replaceState(window.history.state, "", url);
}
function locate(hash: string) {
    let id;
    try {
        id = decodeURIComponent(hash.slice(1));
    }
    catch {
        return;
    }
    if (!id)
        return;
    const anchor = document.getElementById(id) || document.getElementById(headingPrefix + id);
    if (anchor && prose.value?.contains(anchor))
        anchor.scrollIntoView({ block: "start" });
}
async function restoreFragment() {
    if (!props.preview && route.hash) {
        await nextTick();
        locate(route.hash);
    }
}
function previewLink(event: MouseEvent) {
    if (!(event.target instanceof Element))
        return;
    if (!props.preview && event.target instanceof HTMLImageElement) {
        enlargedImage.value = event.target.currentSrc || event.target.src;
        return;
    }
    if (!props.preview)
        return;
    const href = event.target.closest("a")?.getAttribute("href");
    if (href?.startsWith("#")) {
        event.preventDefault();
        locate(href);
    }
}
async function enhanceDiagrams() {
    if (prose.value)
        await renderKnowledgeDiagrams(prose.value);
    enhanceReading();
}
onMounted(() => {
    enhanceDiagrams();
    restoreFragment();
});
watch(html, enhanceDiagrams, { flush: "post" });
watch(() => [route.hash, html.value], restoreFragment, { flush: "post" });
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div class="knowledge-reader" :class="{'has-outline': !preview && headings.length>1}">
    <div ref="prose" class="knowledge-prose" @click="previewLink" v-html="html"></div>
    <nav v-if="!preview && headings.length>1" class="article-outline" aria-label="文章目录"><strong>本页目录</strong><a v-for="heading in headings" :key="heading.id" :href="'#'+heading.id" :class="{active:activeHeading===heading.id}" :style="{paddingLeft:(heading.level>2?12:0)+'px'}" @click.prevent="jump(heading.id)">{{ heading.title }}</a></nav>
  </div>
  <el-dialog :model-value="!!enlargedImage" @close="enlargedImage=''" class="knowledge-lightbox" width="min(1100px,96vw)" title="图片预览" append-to-body><img v-if="enlargedImage" :src="enlargedImage" alt="放大预览" style="display:block;max-width:100%;height:auto;margin:auto" /></el-dialog>
</template>

<style scoped>
.knowledge-reader{min-width:0}.knowledge-reader.has-outline{display:grid;grid-template-columns:minmax(0,1fr) 150px;gap:28px;align-items:start}.article-outline{position:sticky;top:22px;max-height:65vh;overflow:auto;border-left:1px solid var(--line);padding-left:14px;display:grid;gap:9px;font-size:12px}.article-outline strong{color:var(--muted);font-weight:500;margin-bottom:4px}.article-outline a{color:var(--muted);line-height:1.5;text-decoration:none;overflow-wrap:anywhere}.article-outline a.active{color:var(--teal);font-weight:650}.knowledge-prose{min-width:0}.knowledge-prose :deep(pre){position:relative}.knowledge-prose :deep(.code-copy){float:right;border:1px solid var(--line);border-radius:5px;padding:3px 8px;color:var(--teal);background:var(--paper);font:12px sans-serif;cursor:pointer;margin:0 0 7px 10px}.knowledge-prose :deep(img){cursor:zoom-in}@media(max-width:1100px){.knowledge-reader.has-outline{grid-template-columns:minmax(0,1fr)}.article-outline{position:static;grid-row:1;max-height:160px;border:1px solid var(--line);padding:12px;border-radius:8px}}
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
