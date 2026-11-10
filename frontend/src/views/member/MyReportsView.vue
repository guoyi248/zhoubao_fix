<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowRight, Document } from "@element-plus/icons-vue";
import ReportDetail from "@/components/report/ReportDetail.vue";
import api from "@/utils/api";
import { dateText, reportStatus, type ReportRow } from "@/utils/week";

const route = useRoute();
const router = useRouter();
const reports = ref<ReportRow[]>([]);
const selected = ref("");
const loading = ref(true);
const error = ref("");

function readSelection() {
  const id = route.query.report;
  selected.value = typeof id === "string" && reports.value.some(row => row.id === id) ? id : "";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    reports.value = (await api.get<ReportRow[]>("/me/reports/")).data;
    readSelection();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "周报读取失败";
  } finally {
    loading.value = false;
  }
}

function close() {
  selected.value = "";
  if (route.query.report) {
    const query = { ...route.query };
    delete query.report;
    void router.replace({ query });
  }
}

function weekName(row: ReportRow) {
  const [year, week] = row.period_label.split("-W");
  return year + " 年第 " + Number(week) + " 周";
}
watch(() => route.query.report, readSelection);
onMounted(load);
</script>

<template>
  <div class="my-reports" v-loading="loading" :aria-busy="loading">
    <header class="page-heading">
      <h1 class="page-title">历史周报</h1>
      <router-link class="link-button" to="/analysis">AI 周报解析 <el-icon><ArrowRight /></el-icon></router-link>
    </header>
    <el-alert v-if="error" type="error" :closable="false">
      <template #title>{{ error }} <button class="link-button" @click="load">重试</button></template>
    </el-alert>
    <section v-else class="panel history-list" aria-label="我的历史周报">
      <button v-for="row in reports" :key="row.id" class="history-item" @click="selected=row.id">
        <span class="soft-icon" aria-hidden="true"><el-icon><Document /></el-icon></span>
        <span class="report-name">
          <strong>{{ row.published_filename || weekName(row) }}</strong>
          <small><template v-if="row.published_filename">{{ weekName(row) }} · </template>{{ dateText(row.submitted_at || row.updated_at, true) }} {{ row.submitted_at ? '提交' : '更新' }}</small>
        </span>
        <span class="pill" :class="{ good: row.status==='submitted' || row.status==='archived', waiting: row.status==='resubmitted' }">{{ reportStatus[row.status] }}</span>
        <el-icon class="open-icon" aria-hidden="true"><ArrowRight /></el-icon>
      </button>
      <p v-if="!loading && !reports.length" class="empty-copy">暂无历史周报。<router-link to="/reports/current">提交本周周报</router-link></p>
    </section>
    <el-drawer :model-value="!!selected" title="周报详情" size="min(760px,100%)" @close="close">
      <ReportDetail v-if="selected" :report-id="selected" />
    </el-drawer>
  </div>
</template>

<style scoped>
.my-reports { min-width:0; min-height:150px; }
.history-list { padding:4px clamp(12px,2vw,24px); }
.history-item { display:flex; align-items:center; gap:12px; width:100%; padding:15px 6px; border:0; background:transparent; color:var(--ink); text-align:left; }
.history-item + .history-item { border-top:1px solid var(--line); }
.history-item:hover, .history-item:focus-visible { background:#f4f8f2; }
.report-name { flex:1; min-width:0; }
.report-name strong, .report-name small { display:block; }
.report-name strong { font-size:14px; overflow-wrap:anywhere; }
.report-name small { margin-top:5px; font-size:12px; color:var(--muted); }
.open-icon { color:var(--muted); }
@media (max-width:500px) { .history-item { gap:8px; } .open-icon { display:none; } }
</style>
