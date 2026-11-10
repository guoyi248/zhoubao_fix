<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowRight, VideoCamera } from "@element-plus/icons-vue";
import api from "@/utils/api";
import ReportDetail from "@/components/report/ReportDetail.vue";
import { dateText, weekRange, type Overview } from "@/utils/week";
import { enterPresentationFullscreen } from "@/utils/presentation";

interface MeetingRecord { id: string; created_at: string; snapshot_count: number }
const route = useRoute();
const router = useRouter();
const overview = ref<Overview>();
const records = ref<MeetingRecord[]>([]);
const tab = ref("submitted");
const selected = ref("");
const error = ref("");
const historyError = ref("");
const loading = ref(false);
const refresh = ref(0);
const periodId = computed(() => overview.value?.period.id || "");
watch(() => [route.query.period, refresh.value] as const, async ([id], _, cleanup) => {
  const request = new AbortController();
  cleanup(() => request.abort());
  loading.value = true;
  error.value = "";
  historyError.value = "";
  overview.value = undefined;
  tab.value = "submitted";
  selected.value = "";
  records.value = [];
  try {
    const { data } = await api.get<Overview>("/admin/reports/overview", {
      params: typeof id === "string" ? { period:id } : {}, signal: request.signal,
    });
    if (request.signal.aborted) return;
    overview.value = data;
    loading.value = false;
    const history = await api.get<MeetingRecord[]>("/admin/meetings/list", { params:{ period:data.period.id }, signal:request.signal });
    if (!request.signal.aborted) records.value = history.data;
  } catch (e:any) {
    if (!request.signal.aborted) {
      if (overview.value) historyError.value = e.message || "组会记录加载失败";
      else error.value = e.message || "周报加载失败";
    }
  } finally { if (!request.signal.aborted) loading.value = false; }
}, { immediate: true });

function choosePeriod(id: string) { void router.replace({ path:"/admin/reports", query:{period:id} }); }
</script>

