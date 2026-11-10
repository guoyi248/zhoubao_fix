<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ArrowRight, Calendar, Document, Monitor, Upload } from "@element-plus/icons-vue";
import ReportOriginalDrawer from "@/components/report/ReportOriginalDrawer.vue";
import { useUserStore } from "@/stores/user";
import api from "@/utils/api";
import { enterPresentationFullscreen } from "@/utils/presentation";
import { reportFileAccept, sendReportFile } from "@/utils/reportUpload";
import { dateText, weekRange, type Overview, type Period, type ReportRow } from "@/utils/week";
import { analysisLabels } from "@/utils/weeklyServices";

interface CurrentReport {
  id: string;
  status: string;
  current_revision_id: string | null;
  period: Period;
  attachment_count: number;
  attachment_limits: { count: number; file_bytes: number };
}
const user = useUserStore();
const router = useRouter();
const report = ref<CurrentReport>();
const overview = ref<Overview>();
const history = ref<ReportRow[]>([]);
const openRow = ref<ReportRow>();
const filter = ref<"all" | "submitted" | "missing">("all");
const fileInput = ref<HTMLInputElement>();
const dragOver = ref(false);
const uploading = ref(false);
const uploadError = ref("");
const loading = ref(true);
const error = ref("");
const period = computed(() => report.value?.period);
const editable = computed(() => report.value?.status === "draft" || report.value?.status === "resubmitted");
const ownPublished = computed(() => (user.isAdmin ? overview.value?.submitted : history.value)?.find(r => r.id === report.value?.id && r.current_revision_id));
const previous = computed(() => history.value.filter(r => r.current_revision_id && r.id !== report.value?.id).slice(0, 5));
const stateLabel = computed(() => {
  if (report.value?.status === "archived") return "已归档";
  if (report.value?.status === "resubmitted") return "更正中";
  return report.value?.current_revision_id ? "已提交" : "待提交";
});
const filters = computed(() => {
  const submitted = overview.value?.submitted.length || 0;
  const missing = overview.value?.missing.length || 0;
  return [
    { value: "all", name: "全部成员", count: submitted + missing },
    { value: "submitted", name: "已提交", count: submitted },
    { value: "missing", name: "待提交", count: missing },
  ] as const;
});
const canUpload = computed(() => editable.value && report.value && report.value.attachment_count < report.value.attachment_limits.count);
function weekLabel(row: ReportRow) {
  const [year, week] = row.period_label.split("-W");
  return year + " 年第 " + Number(week) + " 周";
}
function publishedTitle(row: ReportRow) {
  return row.published_filename || weekLabel(row) + "周报";
}
async function load() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await api.get<CurrentReport>("/me/reports/current");
    report.value = data;
    if (user.isAdmin) {
      const team = await api.get<Overview>("/admin/reports/overview", { params: { period: data.period.id } });
      overview.value = team.data;
    } else {
      history.value = (await api.get<ReportRow[]>("/me/reports/")).data;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "周报加载失败";
  } finally {
    loading.value = false;
  }
}
async function upload(files?: FileList | null) {
  dragOver.value = false;
  if (!files?.length || !report.value || !canUpload.value || uploading.value) return;
  const file = files[0];
  if (files.length !== 1) {
    uploadError.value = "请先选择一份周报，上传后可以继续添加附件。";
    return;
  }
  if (!reportFileAccept.split(",").some(ext => file.name.toLowerCase().endsWith(ext))) {
    uploadError.value = "请选择 Word、Excel、PPT、PDF、TXT 或 Markdown 文件。";
    return;
  }
  uploadError.value = "";
  uploading.value = true;
  try {
    const uploaded = await sendReportFile("/me/reports/" + report.value.id + "/attachments", file);
    report.value.attachment_count++;
    await router.push({ path: "/reports/current", query: { file: uploaded.id } });
  } catch (cause) {
    uploadError.value = cause instanceof Error ? cause.message : "文件上传失败，请重试。";
  } finally {
    uploading.value = false;
  }
}
function chooseFile(event: Event) {
  const input = event.target as HTMLInputElement;
  void upload(input.files);
  input.value = "";
}
onMounted(load);
</script>

