<script setup lang="ts">
/**
 * 周报编辑器 — 上传 Word/PDF，系统自动处理，确认后提交。
 */
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { UploadFilled } from "@element-plus/icons-vue";
import api from "@/utils/api";

const router = useRouter();

interface ReportData {
  id: string;
  status: string;
  reporting_period_id: string;
  period: { iso_year: number; iso_week: number; deadline: string };
  draft_content_json: any;
  optimistic_version: number;
}

interface AttachmentInfo {
  id: string;
  original_filename: string;
  status: string;
  file_size_bytes: number;
  detected_mime: string;
  compatibility_report?: {
    declared_fonts: string[];
    missing_fonts: string[];
    preview_level: string;
    warnings: string[];
  };
  preview_status?: {
    available: boolean;
    page_count: number;
    converter_version: string;
  };
}

const report = ref<ReportData | null>(null);
const attachments = ref<AttachmentInfo[]>([]);
const uploading = ref(false);
const loading = ref(true);
const submitting = ref(false);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const weekLabel = computed(() => {
  if (!report.value) return "";
  return `第 ${report.value.period.iso_week} 周`;
});

const canSubmit = computed(() => {
  if (!attachments.value.length) return false;
  // 所有附件必须已确认或就绪
  return attachments.value.every((a) =>
    ["user_confirmed", "ready", "ready_with_warning"].includes(a.status),
  );
});

const hasConfirmed = computed(() =>
  attachments.value.some((a) => a.status === "user_confirmed"),
);

onMounted(async () => {
  await loadReport();
  startPolling();
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});

function startPolling() {
  pollTimer = setInterval(refreshAttachments, 3000);
}

