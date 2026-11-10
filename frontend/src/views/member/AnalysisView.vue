<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowRight } from "@element-plus/icons-vue";
import api from "@/utils/api";
import { useUserStore } from "@/stores/user";
import ProgressSummary from "@/components/report/ProgressSummary.vue";
import { serviceLabel, analysisLabels as labels, type ServiceState } from "@/utils/weeklyServices";
import type { Overview, ReportRow } from "@/utils/week";

interface ModelService extends ServiceState { provider?: string; model?: string }
interface Choice { id: string; label: string }
interface Source { id: string; name: string; revision: string; status?: string }
const route = useRoute();
const router = useRouter();
const store = useUserStore();
const service = ref<ModelService>();
const choices = ref<Choice[]>([]);
const rows = ref<Source[]>([]);
const period = ref("");
const selected = ref("");
const error = ref("");
const loading = ref(false);
const current = computed(() => rows.value.find(row => row.revision === selected.value));
const active = computed(() => service.value?.enabled && service.value?.configured);
let generation = 0;
async function load() {
  const token = ++generation;
  const requested = typeof route.query.period === "string" ? route.query.period : "";
  const requestedRevision = typeof route.query.revision === "string" ? route.query.revision : "";
  loading.value = true;
  error.value = "";
  try {
    const { data: state } = await api.get<ModelService>("/reports/analysis-service");
    if (token !== generation) return;
    service.value = state;
    if (store.isAdmin) {
      const { data } = await api.get<Overview>("/admin/reports/overview", { params: requested ? { period: requested } : {} });
      if (token !== generation) return;
      choices.value = data.periods.map(p => ({id:p.id, label:p.iso_year+" 年 · 第 "+p.iso_week+" 周"}));
      period.value = data.period.id;
      rows.value = data.submitted.flatMap(r => r.current_revision_id ? [{
        id:r.id, name:r.owner_name, revision:r.current_revision_id, status:r.analysis_status,
      }] : []);
    } else {
      const { data } = await api.get<ReportRow[]>("/me/reports/");
      if (token !== generation) return;
      const published = data.filter(r => r.current_revision_id);
      choices.value = published.map(r => ({ id:r.reporting_period_id, label:r.period_label.replace("-W"," 年 · 第 ")+" 周" }));
      const report = published.find(r => r.reporting_period_id === requested)
        || published.find(r => r.current_revision_id === requestedRevision) || published[0];
      period.value = report?.reporting_period_id || "";
      rows.value = report?.current_revision_id ? [{ id:report.id, name:report.owner_name, revision:report.current_revision_id }] : [];
    }
    selected.value = rows.value.find(r => r.revision===requestedRevision)?.revision || rows.value[0]?.revision || "";
  } catch (e: any) {
    if (token === generation) { error.value = e.message || "解析信息加载失败"; rows.value = []; }
  } finally { if (token === generation) loading.value = false; }
}
function choosePeriod(id: string) {
  void router.replace({ path: "/analysis", query: { period:id } });
}
function updateStatus(revision: string, status: string) {
  const row = rows.value.find(r => r.revision === revision);
  if (row) row.status = status;
}
watch(() => [route.query.period, route.query.revision], load);
onMounted(load);
</script>

