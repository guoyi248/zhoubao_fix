<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Document, Upload } from "@element-plus/icons-vue";
import ProgressSummary from "@/components/report/ProgressSummary.vue";
import PresentationDocument from "@/components/report/PresentationDocument.vue";
import { weekRange } from "@/utils/week";
import api from "@/utils/api";
import { reportFileAccept, sendReportFile, type ReportAttachment as AttInfo } from "@/utils/reportUpload";

const router = useRouter();
const route = useRoute();
let requestedFile = typeof route.query.file === "string" ? route.query.file : "";
const report = ref<any>(null);
const attachments = ref<AttInfo[]>([]);
const loading = ref(true);
const busy = ref(false);
const submitting = ref(false);
const replacementInput = ref<HTMLInputElement>();
const replacementId = ref("");
const error = ref("");
const selectedId = ref("");
const previewAttId = ref("");
const previewHidden = ref(false);
const pending = new Set(["uploading", "quarantined", "scanning", "compatibility_check", "converting"]);
const weekLabel = computed(() => report.value ? `第 ${report.value.period.iso_week} 周` : "");
const isEditable = computed(() => ["draft", "resubmitted"].includes(report.value?.status));
const available = computed(() => attachments.value.filter(a => a.preview_status?.available));
const submittedId = computed(() => report.value?.revisions?.[0]?.confirmed_pdf_attachment_id);
const displayedFile = computed(() => previewHidden.value ? null : previewAttId.value || (
  !isEditable.value && available.value.some(a => a.id === submittedId.value) ? submittedId.value : null
));
const hasText = computed(() => Object.values(report.value?.draft_content_json || {}).some(value =>
  (Array.isArray(value) ? value : [value]).some(line => typeof line === "string" && line.trim())));
const atLimit = computed(() => !!report.value?.attachment_limits && attachments.value.length >= report.value.attachment_limits.count);
const selectedFile = computed(() => available.value.find(a => a.id === selectedId.value));
const processing = computed(() => attachments.value.some(a => pending.has(a.status)));
const rejected = computed(() => attachments.value.some(a => a.status === "rejected"));
const canSubmit = computed(() => !processing.value && !rejected.value && (!!selectedFile.value || hasText.value));
const submitHint = computed(() => {
  if (rejected.value) return "请移除未通过安全检查的附件";
  if (processing.value) return "正在处理附件，完成后可提交";
  if (selectedFile.value) return "提交文件 · " + (selectedFile.value.uploaded_filename || selectedFile.value.original_filename);
  if (hasText.value) return "将提交已填写的正文";
  return attachments.value.length ? "附件尚无可用预览，请重新生成或替换" : "上传一份文件即可开始";
});
let timer: ReturnType<typeof setTimeout> | undefined;
let generation = 0;
let active = true;

function stopPolling() {
  clearTimeout(timer);
  generation++;
}

async function loadAttachments() {
  stopPolling();
  const request = generation;
  try {
    const { data } = await api.get<AttInfo[]>(`/me/reports/${report.value.id}/attachments`);
    if (!active || request !== generation) return;
    attachments.value = data;
    if (!available.value.some(a => a.id === selectedId.value)) {
      selectedId.value = (available.value.find(a => a.id === submittedId.value)
        || available.value.find(a => a.status === "user_confirmed") || available.value[0])?.id || "";
    }
    if (!available.value.some(a => a.id === previewAttId.value)) previewAttId.value = "";
    if (requestedFile && available.value.some(a => a.id === requestedFile)) {
      selectedId.value = requestedFile;
      previewHidden.value = false;
      previewAttId.value = requestedFile;
      requestedFile = "";
    }
  } catch (e: any) {
    if (active && request === generation) ElMessage.error(e.message || "附件列表加载失败");
  }
  if (active && request === generation && attachments.value.some(a => pending.has(a.status))) {
    timer = setTimeout(loadAttachments, 3000);
  }
}

function togglePreview(id: string) {
  previewHidden.value = displayedFile.value === id;
  previewAttId.value = previewHidden.value ? "" : id;
}