<template>
  <div class="team-reports" v-loading="loading">
    <header class="page-heading">
      <div>
        <h1 class="page-title">团队周报</h1>
        <p v-if="overview" class="page-sub">{{ weekRange(overview.period) }}</p>
      </div>
      <div v-if="overview" class="report-actions">
        <el-select :model-value="periodId" class="period-picker" aria-label="选择周报周期" @change="choosePeriod">
          <el-option v-for="p in overview.periods" :key="p.id" :label="p.iso_year+' 年 · 第 '+p.iso_week+' 周'" :value="p.id" />
        </el-select>
        <router-link v-if="overview.submitted.length" class="present-link" :to="{path:'/admin/presentation',query:{period:periodId}}" @click="enterPresentationFullscreen($event)">
          <el-icon><VideoCamera /></el-icon> 组会展示
        </router-link>
        <el-button v-else disabled :icon="VideoCamera">组会展示</el-button>
      </div>
    </header>
    <el-alert v-if="error" type="error" :closable="false">
      <template #title>{{ error }} <button class="link-button" @click="refresh++">重试</button></template>
    </el-alert>
    <section v-if="overview" class="panel report-list" aria-label="成员提交情况">
      <header class="list-head">
        <div class="tabline" aria-label="提交状态">
          <button type="button" :class="{chosen:tab==='submitted'}" :aria-pressed="tab==='submitted'" @click="tab='submitted'">
            已提交 <b>{{ overview.submitted.length }}</b>
          </button>
          <button v-if="overview.is_current" type="button" :class="{chosen:tab==='missing'}" :aria-pressed="tab==='missing'" @click="tab='missing'">
            待提交 <b>{{ overview.missing.length }}</b>
          </button>
        </div>
        <router-link class="link-button" :to="{path:'/analysis',query:{period:periodId}}">AI 周进展 <el-icon><ArrowRight /></el-icon></router-link>
      </header>
      <template v-if="tab==='submitted'">
        <button v-for="r in overview.submitted" :key="r.id" class="data-row action report-row" :aria-label="'查看'+r.owner_name+'的周报'" @click="selected=r.id">
          <span class="avatar" aria-hidden="true">{{ r.owner_name.slice(-1) }}</span>
          <span class="report-info">
            <strong>{{ r.owner_name }}</strong>
            <small v-if="r.published_filename" class="filename">{{ r.published_filename }}</small>
          </span>
          <span class="row-end report-meta"><time :datetime="r.submitted_at || r.updated_at">{{ dateText(r.submitted_at || r.updated_at,true) }} {{ r.submitted_at ? '提交' : '更新' }}</time><el-icon><ArrowRight /></el-icon></span>
        </button>
        <p v-if="!overview.submitted.length" class="empty-copy">这周还没有已提交的周报。</p>
      </template>
      <template v-else>
        <div v-for="m in overview.missing" :key="m.id" class="data-row"><span class="avatar" aria-hidden="true">{{ m.name.slice(-1) }}</span><strong class="member-name">{{ m.name }}</strong></div>
        <p v-if="!overview.missing.length" class="empty-copy">本周已全员提交。</p>
        <router-link v-if="overview.missing.length" to="/reminders" class="link-button reminders-link">查看邮箱提醒 <el-icon><ArrowRight /></el-icon></router-link>
      </template>
    </section>
    <p v-if="historyError" role="alert" class="history-error glass-panel">{{ historyError }} <button class="link-button" @click="refresh++">重试</button></p>
    <details v-else-if="records.length" class="past glass-panel">
      <summary>组会记录 <small>{{ records.length }}</small></summary>
      <router-link v-for="m in records" :key="m.id" class="data-row action" :to="'/admin/meetings/'+m.id" @click="enterPresentationFullscreen($event)">
        <time :datetime="m.created_at">{{ dateText(m.created_at,true) }}</time> · {{ m.snapshot_count }} 份周报 <el-icon class="row-end"><ArrowRight /></el-icon>
      </router-link>
    </details>
    <el-drawer :model-value="!!selected" title="成员周报" size="min(760px,100%)" @close="selected=''">
      <ReportDetail v-if="selected" :report-id="selected" admin-view />
    </el-drawer>
  </div>
</template>
<style scoped>
.report-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; }
.period-picker { width: 184px; max-width: 100%; }
.present-link { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 34px; padding: 6px 14px; border-radius: 7px; background: var(--teal); color: #fff; font-size: 14px; font-weight: 600; text-decoration: none; white-space: nowrap; }
.present-link:hover { background: #225b3a; }
.report-list { padding-top: 6px; padding-bottom: 6px; }
.list-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--line); }
.list-head .tabline { margin: 0; border: 0; }
.tabline button { padding: 13px 0; }
.report-row { padding: 14px 0; }
.report-info { min-width: 0; }
.report-info strong,.member-name { overflow-wrap: anywhere; }
.filename { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.report-meta { display: flex; align-items: center; gap: 13px; flex-shrink: 0; color: var(--muted); font-size: 12px; }
.report-meta .el-icon { color: var(--teal); }
.reminders-link { margin: 6px 0 12px; }
.past,.history-error { margin-top:16px; padding:8px 16px; color:var(--muted); font-size:13px;
  background:var(--paper); border:1px solid var(--line); border-radius:12px; }
.past summary { cursor: pointer; padding: 7px 0; }
.past summary small { margin-left: 5px; }
.past a { text-decoration: none; }
@media(max-width: 640px) {
  .report-actions { width: 100%; }
  .period-picker { flex: 1; min-width: 124px; }
  .report-row { display: grid; grid-template-columns: auto minmax(0,1fr) auto; column-gap: 9px; }
  .report-meta { flex-direction: column; align-items: flex-end; gap: 4px; }
  .list-head { flex-wrap: wrap; gap: 3px 8px; }
}
</style>
