<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowLeft, FullScreen } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import api from "@/utils/api";
import { enterPresentationFullscreen, exitPresentationFullscreen } from "@/utils/presentation";
import type { Overview } from "@/utils/week";
import PresentationDocument from "@/components/report/PresentationDocument.vue";

interface Original {
  attachmentId: string | null;
  content: Record<string, unknown>;
}
interface Entry {
  name: string;
  reportId: string;
  revisionId: string;
  original?: Original;
}
interface Snapshot {
  member_name: string;
  report_id: string;
  report_revision_id: string;
  confirmed_pdf_attachment_id: string | null;
  structured_content: Record<string, unknown>;
}
const route = useRoute();
const router = useRouter();
const roster = ref<Entry[]>([]);
const selected = ref(0);
const periodId = ref("");
const periodName = ref("");
const listError = ref("");
const sourceError = ref("");
const listLoading = ref(true);
const fullscreen = ref(false);
const nativeAvailable = !!document.fullscreenEnabled;
const reload = ref(0);
const retrySource = ref(0);
const current = computed(() => roster.value[selected.value]);

watch(() => [route.name, route.params.id, route.query.period, route.query.revision, reload.value] as const, async ([name, id, period, revision], _, cleanup) => {
  const request = new AbortController();
  cleanup(() => request.abort());
  listLoading.value = true;
  listError.value = "";
  roster.value = [];
  selected.value = 0;
  periodId.value = "";
  periodName.value = "";
  try {
    if (name === "meeting-mode" && id) {
      const { data } = await api.get("/admin/meetings/" + id, { signal: request.signal });
      if (request.signal.aborted) return;
      periodId.value = data.reporting_period_id;
      periodName.value = data.period_label;
      roster.value = data.snapshots.map((s: Snapshot) => ({
        name: s.member_name, reportId: s.report_id, revisionId: s.report_revision_id,
        original: { attachmentId: s.confirmed_pdf_attachment_id, content: s.structured_content },
      }));
    } else {
      const { data } = await api.get<Overview>("/admin/reports/overview", {
        params: typeof period === "string" ? { period } : {}, signal: request.signal,
      });
      if (request.signal.aborted) return;
      periodId.value = data.period.id;
      periodName.value = data.period.iso_year + " 年 · 第 " + data.period.iso_week + " 周";
      roster.value = data.submitted.flatMap(r => r.current_revision_id ? [{
        name: r.owner_name, reportId: r.id, revisionId: r.current_revision_id,
      }] : []);
    }
    if (typeof revision === "string") {
      selected.value = Math.max(0, roster.value.findIndex(entry => entry.revisionId === revision));
    }
  } catch (e: any) {
    if (!request.signal.aborted) listError.value = e.message || "周报名单加载失败";
  } finally {
    if (!request.signal.aborted) listLoading.value = false;
  }
}, { immediate: true });

watch(() => [current.value, retrySource.value] as const, async ([entry], _, cleanup) => {
  const request = new AbortController();
  cleanup(() => request.abort());
  sourceError.value = "";
  if (!entry || entry.original) return;
  try {
    const { data } = await api.get("/admin/reports/" + entry.reportId + "/revisions/" + entry.revisionId, { signal: request.signal });
    if (!request.signal.aborted) entry.original = { attachmentId: data.confirmed_pdf_attachment_id, content: data.structured_content_json };
  } catch (e: any) {
    if (!request.signal.aborted) sourceError.value = e.message || "周报原文加载失败";
  }
}, { immediate: true, flush: "post" });