async function loadReport() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await api.get("/me/reports/current");
    if (!active) return;
    report.value = data;
    await loadAttachments();
  } catch (e: any) { error.value = e.message || "周报加载失败"; }
  finally { loading.value = false; }
}
onMounted(loadReport);
onUnmounted(() => { active = false; stopPolling(); });

async function changeFiles(action: () => Promise<void>) {
  if (busy.value || !report.value) return;
  busy.value = true;
  stopPolling();
  try {
    await action();
  } catch (e: any) {
    if (e !== "cancel" && e !== "close") ElMessage.error(e.message || "操作失败");
  } finally {
    if (active) await loadAttachments();
    busy.value = false;
  }
}

async function sendFile(url: string, file: File) {
  const data = await sendReportFile(url, file);
  if (data.preview_status?.available) selectedId.value = data.id;
  return data;
}

function handleUpload(file: { raw?: File }) {
  const raw = file.raw;
  if (!raw) return;
  return changeFiles(async () => {
    const data = await sendFile(`/me/reports/${report.value.id}/attachments`, raw);
    requestedFile = data.id;
    ElMessage.success(`${data.uploaded_filename || data.original_filename} 上传成功`);
  });
}

function confirmPreview(att: AttInfo) {
  return changeFiles(async () => {
    await api.post(`/attachments/${att.id}/confirm`, { confirmed: true });
    selectedId.value = att.id;
    ElMessage.success("已确认");
  });
}

function removeAttachment(att: AttInfo) {
  return changeFiles(async () => { await api.delete(`/attachments/${att.id}/delete`); });
}

function retryPreview(att: AttInfo) {
  return changeFiles(async () => {
    await api.post(`/attachments/${att.id}/retry`);
    selectedId.value = att.id;
    ElMessage.success("预览已生成");
  });
}

function replaceAttachment(att: AttInfo, file: File) {
  return changeFiles(async () => {
    await ElMessageBox.confirm(`用“${file.name}”替换这个附件？`, "确认替换", { type: "warning" });
    const replacement = await sendFile(`/attachments/${att.id}/replace`, file);
    requestedFile = replacement.id;
    ElMessage.success("附件已替换");
  });
}

function chooseReplacement(att: AttInfo) {
  replacementId.value = att.id;
  replacementInput.value?.click();
}

function onReplacement(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  const target = attachments.value.find(att => att.id === replacementId.value);
  if (target && file) void replaceAttachment(target, file);
  input.value = "";
}

function handleSubmit() {
  if (!canSubmit.value) return;
  return changeFiles(async () => {
    await ElMessageBox.confirm(selectedFile.value
      ? "本次提交使用“" + (selectedFile.value.uploaded_filename || selectedFile.value.original_filename) + "”。"
      : "本次提交使用已填写的正文。", "提交本周周报", { confirmButtonText: "提交", cancelButtonText: "返回" });
    submitting.value = true;
    try {
      await api.post(`/me/reports/${report.value.id}/submit`, { confirmed_pdf_attachment_id: selectedId.value || null });
      ElMessage.success("周报已提交");
      await router.push("/");
    } finally { submitting.value = false; }
  });
}

function correctReport() {
  return changeFiles(async () => {
    await ElMessageBox.confirm("要重新编辑这份周报吗？再次提交后将生成一个新版本。", "更正周报");
    const { data } = await api.post(`/me/reports/${report.value.id}/resubmit`, {});
    report.value.status = data.status;
  });
}

function limitSize(bytes: number) {
  if (bytes >= 1048576 && bytes % 1048576 === 0) return (bytes / 1048576) + " MiB";
  if (bytes >= 1024 && bytes % 1024 === 0) return (bytes / 1024) + " KiB";
  return bytes.toLocaleString() + " 字节";
}
function formatSize(b: number) { if (!b) return ""; return b < 1024 ? `${b}B` : b < 1048576 ? `${(b/1024).toFixed(1)}KB` : `${(b/1048576).toFixed(1)}MB`; }
const sl: Record<string,string> = { quarantined:"等待扫描",scanning:"扫描中",rejected:"已拒绝",stored:"已存储",compatibility_check:"检测中",converting:"转PDF中",preview_ready:"可预览",preview_warning:"可预览(警告)",user_confirmed:"已确认",ready:"就绪",ready_with_warning:"就绪(警告)",failed:"失败" };
const sc: Record<string,string> = { quarantined:"info",scanning:"warning",rejected:"danger",stored:"success",preview_ready:"",preview_warning:"warning",user_confirmed:"success",ready:"success",failed:"danger",converting:"warning" };
function canConfirm(s:string) { return ["preview_ready","preview_warning"].includes(s); }
</script>