async function loadReport() {
  try {
    const { data } = await api.get("/me/reports/current");
    report.value = data;
    await refreshAttachments();
  } catch (e: any) {
    ElMessage.error(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
}

async function refreshAttachments() {
  if (!report.value) return;
  try {
    await api.get(`/me/reports/${report.value.id}`);
    // 加载附件列表 — 简化：用已知附件 ID 轮询
  } catch { /* ignore */ }
}

async function handleUpload(file: any) {
  if (!report.value) return;
  uploading.value = true;
  try {
    const form = new FormData();
    form.append("file", file.raw || file);
    const { data } = await api.post(
      `/me/reports/${report.value.id}/attachments`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    attachments.value.push(data);
    ElMessage.success(`"${data.original_filename}" 上传成功，正在处理...`);
    // 轮询状态
    pollAttachment(data.id);
  } catch (e: any) {
    ElMessage.error(e.message || "上传失败");
  } finally {
    uploading.value = false;
  }
}

async function pollAttachment(id: string) {
  const check = async () => {
    try {
      const { data } = await api.get(`/attachments/${id}/status`);
      const idx = attachments.value.findIndex((a) => a.id === id);
      if (idx >= 0) {
        attachments.value[idx].status = data.status;
        // 状态到达终态时加载详情
        if (
          ["preview_ready", "preview_warning", "ready", "ready_with_warning", "failed", "rejected"].includes(
            data.status,
          )
        ) {
          await loadAttachmentDetail(id);
        }
      }
    } catch { /* ignore */ }
  };
  check();
  // 继续轮询直到终态
  const timer = setInterval(async () => {
    const a = attachments.value.find((a) => a.id === id);
    if (!a || ["ready", "ready_with_warning", "user_confirmed", "failed", "rejected"].includes(a.status)) {
      clearInterval(timer);
      return;
    }
    await check();
  }, 2000);
}

async function loadAttachmentDetail(id: string) {
  try {
    const { data } = await api.get(`/attachments/${id}`);
    const idx = attachments.value.findIndex((a) => a.id === id);
    if (idx >= 0) {
      attachments.value[idx] = { ...attachments.value[idx], ...data };
    }
  } catch { /* ignore */ }
}

async function confirmPreview(att: AttachmentInfo) {
  try {
    await api.post(`/attachments/${att.id}/confirm`, { confirmed: true });
    att.status = "user_confirmed";
    ElMessage.success("预览已确认");
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function rejectPreview(att: AttachmentInfo) {
  try {
    await api.post(`/attachments/${att.id}/confirm`, { confirmed: false });
    att.status = "failed";
    ElMessage.warning("已标记为失败，请重新上传");
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function removeAttachment(att: AttachmentInfo) {
  try {
    await api.delete(`/attachments/${att.id}/delete`);
    attachments.value = attachments.value.filter((a) => a.id !== att.id);
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function handleSubmit() {
  if (!report.value || !canSubmit.value) return;
  await ElMessageBox.confirm("确认提交本周周报？附件预览已确认的内容将作为正式周报。", "提交确认");
  submitting.value = true;
  try {
    // 将首个已确认的 PDF 作为 confirmed_pdf
    const confirmed = attachments.value.find((a) => a.status === "user_confirmed");
    await api.post(`/me/reports/${report.value.id}/submit`, {
      confirmed_pdf_attachment_id: confirmed?.id || null,
    });
    ElMessage.success("周报已提交！");
    router.push("/");
  } catch (e: any) {
    ElMessage.error(e.message || "提交失败");
  } finally {
    submitting.value = false;
  }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

const statusLabel: Record<string, string> = {
  uploading: "上传中",
  quarantined: "等待扫描",
  scanning: "病毒扫描中",
  stored: "已安全存储",
  compatibility_check: "兼容性检测",
  converting: "正在转 PDF",
  preview_ready: "预览就绪 — 请确认",
  preview_warning: "预览就绪（有警告）— 请确认",
  user_confirmed: "✓ 已确认",
  extracting: "文本抽取中",
  analyzing: "AI 分析中",
  ready: "处理完成",
  ready_with_warning: "处理完成（有警告）",
  failed: "处理失败",
  rejected: "已拒绝",
};

const statusColor: Record<string, string> = {
  uploading: "info",
  quarantined: "info",
  scanning: "warning",
  stored: "success",
  compatibility_check: "warning",
  converting: "warning",
  preview_ready: "",
  preview_warning: "warning",
  user_confirmed: "success",
  extracting: "warning",
  analyzing: "warning",
  ready: "success",
  ready_with_warning: "warning",
  failed: "danger",
  rejected: "danger",
};
</script>

<template>
  <div class="editor" v-loading="loading">
    <div class="editor-header">
      <h2>提交周报 — {{ weekLabel }}</h2>
      <el-button
        type="primary"
        size="large"
        :disabled="!canSubmit || submitting"
        :loading="submitting"
        @click="handleSubmit"
      >
        {{ hasConfirmed ? "提交周报" : "请先确认预览" }}
      </el-button>
    </div>

    <!-- 上传区 -->
    <el-card class="upload-card">
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
        :disabled="uploading || report?.status !== 'draft'"
        accept=".docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.txt,.md"
      >
        <el-icon class="upload-icon"><upload-filled /></el-icon>
        <div class="upload-text">
          <p>将文件拖到此处，或<em>点击选择</em></p>
          <p class="hint">推荐上传 PDF，可获得最佳展示效果</p>
        </div>
      </el-upload>

      <!-- 附件列表 -->
      <div class="attachment-list" v-if="attachments.length">
        <div
          v-for="att in attachments"
          :key="att.id"
          class="attachment-item"
        >
          <div class="att-info">
            <span class="att-name">{{ att.original_filename }}</span>
            <span class="att-size">{{ formatSize(att.file_size_bytes) }}</span>
            <el-tag
              :type="statusColor[att.status] as any"
              size="small"
            >
              {{ statusLabel[att.status] || att.status }}
            </el-tag>
          </div>

          <!-- 兼容性警告 -->
          <div v-if="att.compatibility_report?.warnings?.length" class="att-warnings">
            <span v-for="w in att.compatibility_report.warnings" :key="w" class="warn-tag">
              ⚠ {{ w }}
            </span>
          </div>

          <!-- PDF 预览按钮 -->
          <div class="att-actions" v-if="att.status === 'preview_ready' || att.status === 'preview_warning'">
            <a :href="`/api/v1/attachments/${att.id}/preview-content`" target="_blank">
              <el-button size="small">查看 PDF 预览</el-button>
            </a>
            <el-button size="small" type="success" @click="confirmPreview(att)">
              确认无误
            </el-button>
            <el-button size="small" type="warning" @click="rejectPreview(att)">
              有问题，重新上传
            </el-button>
          </div>

          <!-- 已确认 -->
          <div v-if="att.status === 'user_confirmed'" class="att-confirmed">
            <el-tag type="success">已确认 — 将作为正式周报提交</el-tag>
          </div>

          <!-- 操作 -->
          <div class="att-actions">
            <a v-if="att.preview_status?.available" :href="`/api/v1/attachments/${att.id}/preview-content`" target="_blank">
              <el-button size="small" text>查看 PDF</el-button>
            </a>
            <a :href="`/api/v1/attachments/${att.id}/download`">
              <el-button size="small" text>下载原件</el-button>
            </a>
            <el-button
              v-if="report?.status === 'draft'"
              size="small"
              text
              type="danger"
              @click="removeAttachment(att)"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.editor {
  padding: 24px;
  max-width: 780px;
  margin: 0 auto;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.editor-header h2 { font-size: 20px; margin: 0; }

.upload-card { margin-bottom: 16px; }

.upload-icon { font-size: 48px; color: var(--el-color-primary); }

.upload-text { text-align: center; }
.upload-text p { margin: 4px 0; font-size: 14px; }
.upload-text .hint { font-size: 12px; color: var(--el-text-color-placeholder); }

.attachment-list { margin-top: 16px; }

.attachment-item {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  margin-bottom: 8px;
}

.att-info {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.att-name { font-weight: 500; flex: 1; }
.att-size { font-size: 12px; color: var(--el-text-color-placeholder); }

.att-warnings {
  margin: 6px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.warn-tag {
  font-size: 12px;
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  padding: 2px 6px;
  border-radius: 4px;
}

.att-actions {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}

.att-confirmed { margin-top: 6px; }
</style>
