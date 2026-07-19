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
const convertProgress = ref(0);
const convertMsg = ref("");
const newAttachId = ref("");

const isSubmitted = computed(() => report.value?.status === "submitted");
const weekLabel = computed(() => report.value ? `第 ${report.value.period.iso_week} 周` : "");
const deadlineText = computed(() => {
  if (!report.value?.period.deadline) return "";
  const d = new Date(report.value.period.deadline);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${d.getHours()}:00 截止`;
});

// 找到最新的 user_confirmed 附件（用于显示 PDF）
const latestConfirmed = computed(() => {
  const confirmed = attachments.value.filter(a => a.status === "user_confirmed");
  if (!confirmed.length) return null;
  return confirmed[confirmed.length - 1]; // 最新的
});

onMounted(async () => {
  try {
    const { data } = await api.get("/me/reports/current");
    report.value = data;
    await refreshAttachments(data.id);
    if (userStore.isAdmin) {
      try {
        const { data: s } = await api.get(`/admin/reports/?period=${data.reporting_period_id}`);
        submissionCount.value = Array.isArray(s) ? s.length : 0;
      } catch {}
    }
  } catch {} finally { loading.value = false; }
});

async function refreshAttachments(reportId: string) {
  try {
    const { data } = await api.get(`/me/reports/${reportId}`);
    // The report detail doesn't include attachments list directly,
    // load from the revisions' confirmed_pdf
    if (data.revisions?.length) {
      const latest = data.revisions[0];
      if (latest.confirmed_pdf_attachment_id) {
        attachments.value = [{ id: latest.confirmed_pdf_attachment_id, status: "user_confirmed" }];
      }
    }
  } catch {}
}

async function correctReport() {
  await ElMessageBox.confirm("上传新文件将覆盖当前已提交的周报。继续？", "更正周报", { type: "warning" });
  correcting.value = true;
  try {
    const { data } = await api.post(`/me/reports/${report.value.id}/resubmit`, {});
    report.value.status = "resubmitted";
    ElMessage.success("可以上传新文件了");
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || "操作失败");
    correcting.value = false;
  }
}

async function handleCorrectUpload(file: any) {
  if (!report.value) return;
  uploading.value = true;
  convertProgress.value = 10;
  convertMsg.value = "上传中...";
  try {
    const form = new FormData(); form.append("file", file.raw || file);
    const { data } = await api.post(`/me/reports/${report.value.id}/attachments`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    newAttachId.value = data.id;
    convertProgress.value = 30;
    convertMsg.value = "转换中...";

    // Poll for conversion
    let attempts = 0;
    const timer = setInterval(async () => {
      try {
        const { data: s } = await api.get(`/attachments/${newAttachId.value}/status`);
        if (s.status === "converting") {
          convertProgress.value = Math.min(30 + attempts * 5, 80);
          convertMsg.value = "正在转 PDF...";
        } else if (s.status === "preview_ready" || s.status === "preview_warning") {
          clearInterval(timer);
          convertProgress.value = 85;
          convertMsg.value = "转换完成，请确认提交";
          // Confirm and wait for user to click submit
          await api.post(`/attachments/${newAttachId.value}/confirm`, { confirmed: true });
          convertProgress.value = 100;
          convertMsg.value = "已就绪，点击「确认提交」完成";
          ElMessage.success("PDF 转换完成，请点击「确认提交更正」");
        } else if (s.status === "failed") {
          clearInterval(timer);
          convertProgress.value = 0;
          convertMsg.value = "转换失败";
          ElMessage.error("转换失败，请重试");
          uploading.value = false;
        }
        if (++attempts > 30 && s.status !== "failed") {
          clearInterval(timer);
          ElMessage.error("转换超时");
          uploading.value = false;
        }
      } catch { clearInterval(timer); uploading.value = false; }
    }, 2000);
  } catch (e: any) {
    ElMessage.error(e.message || "上传失败");
    uploading.value = false;
  }
}

async function confirmCorrection() {
  if (!report.value || !newAttachId.value) return;
  await ElMessageBox.confirm("确认用新文件覆盖已提交的周报？", "确认提交", { type: "warning" });
  try {
    await api.post(`/me/reports/${report.value.id}/submit`, {
      confirmed_pdf_attachment_id: newAttachId.value,
    });
    report.value.status = "submitted";
    attachments.value = [{ id: newAttachId.value, status: "user_confirmed" }];
    correcting.value = false;
    newAttachId.value = "";
    convertProgress.value = 0;
    convertMsg.value = "";
    uploading.value = false;
    ElMessage.success("更正完成，周报已重新提交");
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || "提交失败");
  }
}

</script>

<template>
  <div class="dashboard" v-loading="loading">
    <div class="dash-header">
      <div>
        <h2>本周工作台</h2>
        <p class="period-info">{{ weekLabel }} · {{ deadlineText }}</p>
      </div>
      <div class="header-actions">
        <el-button v-if="!isSubmitted && !correcting" type="primary" size="large" @click="router.push('/reports/current')">填写本周周报</el-button>
        <el-tag v-else-if="isSubmitted && !correcting" type="success" size="large">已提交</el-tag>
      </div>
    </div>

    <!-- 更正模式：上传 + 进度 + 确认 -->
    <el-card v-if="correcting">
      <template #header><strong>🔄 更正周报 — 上传新文件覆盖</strong></template>

      <!-- 上传区 -->
      <el-upload v-if="!uploading" drag :auto-upload="false" :show-file-list="false" :on-change="handleCorrectUpload"
        accept=".docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.txt,.md">
        <div style="font-size:36px;color:#e6a23c">📁</div>
        <div style="font-size:14px">拖拽新文件或 <em>点击选择</em></div>
        <div style="font-size:12px;color:#999;margin-top:4px">Word/Excel/PPT 自动转 PDF，PDF 直接使用</div>
      </el-upload>

      <!-- 进度条 -->
      <div v-else style="padding:20px 0">
        <div style="margin-bottom:8px;font-size:14px">{{ convertMsg }}</div>
        <el-progress :percentage="convertProgress" :status="convertProgress===100?'success':''" :stroke-width="20" />
        <div style="margin-top:12px;display:flex;gap:8px">
          <el-button v-if="convertProgress >= 85" type="primary" size="large" @click="confirmCorrection">
            确认提交更正
          </el-button>
          <el-button text @click="correcting=false;newAttachId='';uploading=false;convertProgress=0">取消</el-button>
        </div>
      </div>
    </el-card>

    <!-- 状态卡片 -->
    <el-row :gutter="16" class="dash-cards">
      <el-col :span="8">
        <el-card shadow="hover">
          <div style="text-align:center">
            <div style="font-size:24px;font-weight:bold">{{ isSubmitted ? '已提交' : correcting ? '更正中' : '草稿' }}</div>
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
    <el-card v-if="isSubmitted && latestConfirmed" style="margin-top:12px">
      <template #header>提交的周报 PDF</template>
      <iframe :src="`/api/v1/attachments/${latestConfirmed.id}/preview-content`" width="100%" height="800px" frameborder="0" style="border:1px solid #e5e5e5;border-radius:4px" />
    </el-card>

    <!-- 快捷操作 -->
    <el-row :gutter="16" class="dash-actions" style="margin-top:16px">
      <el-col :span="6">
        <el-card shadow="hover" class="action-card" @click="router.push('/reports/current')"><span>✏️ 写周报</span></el-card>
      </el-col>
      <el-col :span="6" v-if="isSubmitted">
        <el-card shadow="hover" class="action-card" @click="correctReport"><span>🔄 更正周报</span></el-card>
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
.action-card { cursor: pointer; text-align: center; padding: 16px 0; transition: transform 0.15s; }
.action-card:hover { transform: translateY(-2px); }
.action-card span { font-size: 14px; }
</style>