<template>
  <div class="editor" v-loading="loading" :aria-busy="loading">
    <el-alert v-if="error" type="error" :closable="false">
      <template #title>{{ error }} <button class="link-button" @click="loadReport">重试</button></template>
    </el-alert>
    <template v-if="report">
      <header class="editor-header glass-heading">
        <div>
          <h1 class="page-title">{{ isEditable ? '提交周报' : '本周周报' }}</h1>
          <p class="page-sub">{{ report.period.iso_year }} 年{{ weekLabel }} · {{ weekRange(report.period) }}</p>
        </div>
        <div class="action-row">
          <span class="pill" :class="isEditable ? 'waiting' : 'good'">{{ report.status === 'archived' ? '已归档' : report.status === 'resubmitted' ? '更正中' : isEditable ? '待提交' : '已提交' }}</span>
          <el-button v-if="report.status === 'submitted'" :disabled="busy" @click="correctReport">更正周报</el-button>
        </div>
      </header>

      <section v-if="isEditable || attachments.length" class="panel files-panel">
        <header class="panel-head">
          <h2>周报附件<span v-if="attachments.length" class="file-count">{{ attachments.length }}</span></h2>
          <details v-if="isEditable && report.attachment_limits" class="limits">
            <summary>上传要求</summary>
            <p>支持 Word、Excel、PPT、PDF、TXT 和 Markdown。单个文件最多 {{ limitSize(report.attachment_limits.file_bytes) }}，每周最多 {{ report.attachment_limits.count }} 个附件，共 {{ limitSize(report.attachment_limits.total_bytes) }}。</p>
          </details>
        </header>
        <el-upload v-if="isEditable && !atLimit" drag :auto-upload="false" :show-file-list="false" :on-change="handleUpload" :disabled="busy" :accept="reportFileAccept">
          <span class="upload-glyph"><el-icon><Upload /></el-icon></span>
          <span class="upload-copy"><strong>{{ attachments.length ? '添加附件' : '选择周报文件' }}</strong><span>或拖放文件到这里</span></span>
        </el-upload>
        <p v-else-if="isEditable && atLimit" class="muted">附件数量已达上限，可替换已有文件。</p>
        <input ref="replacementInput" type="file" hidden :accept="reportFileAccept" @change="onReplacement" />
        <div v-auto-animate class="file-list">
          <article v-for="att in attachments" :key="att.id" class="att-row">
            <div class="att-info">
              <span class="soft-icon" aria-hidden="true"><el-icon><Document /></el-icon></span>
              <div class="file-meta">
                <strong>{{ att.uploaded_filename || att.original_filename }}</strong>
                <small>{{ formatSize(att.file_size_bytes) }}</small>
              </div>
              <el-tag :type="sc[att.status] as any || 'info'" size="small">{{ sl[att.status] || att.status }}</el-tag>
            </div>
            <p v-if="att.status === 'failed' && /\.docx?$/i.test(att.original_filename)" class="preview-help">Word 原件已保存，可重试预览或改传 Word 导出的 PDF。</p>
            <div class="att-actions">
              <button v-if="att.preview_status?.available" type="button" class="link-button" :aria-expanded="displayedFile === att.id"
                @click="togglePreview(att.id)">{{ displayedFile === att.id ? '收起预览' : '预览 PDF' }}</button>
              <button v-if="isEditable && att.preview_status?.available && canConfirm(att.status)" class="link-button" :disabled="busy" @click="confirmPreview(att)">确认预览</button>
              <button v-if="isEditable && !att.preview_status?.available && ['stored','failed'].includes(att.status)" class="link-button" :disabled="busy" @click="retryPreview(att)">重新生成预览</button>
              <a v-if="!['uploading','quarantined','scanning','rejected'].includes(att.status)" class="link-button" :href="`/api/v1/attachments/${att.id}/download`">下载原件</a>
              <button v-if="isEditable" class="link-button" :disabled="busy" @click="chooseReplacement(att)">替换</button>
              <button v-if="isEditable" class="link-button danger" :disabled="busy" @click="removeAttachment(att)">删除</button>
              <el-radio v-if="isEditable && available.length > 1 && att.preview_status?.available" v-model="selectedId" :value="att.id" :disabled="busy">周报主文件</el-radio>
            </div>
          </article>
        </div>
      </section>

      <section v-if="displayedFile || hasText" class="panel preview-panel">
        <header class="panel-head preview-header">
          <h2>{{ displayedFile ? '文件预览' : '周报正文' }}</h2>
          <a v-if="displayedFile" class="link-button" :href="`/api/v1/attachments/${displayedFile}/preview-content`" target="_blank" rel="noopener">打开原 PDF</a>
        </header>
        <PresentationDocument :attachment-id="displayedFile" :content="report.draft_content_json || {}" :author="report.owner_name" />
      </section>
      <ProgressSummary v-if="report.current_revision_id && !isEditable" :revision-id="report.current_revision_id" />
      <footer v-if="isEditable" class="submit-bar glass-panel">
        <span>{{ submitHint }}</span>
        <el-button type="primary" :loading="submitting" :disabled="busy || !canSubmit" @click="handleSubmit">提交周报</el-button>
      </footer>
    </template>
  </div>