<template>
  <div v-loading="loading" class="dashboard" :aria-busy="loading">
    <header class="week-head glass-heading">
      <div class="week-title">
        <h1 class="page-title">本周工作台</h1>
        <div v-if="period" class="period">
          <span><el-icon><Calendar /></el-icon>{{ period.iso_year }} 年第 {{ period.iso_week }} 周</span>
          <span>{{ weekRange(period) }}</span>
        </div>
      </div>
      <router-link v-if="user.isAdmin && overview?.submitted.length && period"
        class="primary" :to="{ path: '/admin/presentation', query: { period: period.id } }" @click="enterPresentationFullscreen($event)">
        <el-icon><Monitor /></el-icon>开始组会
      </router-link>
    </header>
    <el-alert v-if="error" type="error" :closable="false">
      <template #title>{{ error }} <button class="link-button" @click="load">重试</button></template>
    </el-alert>

    <section v-if="user.isAdmin && overview && period" class="surface-card glass-panel" aria-labelledby="team-title">
      <header class="card-head">
        <h2 id="team-title">成员提交情况</h2>
        <router-link class="link-button" to="/admin/reports">往期周报 <el-icon><ArrowRight /></el-icon></router-link>
      </header>
      <div class="toolbar">
        <div class="filters" role="group" aria-label="按提交状态筛选成员">
          <button v-for="tab in filters" :key="tab.value" :aria-pressed="filter === tab.value" @click="filter = tab.value">
            {{ tab.name }} <b>{{ tab.count }}</b>
          </button>
        </div>
        <router-link v-if="overview.missing.length" class="link-button" to="/reminders">邮箱提醒</router-link>
      </div>
      <div class="team-row column-head" aria-hidden="true">
        <span>成员</span><span>周报文件</span><span>AI 解析</span><span>组会</span>
      </div>
      <template v-if="filter !== 'missing'">
        <article v-for="row in overview.submitted" :key="row.id" class="team-row">
          <div class="person"><span class="avatar" aria-hidden="true">{{ Array.from(row.owner_name)[0] }}</span>
            <div class="person-copy"><strong>{{ row.owner_name }}</strong><small class="state-done">已提交</small></div>
          </div>
          <div class="file-cell">
            <button class="file-title" :title="publishedTitle(row)" @click="openRow = row">{{ publishedTitle(row) }}</button>
            <small>第 {{ row.revision_no }} 版<span v-if="row.submitted_at"> · {{ dateText(row.submitted_at, true) }} 提交</span></small>
          </div>
          <router-link class="ai-link" :to="{ path: '/analysis', query: { period: period.id, revision: row.current_revision_id } }">
            <span class="mobile-only">AI 解析 · </span>{{ analysisLabels[row.analysis_status] || '查看解析' }}
          </router-link>
          <div class="row-actions">
            <router-link class="link-button" :aria-label="'展示' + row.owner_name + '的周报'"
              :to="{ path: '/admin/presentation', query: { period: period.id, revision: row.current_revision_id } }"
              @click="enterPresentationFullscreen($event)">展示</router-link>
          </div>
        </article>
      </template>
      <template v-if="filter !== 'submitted'">
        <article v-for="member in overview.missing" :key="member.id" class="team-row missing-row">
          <div class="person"><span class="avatar quiet" aria-hidden="true">{{ Array.from(member.name)[0] }}</span>
            <div class="person-copy"><strong>{{ member.name }}</strong><small class="state-pending">待提交</small></div>
          </div>
          <span class="missing-file" aria-hidden="true">—</span>
        </article>
      </template>
      <p v-if="!filters.find(t => t.value === filter)?.count" class="empty-copy">
        {{ filter === 'missing' ? '本周成员均已提交。' : filter === 'submitted' ? '本周尚无人提交。' : '本周暂无成员。' }}
      </p>
    </section>

    <section v-if="report && period" class="surface-card personal glass-panel" aria-labelledby="personal-title">
      <header class="card-head">
        <div class="card-label"><h2 id="personal-title">我的提交</h2>
          <span :class="['pill', editable ? 'waiting' : 'good']">{{ stateLabel }}</span>
        </div>
        <span class="deadline">截止 {{ dateText(period.deadline, true) }}（北京时间）</span>
      </header>
      <div v-if="ownPublished" class="published">
        <span class="soft-icon" aria-hidden="true"><el-icon><Document /></el-icon></span>
        <div class="file-cell"><button class="file-title" :title="'打开原文 · ' + publishedTitle(ownPublished)" @click="openRow = ownPublished">{{ publishedTitle(ownPublished) }}</button>
          <small>第 {{ ownPublished.revision_no }} 版<span v-if="ownPublished.submitted_at"> · {{ dateText(ownPublished.submitted_at, true) }} 提交</span></small>
        </div>
      </div>
      <template v-if="canUpload">
        <input ref="fileInput" hidden type="file" :accept="reportFileAccept" @change="chooseFile" />
        <button class="upload-zone" :class="{ dragging: dragOver, compact: report.attachment_count }" :disabled="uploading" @click="fileInput?.click()"
          @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop.prevent="upload($event.dataTransfer?.files)">
          <span class="upload-icon"><el-icon><Upload /></el-icon></span>
          <span><strong>{{ uploading ? '正在上传…' : report.attachment_count ? '添加附件' : '上传周报文件' }}</strong>
            <small>可拖放 Word、Excel、PPT、PDF、TXT 或 Markdown</small></span>
        </button>
        <p v-if="uploadError" class="upload-error" role="alert">{{ uploadError }}</p>
      </template>
      <footer class="personal-foot">
        <span v-if="editable && report.attachment_count">草稿中有 {{ report.attachment_count }} 个附件</span>
        <router-link to="/reports/current" :class="editable && report.attachment_count ? 'primary' : 'link-button'">
          {{ editable ? (report.attachment_count ? '继续提交' : '打开草稿') : report.status === 'submitted' ? '更正周报' : '查看周报' }}
          <el-icon><ArrowRight /></el-icon>
        </router-link>
      </footer>
    </section>

    <section v-if="!user.isAdmin && !loading && !error" class="surface-card glass-panel" aria-labelledby="history-title">
      <header class="card-head">
        <h2 id="history-title">往期提交</h2>
        <router-link class="link-button" to="/reports">全部周报 <el-icon><ArrowRight /></el-icon></router-link>
      </header>
      <button v-for="row in previous" :key="row.id" class="published history-row" @click="openRow = row">
        <span class="soft-icon" aria-hidden="true"><el-icon><Document /></el-icon></span>
        <span class="file-cell"><strong class="file-title">{{ publishedTitle(row) }}</strong>
          <small>{{ weekLabel(row) }} · 第 {{ row.revision_no }} 版<span v-if="row.submitted_at"> · {{ dateText(row.submitted_at, true) }} 提交</span></small>
        </span>
        <el-icon aria-hidden="true"><ArrowRight /></el-icon>
      </button>
      <p v-if="!previous.length" class="empty-copy">暂无往期周报。</p>
    </section>
    <ReportOriginalDrawer :row="openRow" :admin="user.isAdmin" @close="openRow = undefined" />
  </div>