function choose(index: number) {
  if (index < 0 || index >= roster.value.length) return;
  selected.value = index;
  document.getElementById("speaker-" + index)?.scrollIntoView({ block: "nearest" });
}
function shortcuts(event: KeyboardEvent) {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const offset = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
  if (!offset) return;
  event.preventDefault();
  choose(selected.value + offset);
}
function syncFullscreen() { fullscreen.value = !!document.fullscreenElement; }
async function toggleFullscreen() {
  if (fullscreen.value) await exitPresentationFullscreen();
  else if (!await enterPresentationFullscreen()) ElMessage.info("当前浏览器已使用整页展示");
}
function leave() {
  void router.push({ path: "/admin/reports", query: periodId.value ? { period: periodId.value } : {} });
}
onMounted(() => {
  syncFullscreen();
  document.addEventListener("fullscreenchange", syncFullscreen);
  document.addEventListener("keydown", shortcuts);
});
onUnmounted(() => {
  document.removeEventListener("fullscreenchange", syncFullscreen);
  document.removeEventListener("keydown", shortcuts);
  void exitPresentationFullscreen();
});
</script>

<template>
  <main class="presentation">
    <aside class="present-rail">
      <header><h1>组会展示</h1><p v-if="periodName">{{ periodName }}</p></header>
      <nav aria-label="切换成员周报">
        <button v-for="(entry,i) in roster" :id="'speaker-'+i" :key="entry.revisionId" type="button"
          :class="{active:i===selected}" :aria-current="i===selected ? 'true' : undefined" @click="choose(i)">{{ entry.name }}</button>
      </nav>
      <footer>
        <button v-if="nativeAvailable" @click="toggleFullscreen"><el-icon><FullScreen /></el-icon>{{ fullscreen?'退出全屏':'浏览器全屏' }}</button>
        <button @click="leave"><el-icon><ArrowLeft /></el-icon>退出展示</button>
      </footer>
    </aside>
    <section class="reader" :aria-label="current ? current.name+'的周报原文' : '周报原文'">
      <p v-if="listError" class="notice">{{ listError }} <button class="link-button" @click="reload++">重试</button></p>
      <p v-else-if="listLoading" class="notice" role="status">正在加载周报名单…</p>
      <p v-else-if="!current" class="notice">这一周还没有已提交的周报。</p>
      <p v-else-if="sourceError" class="notice">{{ sourceError }} <button class="link-button" @click="retrySource++">重试</button></p>
      <PresentationDocument v-else-if="current.original" :key="current.revisionId" meeting :author="current.name"
        :attachment-id="current.original.attachmentId" :content="current.original.content" />
      <p v-else class="notice" role="status">正在打开周报…</p>
    </section>
  </main>
</template>

<style scoped>
.presentation{position:fixed;inset:0;display:grid;grid-template-rows:minmax(0,1fr);grid-template-columns:clamp(142px,13vw,205px) minmax(0,1fr);background:#e9eeeb;color:var(--ink);overflow:hidden}
.present-rail{min-height:0;display:flex;flex-direction:column;background:#fff;border-right:1px solid #d5e0d9;padding:22px 10px 10px}
.present-rail header{padding:0 10px 18px;border-bottom:1px solid var(--line)}.present-rail h1{font-size:17px}.present-rail header p{margin-top:5px;color:var(--muted);font-size:12px}
.present-rail nav{min-height:0;flex:1;overflow:auto;padding:12px 0}.present-rail button{display:flex;align-items:center;gap:8px;width:100%;padding:10px;border:0;border-radius:8px;background:transparent;text-align:left;color:var(--ink);font-size:14px;overflow-wrap:anywhere}.present-rail button:hover{background:#f1f6f2}.present-rail nav button.active{background:#dfefe5;color:#076646;font-weight:700;box-shadow:inset 3px 0 #167552}.present-rail footer{border-top:1px solid var(--line);padding-top:6px}.present-rail footer button{font-size:12px;color:var(--muted)}.reader{display:flex;flex-direction:column;min-height:0;min-width:0;overflow:hidden}.notice{padding:24px;color:var(--muted)}
@media(max-width:600px){.presentation{grid-template-columns:86px minmax(0,1fr)}.present-rail{padding:12px 4px 6px}.present-rail header{padding:0 4px 10px}.present-rail header h1{font-size:14px}.present-rail header p{font-size:10px}.present-rail button{padding:9px 7px;font-size:13px}.present-rail footer button{font-size:11px;gap:3px}}
</style>