</template>

<style scoped>
.editor { display:grid; gap:20px; min-width:0; min-height:160px; align-content:start; }
.editor-header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; }
.files-panel .panel-head, .preview-header { margin-bottom:12px; }
.file-count { margin-left:7px; font-size:13px; color:var(--muted); font-weight:500; }
.limits { position:relative; font-size:12px; color:var(--muted); }
.limits summary { cursor:pointer; padding:5px 0; }
.limits p { position:absolute; right:0; z-index:2; width:min(250px,66vw); padding:12px 14px; background:var(--paper); border:1px solid var(--line); border-radius:7px; line-height:1.7; box-shadow:0 4px 14px #234d3020; }
.editor :deep(.el-upload) { width:100%; }
.editor :deep(.el-upload-dragger) { display:flex; align-items:center; justify-content:center; gap:13px; background:var(--glass-inset); border-color:#71967e; padding:23px 12px; }
.editor :deep(.el-upload-dragger:hover), .editor :deep(.el-upload-dragger.is-dragover) { border-color:var(--teal); background:var(--glass-field); }
.upload-glyph { display:grid; place-items:center; background:#e0eedf; border-radius:8px; width:39px; height:39px; color:var(--teal); font-size:22px; }
.upload-copy { display:grid; gap:4px; text-align:left; }
.upload-copy strong { color:var(--teal); font-size:15px; }
.upload-copy > span, .file-meta small { color:var(--muted); font-size:12px; }
.att-row { border-top:1px solid var(--line); padding:14px 0; }
.att-row:first-child { margin-top:10px; }
.att-row:last-child { padding-bottom:0; }
.att-info { display:flex; align-items:center; gap:10px; }
.file-meta { flex:1; min-width:0; }
.file-meta strong { overflow-wrap:anywhere; font-size:14px; }
.file-meta small { display:block; margin-top:3px; }
.att-actions { display:flex; flex-wrap:wrap; align-items:center; gap:2px 14px; margin:5px 0 0 44px; }
.att-actions button:disabled { opacity:.55; }
.att-actions .danger { color:#994b43; }
.preview-help { margin:7px 0; color:var(--muted); font-size:13px; }
.preview-header { flex-wrap:wrap; }
.submit-bar { display:flex; align-items:center; justify-content:space-between; gap:14px; padding:12px 16px; position:sticky; bottom:10px; z-index:3; border:1px solid; border-radius:9px; }
.submit-bar span { font-size:13px; color:var(--muted); overflow-wrap:anywhere; }
@media (max-width:550px) { .att-actions { margin-left:0; } .submit-bar { bottom:4px; } }
</style>