</template>

<style scoped>
.dashboard { display: grid; align-content: start; gap: 20px; min-width: 0; min-height: 180px; container-type: inline-size; }
.week-head, .card-head, .card-label, .period, .period > span, .toolbar, .person,
.row-actions, .published, .personal-foot, .primary, .filters { display: flex; align-items: center; }
.week-head, .card-head, .toolbar { justify-content: space-between; gap: 12px; }
.week-head { display:flex; flex-wrap:wrap; gap:14px; margin-bottom:2px; }
.week-title { min-width:0; }
.period { gap: 10px; margin-top: 8px; color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }
.period > span { gap: 6px; }
.period > span + span { border-left: 1px solid #c5d3c7; padding-left: 10px; }
.primary { gap: 8px; flex: none; color: #fff; text-decoration: none; padding: 11px 16px; font-weight: 600; font-size: 14px; background: #326b48; border-radius: 7px; }
.primary:hover { background: #29593c; }
.primary, .upload-zone, .history-row { transition: background-color .15s, border-color .15s; }
.surface-card { border: 1px solid; border-radius: 13px; min-width: 0; padding: 0 clamp(14px, 2.5cqw, 26px); }
.card-head { flex-wrap: wrap; padding: 18px 0; }
.card-head h2 { font-size: 18px; letter-spacing: -.02em; }
.card-label { gap: 10px; }
.toolbar { flex-wrap: wrap; padding-bottom: 16px; }
.filters { gap: 4px; max-width: 100%; flex-wrap: wrap; }
.filters button { background: transparent; border: 0; border-radius: 6px; color: var(--muted); padding: 6px 10px; font-size: 13px; }
.filters button[aria-pressed=true] { background: #e6f1e5; color: #295c3a; font-weight: 650; }
.filters b { font-variant-numeric: tabular-nums; margin-left: 2px; }
.team-row { display: grid; grid-template-columns: minmax(110px,1fr) minmax(140px,2.5fr) minmax(76px,.75fr) minmax(76px,.65fr); column-gap: 14px; align-items: center; padding: 13px 8px; border-top: 1px solid #e5ece5; min-width: 0; }
.column-head { background: #f3f7f1; border: 0; border-radius: 5px; font-size: 12px; color: var(--muted); padding-top: 8px; padding-bottom: 8px; }
.team-row:last-child { margin-bottom: 5px; }
.person { gap: 9px; min-width: 0; }
.person-copy { min-width: 0; }
.person strong { font-size: 14px; overflow-wrap: anywhere; }
.person small, .file-cell small, .upload-zone small { display: block; font-size: 12px; margin-top: 4px; }
.person small::before { content: ""; display: inline-block; height: 5px; width: 5px; background: currentColor; border-radius: 100%; margin-right: 5px; vertical-align: 2px; }
.state-done { color: #46744e; }
.state-pending { color: #825d22; }
.quiet { background: #f2f1e9; color: #716948; }
.file-cell { min-width: 0; }
.file-title { display: block; text-align: left; max-width: 100%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; background: none; border: 0; padding: 0; color: var(--ink); font-size: 14px; font-weight: 600; line-height: 1.6; }
.file-title:hover { text-decoration: underline; text-underline-offset: 3px; color: var(--teal); }
.file-cell small, .deadline, .personal-foot, .missing-file { color: var(--muted); font-size: 12px; line-height: 1.65; }
.ai-link { font-size: 13px; color: #52695a; text-decoration: underline dotted; text-underline-offset: 4px; }
.row-actions { gap: 12px; }
.mobile-only { display: none; }
.missing-file { grid-column: 2 / -1; }
.personal { padding-bottom: 15px; }
.personal-foot { flex-wrap: wrap; justify-content: space-between; gap: 4px 14px; }
.personal-foot > a:only-child { margin-left: auto; }
.personal-foot .primary { padding:6px 12px; }
.upload-zone { display: flex; width: 100%; align-items: center; gap: 13px; text-align: left; padding: 22px; background: var(--glass-inset); color: var(--teal); border: 1px dashed #71967e; border-radius: 8px; margin-bottom: 10px; }
.upload-zone:hover, .upload-zone.dragging { background: var(--glass-field); border-color: #547d59; }
.upload-zone.compact { padding:12px 16px; }
.upload-zone strong { font-size: 16px; }
.upload-zone small { color: #516854; line-height: 1.6; }
.upload-icon { display: grid; place-items: center; width: 39px; height: 39px; flex: none; background: #dcebd9; border-radius: 9px; font-size: 21px; }
.upload-error { color: #943c32; font-size: 13px; margin: 8px 0; }
.published { gap: 12px; padding: 13px 0; border-top: 1px solid #e5ece5; }
.published > .file-cell { flex: 1; }
.published > .link-button { flex: none; }
.history-row:last-child { margin-bottom: 4px; }
.history-row { width:100%; text-align:left; background:transparent; border:0; border-top:1px solid var(--line); color:var(--muted); }
.history-row:hover { background:#f4f8f2; }
@container (max-width: 620px) {
  .week-head > .primary { padding:8px 12px; }
  .team-row { grid-template-columns: minmax(0,1fr) auto; gap: 7px 12px; padding: 14px 0; }
  .person { grid-column: 1; grid-row: 1; }
  .person-copy { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .person small { margin: 0; }
  .file-cell { grid-column: 1 / -1; grid-row: 2; }
  .ai-link { grid-column: 1 / -1; grid-row: 3; justify-self: start; }
  .mobile-only { display: inline; }
  .row-actions { grid-column: 2; grid-row: 1; }
  .column-head, .missing-file { display: none; }
  .person .avatar { width: 29px; height: 29px; font-size: 11px; border-radius: 7px; }
  .filters { gap: 0; }
  .filters button { padding: 6px 8px; }
  .upload-zone { padding: 15px 12px; }
}
@container (max-width: 385px) {
  .card-head { padding: 15px 0; }
  .toolbar { gap: 6px; }
  .deadline { flex-basis: 100%; }
  .published { gap: 7px; }
}
</style>