<template>
  <div v-loading="loading" class="analysis">
    <header class="page-heading">
      <h1 class="page-title">AI 周报解析</h1>
      <el-select v-if="choices.length" :model-value="period" aria-label="选择解析周次" class="period-picker" @change="choosePeriod">
        <el-option v-for="p in choices" :key="p.id" :value="p.id" :label="p.label" />
      </el-select>
    </header>
    <el-alert v-if="error" type="error" :closable="false">
      <template #title>{{ error }} <button class="link-button" @click="load">重试</button></template>
    </el-alert>
    <template v-if="service">
      <div class="service-line glass-panel" :class="{inactive:!active}">
        <span class="service-name"><i aria-hidden="true"></i>{{ active ? '自动解析已启用' : '自动解析' + serviceLabel(service) }}</span>
        <span v-if="service.model" class="model-name">{{ service.provider === 'ollama' ? 'Ollama' : '在线模型' }} · {{ service.model }}</span>
        <span v-if="!active && !store.isAdmin" class="model-name">请联系管理员启用模型服务</span>
        <router-link v-if="service.setup" class="link-button config-link" :to="{path:'/admin/settings',query:{section:'model'}}">配置模型</router-link>
      </div>
      <section v-if="!error && current" class="analysis-panel glass-panel" :class="{personal:!store.isAdmin}">
        <nav v-if="store.isAdmin" class="members" aria-label="选择成员总结">
          <h2>成员 <small>{{ rows.length }}</small></h2>
          <div class="member-list">
            <button v-for="r in rows" :key="r.revision" type="button" :class="{chosen:selected===r.revision}" :aria-pressed="selected===r.revision" @click="selected=r.revision">
              <strong>{{ r.name }}</strong><small>{{ labels[r.status || 'available'] || '等待生成' }}</small>
            </button>
          </div>
        </nav>
        <div class="result">
          <div v-if="store.isAdmin" class="mobile-selector">
            <label for="analysis-member">成员</label>
            <select id="analysis-member" v-model="selected"><option v-for="r in rows" :key="r.revision" :value="r.revision">{{ r.name }}</option></select>
          </div>
          <h2 v-if="store.isAdmin" class="selected-name">{{ current.name }}</h2>
          <ProgressSummary :revision-id="current.revision" @loaded="updateStatus" />
        </div>
      </section>
      <section v-else-if="!error" class="panel empty-result">
        <h2>{{ store.isAdmin ? '这周还没有已提交的周报' : '还没有已提交的周报' }}</h2>
        <router-link class="link-button" :to="store.isAdmin ? {path:'/admin/reports',query:{period}} : '/reports/current'">
          {{ store.isAdmin ? '查看团队周报' : '填写本周周报' }} <el-icon><ArrowRight /></el-icon>
        </router-link>
      </section>
    </template>
  </div>
</template>

<style scoped>
.period-picker { max-width: 100%; width: 186px; }
.service-line { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 14px; margin-bottom: 16px; padding: 10px 14px; color: var(--muted); background: #edf4ec; border: 1px solid var(--line); border-radius: 8px; font-size: 13px; }
.service-line.inactive { background: #f6f4ec; border-color: #e6e2d3; }
.service-name { display: inline-flex; align-items: center; gap: 7px; color: var(--ink); font-weight: 600; }
.service-name i { width: 7px; height: 7px; border-radius: 50%; background: #59895f; }
.inactive .service-name i { background: #a38a47; }
.model-name { min-width: 0; overflow-wrap: anywhere; }
.config-link { margin-left: auto; }
.analysis-panel { display: grid; grid-template-columns: minmax(144px,205px) minmax(0,1fr); min-width: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); }
.analysis-panel.personal { grid-template-columns: 1fr; }
.members { min-width: 0; padding: 17px 10px; border-right: 1px solid var(--line); background: #f5f8f2; }
.members h2 { display: flex; align-items: baseline; gap: 7px; margin: 0 9px 12px; font-size: 14px; }
.members h2 small { color: var(--muted); font-size: 12px; font-weight: 500; }
.member-list { display: grid; gap: 3px; }
.member-list button { display: grid; gap: 3px; width: 100%; border: 0; border-radius: 6px; padding: 9px 10px; text-align: left; background: transparent; color: var(--ink); overflow-wrap: anywhere; }
.member-list button:hover { background: #e8f0e6; }
.member-list button.chosen { background: #dcebdc; color: #285a38; }
.member-list strong { font-size: 14px; }
.member-list small { color: var(--muted); font-size: 12px; }
.result { min-width: 0; padding: clamp(17px,2.2vw,28px); overflow-wrap: anywhere; }
.selected-name { margin: 0 0 17px; font-size: 21px; }
.result :deep(.summary-box) { padding: 0; background: transparent; border: 0; }
.result :deep(.summary-lead) { margin: 12px 0; }
.mobile-selector { display: none; }
.empty-result { text-align: center; padding: 35px 16px; }
.empty-result h2 { margin: 0 0 8px; font-size: 16px; }
@media (max-width: 720px) {
  .analysis-panel { display: block; }
  .members,.selected-name { display: none; }
  .mobile-selector { display: flex; align-items: center; gap: 10px; padding-bottom: 15px; margin-bottom: 15px; border-bottom: 1px solid var(--line); }
  .mobile-selector label { font-size: 13px; color: var(--muted); }
  .mobile-selector select { min-width: 0; max-width: 100%; flex: 1; border: 1px solid var(--line); border-radius: 6px; background: var(--paper); color: var(--ink); padding: 6px; }
}
@media (max-width: 420px) { .period-picker { width: 155px; } }
</style>
