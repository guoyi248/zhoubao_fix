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
const convertProgress = ref(0);
const convertMsg = ref("");

const isSubmitted = computed(() => report.value?.status === "submitted");
const weekLabel = computed(() => report.value ? `第 ${report.value.period.iso_week} 周` : "");
const deadlineText = computed(() => {
  if (!report.value?.period.deadline) return "";
  const d = new Date(report.value.period.deadline);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${d.getHours()}:00 截止`;
});
const latestConfirmed = computed(() => {
  const ok = attachments.value.filter(a => ["user_confirmed","preview_ready","ready","ready_with_warning"].includes(a.status));
  return ok.length ? ok[ok.length - 1] : null;
});

onMounted(async () => {
  try {
    const { data } = await api.get("/me/reports/current");
    report.value = data;
    if (data.revisions?.length) {
      const rev = data.revisions[0];
      if (rev.confirmed_pdf_attachment_id)
        attachments.value = [{ id: rev.confirmed_pdf_attachment_id, status: "user_confirmed" }];
    }
    if (userStore.isAdmin) {
      try {
        const { data: s } = await api.get(`/admin/reports/?period=${data.reporting_period_id}`);
        submissionCount.value = Array.isArray(s) ? s.length : 0;
      } catch {}
    }
  } catch {} finally { loading.value = false; }
});

function correctReport() {
  (document.getElementById("correct-input") as HTMLInputElement)?.click();
}

async function doCorrect(file: any) {
  if (!report.value) return;
  await ElMessageBox.confirm("上传新文件将覆盖当前已提交的周报。继续？", "更正周报", { type: "warning" });
  correcting.value = true;
  convertProgress.value = 30;
  convertMsg.value = "上传并转换中...";
  try {
    const form = new FormData(); form.append("file", file.raw || file);
    const { data } = await api.post(`/me/reports/${report.value.id}/correct`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    convertProgress.value = 100;
    report.value.status = "submitted";
    attachments.value = [{ id: data.attachment_id, status: "user_confirmed" }];
    ElMessage.success(`更正完成！Revision #${data.revision_no}`);
  } catch (e: any) { ElMessage.error(e.response?.data?.message || "更正失败"); }
  finally { correcting.value = false; }
}
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <div class="dash-header">
      <div>
        <h2>本周工作台</h2>
        <p class="period-info">{{ weekLabel }} · {{ deadlineText }}</p>
      </div>
      <div>
        <el-button v-if="!isSubmitted" type="primary" size="large" @click="router.push('/reports/current')">填写本周周报</el-button>
        <el-tag v-else type="success" size="large">已提交</el-tag>
      </div>
    </div>

    <!-- 更正进度条 -->
    <el-card v-if="correcting" style="margin-bottom:16px;border:1px solid var(--el-color-warning)">
      <div style="margin-bottom:8px;font-size:14px">{{ convertMsg }}</div>
      <el-progress :percentage="convertProgress" :stroke-width="20" />
    </el-card>

    <!-- 状态卡片 -->
    <el-row :gutter="16" class="dash-cards">
      <el-col :span="8"><el-card shadow="hover"><div style="text-align:center"><div style="font-size:24px;font-weight:bold">{{ isSubmitted ? '已提交' : '草稿' }}</div><div style="font-size:12px;color:#999">周报状态</div></div></el-card></el-col>
      <el-col :span="8" v-if="userStore.isAdmin"><el-card shadow="hover"><div style="text-align:center"><div style="font-size:24px;font-weight:bold">{{ submissionCount }} <span style="font-size:14px">份</span></div><div style="font-size:12px;color:#999">已提交</div></div></el-card></el-col>
      <el-col :span="8"><el-card shadow="hover"><div style="text-align:center"><div style="font-size:24px;font-weight:bold">{{ weekLabel }}</div><div style="font-size:12px;color:#999">当前周期</div></div></el-card></el-col>
    </el-row>

    <!-- PDF preview -->
    <el-card v-if="isSubmitted && latestConfirmed" style="margin-top:12px">
      <template #header>提交的 PDF</template>
      <iframe :src="`/api/v1/attachments/${latestConfirmed.id}/preview-content`" width="100%" height="800px" frameborder="0" style="border:1px solid #e5e5e5;border-radius:4px" />
    </el-card>

    <!-- 快捷操作 -->
    <el-row :gutter="16" style="margin-top:16px">
      <el-col :span="6"><el-card shadow="hover" class="ac" @click="router.push('/reports/current')"><span>写周报</span></el-card></el-col>
      <el-col :span="6" v-if="isSubmitted">
        <el-card shadow="hover" class="ac" @click="correctReport"><span>更正周报</span></el-card>
        <input id="correct-input" type="file" hidden accept=".docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.txt,.md" @change="(e:any)=>{if(e.target.files[0])doCorrect(e.target.files[0]);e.target.value=''}" />
      </el-col>
      <el-col :span="6"><el-card shadow="hover" class="ac" @click="router.push('/reports')"><span>历史周报</span></el-card></el-col>
      <el-col :span="6"><el-card shadow="hover" class="ac" @click="router.push('/private-plans')"><span>个人计划</span></el-card></el-col>
      <el-col :span="6" v-if="userStore.isAdmin"><el-card shadow="hover" class="ac" @click="router.push('/admin/reports')"><span>全员周报</span></el-card></el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dashboard { padding: 24px; max-width: 960px; margin: 0 auto; }
.dash-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.dash-header h2 { margin: 0 0 4px; font-size: 22px; }
.period-info { margin: 0; color: var(--el-text-color-secondary); font-size: 14px; }
.dash-cards { margin-bottom: 16px; }
.ac { cursor: pointer; text-align: center; padding: 16px 0; transition: transform 0.15s; }
.ac:hover { transform: translateY(-2px); }
.ac span { font-size: 14px; }
</style>
