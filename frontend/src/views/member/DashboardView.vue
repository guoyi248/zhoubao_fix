<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { useRouter } from "vue-router";
import { useUserStore } from "@/stores/user";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "@/utils/api";

const router = useRouter();
const userStore = useUserStore();

const report = ref<any>(null);
const attachments = ref<any[]>([]);
const submissionCount = ref(0);
const loading = ref(true);
const correcting = ref(false);
const uploading = ref(false);

const isSubmitted = computed(() =>
  report.value?.status === "submitted",
);
const isResubmitted = computed(() => report.value?.status === "resubmitted");
const weekLabel = computed(() => report.value ? `第 ${report.value.period.iso_week} 周` : "");
const deadlineText = computed(() => {
  if (!report.value?.period.deadline) return "";
  const d = new Date(report.value.period.deadline);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${d.getHours()}:00 截止`;
});
const confirmedAtt = computed(() => attachments.value.find(a => ["user_confirmed","preview_ready","ready"].includes(a.status)));

onMounted(async () => {
  try {
    const { data } = await api.get("/me/reports/current");
    report.value = data;
    await loadAttachments(data.id);
    if (userStore.isAdmin) {
      try {
        const { data: s } = await api.get(`/admin/reports/?period=${data.reporting_period_id}`);
        submissionCount.value = Array.isArray(s) ? s.length : 0;
      } catch {}
    }
  } catch {} finally { loading.value = false; }
});

async function loadAttachments(reportId: string) {
  try { await api.get(`/me/reports/${reportId}`); } catch {}
}

// 更正周报——上传新文件覆盖
async function correctReport() {
  await ElMessageBox.confirm("上传新文件将覆盖当前已提交的周报。继续？", "更正周报", { type: "warning" });
  correcting.value = true;
  try {
    const { data } = await api.post(`/me/reports/${report.value.id}/resubmit`, {});
    report.value.status = "resubmitted";
    ElMessage.success(data.detail || "可以上传新文件了");
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || e.message || "操作失败");
    correcting.value = false;
  }
}

async function handleCorrectUpload(file: any) {
  if (!report.value) return;
  uploading.value = true;
  try {
    const form = new FormData(); form.append("file", file.raw || file);
    const { data } = await api.post(`/me/reports/${report.value.id}/attachments`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    attachments.value.unshift(data);
    ElMessage.success(`${data.original_filename} 上传成功`);

    // Poll for conversion
    let attempts = 0;
    const timer = setInterval(async () => {
      try {
        const { data: s } = await api.get(`/attachments/${data.id}/status`);
        const idx = attachments.value.findIndex(a => a.id === data.id);
        if (idx >= 0) attachments.value[idx].status = s.status;
        if (s.status === "preview_ready") {
          clearInterval(timer);
          attachments.value[idx].status = "preview_ready";
          await api.post(`/attachments/${data.id}/confirm`, { confirmed: true });
          attachments.value[idx].status = "user_confirmed";
          // Auto-submit
          await api.post(`/me/reports/${report.value.id}/submit`, { confirmed_pdf_attachment_id: data.id });
          report.value.status = "submitted";
          ElMessage.success("更正完成，周报已重新提交！");
          correcting.value = false;
        }
        if (++attempts > 30) { clearInterval(timer); ElMessage.error("转换超时"); correcting.value = false; }
        if (s.status === "failed") { clearInterval(timer); ElMessage.error("转换失败"); correcting.value = false; }
      } catch { clearInterval(timer); correcting.value = false; }
    }, 2000);
  } catch (e: any) { ElMessage.error(e.message); correcting.value = false; }
  finally { uploading.value = false; }
}

function formatSize(b: number) { if (!b) return ""; return b < 1024 ? `${b}B` : b < 1048576 ? `${(b/1024).toFixed(1)}KB` : `${(b/1048576).toFixed(1)}MB`; }
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <div class="dash-header">
      <div>
        <h2>本周工作台</h2>
        <p class="period-info">{{ weekLabel }} · {{ deadlineText }}</p>
      </div>
      <div class="header-actions">
        <el-button v-if="!isSubmitted" type="primary" size="large" @click="router.push('/reports/current')">填写本周周报</el-button>
        <el-tag v-else type="success" size="large">已提交</el-tag>
      </div>
    </div>

    <!-- 更正模式：上传区 -->
    <el-card v-if="correcting" class="correct-card">
      <template #header><strong>上传新文件覆盖周报</strong></template>
      <el-upload drag :auto-upload="false" :show-file-list="false" :on-change="handleCorrectUpload" :disabled="uploading"
        accept=".docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.txt,.md">
        <div style="font-size:36px;color:#e6a23c">📁</div>
        <div style="font-size:14px">拖拽新文件或 <em>点击选择</em></div>
        <div style="font-size:12px;color:#999">上传后自动转换并覆盖提交</div>
      </el-upload>
      <div v-if="attachments.length" style="margin-top:8px">
        <div v-for="a in attachments" :key="a.id" style="font-size:12px;color:#666">
          {{ a.original_filename }} ({{ formatSize(a.file_size_bytes) }}) — {{ a.status }}
        </div>
      </div>
      <el-button text size="small" @click="correcting=false">取消</el-button>
    </el-card>

    <!-- 状态卡片 -->
    <el-row :gutter="16" class="dash-cards">
      <el-col :span="8">
        <el-card shadow="hover">
          <div style="text-align:center">
            <div style="font-size:24px;font-weight:bold">{{ isSubmitted ? '已提交' : '草稿' }}</div>
            <div style="font-size:12px;color:#999">周报状态
              <el-tag :type="isSubmitted ? 'success' : 'warning'" size="small" style="margin-left:4px">{{ isSubmitted ? '✓' : '待提交' }}</el-tag>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8" v-if="userStore.isAdmin">
        <el-card shadow="hover">
          <div style="text-align:center">
            <div style="font-size:24px;font-weight:bold">{{ submissionCount }} <span style="font-size:14px">份</span></div>
            <div style="font-size:12px;color:#999">已提交</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <div style="text-align:center">
            <div style="font-size:24px;font-weight:bold">{{ weekLabel }}</div>
            <div style="font-size:12px;color:#999">当前周期</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 已提交 PDF 预览 -->
    <el-card v-if="isSubmitted && confirmedAtt" style="margin-top:12px">
      <template #header>提交的周报 PDF</template>
      <iframe :src="`/api/v1/attachments/${confirmedAtt.id}/preview-content`" width="100%" height="800px" frameborder="0" style="border:1px solid #e5e5e5;border-radius:4px" />
    </el-card>

    <!-- 快捷操作 -->
    <el-row :gutter="16" class="dash-actions" style="margin-top:16px">
      <el-col :span="6">
        <el-card shadow="hover" class="action-card" @click="router.push('/reports/current')"><span>✏️ 写周报</span></el-card>
      </el-col>
      <el-col :span="6" v-if="isSubmitted">
        <el-card shadow="hover" class="action-card correct-card" @click="correctReport"><span>🔄 更正周报</span></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="action-card" @click="router.push('/reports')"><span>📋 历史周报</span></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="action-card" @click="router.push('/private-plans')"><span>🔒 个人计划</span></el-card>
      </el-col>
      <el-col :span="6" v-if="userStore.isAdmin">
        <el-card shadow="hover" class="action-card" @click="router.push('/admin/reports')"><span>👥 全员周报</span></el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dashboard { padding: 24px; max-width: 960px; margin: 0 auto; }
.dash-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.dash-header h2 { margin: 0 0 4px; font-size: 22px; }
.period-info { margin: 0; color: var(--el-text-color-secondary); font-size: 14px; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.dash-cards { margin-bottom: 16px; }
.correct-card { margin-bottom: 16px; border: 1px solid var(--el-color-warning); }
.action-card { cursor: pointer; text-align: center; padding: 16px 0; transition: transform 0.15s; }
.action-card:hover { transform: translateY(-2px); }
.action-card span { font-size: 14px; }
</style>
