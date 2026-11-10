<script setup lang="ts">
import { computed, ref, watch } from "vue";
import api from "@/utils/api";
import PresentationDocument from "./PresentationDocument.vue";
import ProgressSummary from "./ProgressSummary.vue";
import { dateText, reportStatus, type Period } from "@/utils/week";

interface Revision {
  id: string;
  revision_no: number;
  submitted_at: string;
  reason: string;
  confirmed_pdf_attachment_id: string | null;
}
interface Report {
  owner_name: string;
  owner_department: string;
  status: string;
  period: Period;
  draft_content_json: Record<string, unknown>;
  revisions: Revision[];
}
const props = defineProps<{ reportId: string; adminView?: boolean }>();
const prefix = computed(() => props.adminView ? "/admin/reports" : "/me/reports");
const report = ref<Report>();
const revisionId = ref("");
const content = ref<Record<string, unknown>>({});
const previewId = ref("");
const showText = ref(false);
const section = ref<"original" | "summary">("original");
const hasText = computed(() => Object.values(content.value || {}).some(value =>
  (Array.isArray(value) ? value : [value]).some(line => typeof line === "string" && line.trim())));
const error = ref("");
const loading = ref(true);
const currentRevision = computed(() => report.value?.revisions.find(rev => rev.id === revisionId.value));
let generation = 0;

async function loadVersion(revision: Revision) {
  const token = ++generation;
  revisionId.value = revision.id;
  loading.value = true;
  error.value = "";
  content.value = {};
  previewId.value = "";
  showText.value = false;
  try {
    const { data } = await api.get(prefix.value + "/" + props.reportId + "/revisions/" + revision.id);
    if (token !== generation) return;
    content.value = data.structured_content_json;
    previewId.value = data.confirmed_pdf_attachment_id || "";
  } catch (e: any) {
    if (token === generation) error.value = e.message || "读取这版周报失败";
  } finally {
    if (token === generation) loading.value = false;
  }
}
function chooseVersion(id: string) {
  const version = report.value?.revisions.find(rev => rev.id === id);
  if (version) void loadVersion(version);
}
async function load() {
  const token = ++generation;
  loading.value = true;
  report.value = undefined;
  section.value = "original";
  error.value = "";
  revisionId.value = "";
  previewId.value = "";
  content.value = {};
  showText.value = false;
  try {
    const { data } = await api.get<Report>(prefix.value + "/" + props.reportId);
    if (token !== generation) return;
    report.value = data;
    const latest = data.revisions[0];
    if (latest) {
      await loadVersion(latest);
    } else {
      content.value = data.draft_content_json;
      if (!props.adminView) {
        const files = await api.get("/me/reports/" + props.reportId + "/attachments");
        if (token === generation) previewId.value = files.data.find((a: any) => a.preview_status?.available)?.id || "";
      }
    }
  } catch (e: any) {
    if (token === generation) error.value = e.message || "周报加载失败";
  } finally {
    if (token === generation) loading.value = false;
  }
}
watch(() => [props.reportId, props.adminView], load, { immediate: true });
</script>
<template>
  <article class="detail" v-loading="loading">
    <el-alert v-if="error" :closable="false" type="error">
      <template #title>{{ error }} <button class="link-button" @click="currentRevision ? loadVersion(currentRevision) : load()">重试</button></template>
    </el-alert>
    <template v-if="report">
      <header class="panel-head">
        <div><h2>{{ report.owner_name }}的周报</h2><p class="page-sub">{{ report.period.iso_year }} 年 · 第 {{ report.period.iso_week }} 周 {{ report.owner_department ? ' · '+report.owner_department : '' }}</p></div>
        <span class="pill" :class="{good:report.revisions.length}">{{ reportStatus[report.status] }}</span>
      </header>
      <div v-if="currentRevision" class="version-bar">
        <el-select v-if="report.revisions.length>1" :model-value="revisionId" aria-label="查看修订版本" style="width:136px" @change="chooseVersion">
          <el-option v-for="rev in report.revisions" :key="rev.id" :label="'第 '+rev.revision_no+' 版'" :value="rev.id" />
        </el-select>
        <strong v-else>第 {{ currentRevision.revision_no }} 版</strong>
        <span>{{ dateText(currentRevision.submitted_at,true) }} 提交</span>
      </div>
      <p v-if="currentRevision?.reason" class="muted">更正说明 · {{ currentRevision.reason }}</p>
      <div v-if="revisionId" class="tabline content-choices" role="group" aria-label="查看内容">
        <button type="button" :aria-pressed="section==='original'" :class="{chosen:section==='original'}" @click="section='original'">周报原文</button>
        <button type="button" :aria-pressed="section==='summary'" :class="{chosen:section==='summary'}" @click="section='summary'">AI 总结</button>
      </div>
      <ProgressSummary v-if="section==='summary' && revisionId" :revision-id="revisionId" />
      <section v-else-if="!loading && (previewId || hasText)" class="original">
        <header class="panel-head">
          <div v-if="previewId && hasText" role="group" aria-label="选择周报内容">
            <button type="button" class="link-button" :aria-pressed="!showText" @click="showText=false">附件原文</button>
            <button type="button" class="link-button" :aria-pressed="showText" @click="showText=true">填写的正文</button>
          </div>
          <h3 v-else-if="!revisionId">草稿原文</h3>
          <a v-if="previewId && !showText" class="link-button open-pdf" :href="'/api/v1/attachments/'+previewId+'/preview-content'" target="_blank" rel="noopener">打开原 PDF</a>
        </header>
        <PresentationDocument :attachment-id="showText ? null : previewId || null"
          :content="content" :author="report.owner_name" />
      </section>
      <p v-else-if="!loading && !error" class="empty-copy">这份周报暂时没有可预览的内容。</p>
    </template>
  </article>
</template>
<style scoped>
.detail { display:grid; align-content:start; gap:12px; min-height:160px; }
.detail .panel-head, .content-choices { margin:0; }
.detail h2 { font-size:20px; overflow-wrap:anywhere; }
.version-bar { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; color:var(--muted); font-size:13px; }
.original { min-width:0; border:1px solid var(--line); border-radius:9px; overflow:hidden; }
.original .panel-head { padding:7px 12px; background:#f4f7f3; flex-wrap:wrap; }
.original .panel-head:empty { display:none; }
.original [role="group"] { display:flex; gap:14px; }
.original [aria-pressed="true"] { color:var(--ink); font-weight:700; }
.open-pdf { margin-left:auto; }
</style>
