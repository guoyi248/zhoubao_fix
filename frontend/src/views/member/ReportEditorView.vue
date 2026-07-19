<script setup lang="ts">
/**
 * 周报编辑器 — 上传文件 → 查看PDF → 确认 → 提交。
 * 已提交后显示状态，下个周期自动创建新草稿。
 */
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "@/utils/api";

const router = useRouter();

interface ReportData {
  id: string; status: string; period: { iso_year: number; iso_week: number };
}

interface AttInfo {
  id: string; original_filename: string; status: string;
  file_size_bytes: number; detected_mime: string;
  preview_status?: { available: boolean; page_count: number };
  compatibility_report?: { warnings: string[] };
}

const report = ref<ReportData | null>(null);
const attachments = ref<AttInfo[]>([]);
const uploading = ref(false);
const loading = ref(true);
const submitting = ref(false);
const confirming = ref<string | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const weekLabel = computed(() => report.value ? `第 ${report.value.period.iso_week} 周` : "");
const isEditable = computed(() => report.value?.status === "draft");

// 有附件可提交（至少一个已确认或 PDF 已就绪）
const canSubmit = computed(() => {
  if (!attachments.value.length) return false;
  return attachments.value.some((a) =>
    ["user_confirmed", "preview_ready", "ready", "ready_with_warning"].includes(a.status),
  );
});

// 加载报告
onMounted(async () => {
  try {
    const { data } = await api.get("/me/reports/current");
    report.value = data;
    if (data.status === "draft") {
      await loadAttachments(data.id);
      startPolling();
    }
  } catch (e: any) { ElMessage.error(e.message); }
  loading.value = false;
});

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer); });

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (report.value?.id) loadAttachments(report.value.id);
  }, 3000);
}

async function loadAttachments(reportId: string) {
  try {
    await api.get(`/me/reports/${reportId}`);
  } catch {}
}

// 上传
async function handleUpload(file: any) {
  if (!report.value) return;
  uploading.value = true;
  try {
    const form = new FormData();
    form.append("file", file.raw || file);
    const { data } = await api.post(`/me/reports/${report.value.id}/attachments`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    attachments.value.unshift(data);
    ElMessage.success(`${data.original_filename} 上传成功`);
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || e.message || "上传失败");
  } finally {
    uploading.value = false;
  }
}

// 确认预览
async function confirmPreview(att: AttInfo) {
  confirming.value = att.id;
  try {
    await api.post(`/attachments/${att.id}/confirm`, { confirmed: true });
    att.status = "user_confirmed";
    ElMessage.success("已确认");
  } catch (e: any) {
    ElMessage.error(e.message || "确认失败");
  } finally {
    confirming.value = null;
  }
}

// 删除附件
async function removeAttachment(att: AttInfo) {
  try {
    await api.delete(`/attachments/${att.id}/delete`);
    attachments.value = attachments.value.filter((a) => a.id !== att.id);
  } catch (e: any) {
    ElMessage.error(e.message || "删除失败");
  }
}

// 替换附件——上传新文件覆盖旧的
async function replaceAttachment(att: AttInfo, file: any) {
  await ElMessageBox.confirm(
    `确认用 "${file.raw?.name || file.name}" 替换 "${att.original_filename}"？\n旧文件将被删除，此操作不可撤销。`,
    "确认替换",
    { type: "warning", confirmButtonText: "确认替换", cancelButtonText: "取消" },
  );
  try {
    const form = new FormData();
    form.append("file", file.raw || file);
    const { data } = await api.post(`/attachments/${att.id}/replace`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    const idx = attachments.value.findIndex((a) => a.id === att.id);
    if (idx >= 0) attachments.value[idx] = data;
    ElMessage.success(`已替换为 ${data.original_filename}`);
  } catch (e: any) {
    if (e !== "cancel") ElMessage.error(e.response?.data?.message || e.message || "替换失败");
  }
}

// 提交周报
async function handleSubmit() {
  if (!report.value || !canSubmit.value) return;
  await ElMessageBox.confirm("确认提交本周周报？提交后将生成不可变修订版。", "提交确认");
  submitting.value = true;
  try {
    const confirmed = attachments.value.find((a) => a.status === "user_confirmed");
    await api.post(`/me/reports/${report.value.id}/submit`, {
      confirmed_pdf_attachment_id: confirmed?.id || null,
    });
    ElMessage.success("周报已提交！");
    router.push("/");
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || e.message || "提交失败");
  } finally {
    submitting.value = false;
  }
}

function formatSize(bytes: number) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

const statusLabel: Record<string, string> = {
  quarantined: "等待扫描", scanning: "扫描中", rejected: "已拒绝",
  stored: "已存储", compatibility_check: "检测中", converting: "转PDF中",
  preview_ready: "可预览", preview_warning: "可预览(有警告)",
  user_confirmed: "已确认", ready: "就绪", ready_with_warning: "就绪(警告)",
  failed: "失败", password_protected: "有密码", unsupported: "不支持",
  extracting: "抽取中", analyzing: "AI分析中",
};
const statusColor: Record<string, string> = {
  quarantined: "info", scanning: "warning", rejected: "danger",
  stored: "success", preview_ready: "", preview_warning: "warning",
  user_confirmed: "success", ready: "success", failed: "danger",
  converting: "warning",
};

function canConfirm(s: string) { return ["preview_ready", "preview_warning"].includes(s); }
function canDelete(s: string) { return s !== "user_confirmed"; }
</script>

<template>
  <div class="editor" v-loading="loading">
    <div class="editor-header">
      <h2>{{ isEditable ? '提交周报' : '周报详情' }} — {{ weekLabel }}</h2>
      <div style="display:flex;gap:8px;align-items:center">
        <el-tag v-if="!isEditable" type="success" size="large">已提交</el-tag>
        <el-button v-else type="primary" size="large" :disabled="!canSubmit" :loading="submitting" @click="handleSubmit">
          {{ attachments.length ? '提交周报' : '请先上传文件' }}
        </el-button>
      </div>
    </div>

    <!-- 上传区 -->
    <el-card v-if="isEditable" class="upload-card">
      <template #header>
        <strong>上传 Word / PDF 文件</strong>
        <span style="color:#909399;font-size:12px;margin-left:8px">
          支持 .docx .doc .xlsx .xls .pptx .ppt .pdf .txt
        </span>
      </template>
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        :on-change="handleUpload"
        :disabled="uploading"
        accept=".docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.txt,.md"
      >
        <div style="font-size:36px;color:#409eff;margin-bottom:8px">📁</div>
        <div style="font-size:14px">拖拽文件到此处或 <em>点击选择</em></div>
        <div style="font-size:12px;color:#999;margin-top:4px">推荐上传 PDF 获得最佳展示效果</div>
      </el-upload>
    </el-card>

    <!-- 附件列表 -->
    <el-card v-if="attachments.length" style="margin-top:12px">
      <template #header><strong>附件 ({{ attachments.length }})</strong></template>
      <div v-for="att in attachments" :key="att.id" class="att-row">
        <div class="att-info">
          <span class="att-name">{{ att.original_filename }}</span>
          <span class="att-size">{{ formatSize(att.file_size_bytes) }}</span>
          <el-tag :type="statusColor[att.status] as any || 'info'" size="small">
            {{ statusLabel[att.status] || att.status }}
          </el-tag>
        </div>
        <!-- 警告 -->
        <div v-if="att.compatibility_report?.warnings?.length" class="att-warn">
          ⚠ {{ att.compatibility_report.warnings[0] }}
        </div>
        <!-- 操作 -->
        <div class="att-actions">
          <a v-if="att.status !== 'uploading'" :href="`/api/v1/attachments/${att.id}/preview-content`" target="_blank">
            <el-button size="small" text>查看 PDF</el-button>
          </a>
          <el-button v-if="canConfirm(att.status)" size="small" type="success" :loading="confirming===att.id" @click="confirmPreview(att)">
            确认无误
          </el-button>
          <a :href="`/api/v1/attachments/${att.id}/download`">
            <el-button size="small" text>下载原件</el-button>
          </a>
          <el-button v-if="canDelete(att.status)" size="small" text type="danger" @click="removeAttachment(att)">删除</el-button>
          <!-- 替换按钮：隐藏的 file input -->
          <label v-if="isEditable" style="cursor:pointer;font-size:12px;color:#409eff;margin-left:8px">
            替换
            <input type="file" hidden :accept="'.docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.txt,.md'"
              @change="(e: any) => { if(e.target.files[0]) replaceAttachment(att, e.target.files[0]); e.target.value=''; }" />
          </label>
        </div>
      </div>
    </el-card>

    <!-- 已提交时显示 PDF -->
    <div v-if="!isEditable && attachments.length" style="margin-top:12px">
      <el-card v-for="att in attachments.filter(a=>a.status==='user_confirmed')" :key="att.id">
        <template #header>已提交的周报 PDF</template>
        <iframe :src="`/api/v1/attachments/${att.id}/preview-content`" width="100%" height="600px" frameborder="0" />
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.editor { padding: 24px; max-width: 780px; margin: 0 auto; }
.editor-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.editor-header h2 { font-size: 20px; margin: 0; }
.upload-card { margin-bottom: 12px; }
.att-row { padding: 10px 0; border-bottom: 1px solid #f5f5f5; }
.att-row:last-child { border-bottom: none; }
.att-info { display: flex; align-items: center; gap: 12px; }
.att-name { font-weight: 500; flex: 1; font-size: 14px; }
.att-size { font-size: 12px; color: #999; min-width: 60px; }
.att-warn { margin-top: 4px; font-size: 12px; color: #e6a23c; }
.att-actions { display: flex; gap: 6px; margin-top: 6px; }
</style>
