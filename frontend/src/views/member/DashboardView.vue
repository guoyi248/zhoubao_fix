<script setup lang="ts">
/**
 * 本周工作台 — 首页第一屏。
 * 展示当前周期状态、快速入口、管理员看团队概览。
 */
import { ref, onMounted, computed } from "vue";
import { useRouter } from "vue-router";
import { useUserStore } from "@/stores/user";
import api from "@/utils/api";

const router = useRouter();
const userStore = useUserStore();

interface ReportInfo {
  id: string;
  status: string;
  reporting_period_id: string;
  current_revision_id: string | null;
  optimistic_version: number;
  updated_at: string;
  period: { iso_year: number; iso_week: number; deadline: string };
}

const report = ref<ReportInfo | null>(null);
const submissionCount = ref(0);
const pendingReports = ref(0);
const loading = ref(true);

const isSubmitted = computed(() =>
  report.value?.status === "submitted" || report.value?.status === "resubmitted",
);

const weekLabel = computed(() => {
  if (!report.value) return "";
  return `第 ${report.value.period.iso_week} 周`;
});

const deadlineText = computed(() => {
  if (!report.value?.period.deadline) return "";
  const d = new Date(report.value.period.deadline);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${d.getHours()}:00 截止`;
});

onMounted(async () => {
  try {
    const { data } = await api.get("/me/reports/current");
    report.value = data;

    if (userStore.isAdmin) {
      const { data: summary } = await api.get(`/admin/reports/?period=${data.reporting_period_id}`);
      submissionCount.value = Array.isArray(summary) ? summary.length : 0;

      const { data: meetingData } = await api.get("/admin/meetings/list");
      pendingReports.value = (Array.isArray(meetingData) ? meetingData.length : 0);
    }
  } catch {
    // 未登录等
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- 标题栏 -->
    <div class="dash-header">
      <div>
        <h2>本周工作台</h2>
        <p class="period-info">{{ weekLabel }} · {{ deadlineText }}</p>
      </div>
      <div class="header-actions">
        <el-button
          v-if="!isSubmitted"
          type="primary"
          size="large"
          @click="router.push('/reports/current')"
        >
          填写本周周报
        </el-button>
        <el-tag v-else type="success" size="large">已提交</el-tag>
      </div>
    </div>

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
          <p class="card-hint" v-if="!isSubmitted">请在截止时间前完成提交</p>
          <p class="card-hint" v-else>管理员可在组会中查看</p>
        </el-card>
      </el-col>

      <el-col :span="8" v-if="userStore.isAdmin">
        <el-card shadow="hover">
          <div style="text-align:center">
            <div style="font-size:24px;font-weight:bold">{{ submissionCount }} <span style="font-size:14px">份</span></div>
            <div style="font-size:12px;color:#999">已提交</div>
          </div>
          <p class="card-hint">本周已提交周报</p>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card shadow="hover">
          <div style="text-align:center">
            <div style="font-size:24px;font-weight:bold">{{ weekLabel }}</div>
            <div style="font-size:12px;color:#999">当前周期</div>
          </div>
          <p class="card-hint">{{ deadlineText }}</p>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷操作 -->
    <el-row :gutter="16" class="dash-actions">
      <el-col :span="6">
        <el-card shadow="hover" class="action-card" @click="router.push('/reports/current')">
          <el-icon :size="28"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg></el-icon>
          <span>写周报</span>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="action-card" @click="router.push('/reports')">
          <el-icon :size="28"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3h-4.18C14.4 1.84 13.3 1 12 1s-2.4.84-2.82 2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-7 0a1 1 0 0 1 1 1 1 1 0 0 1-1 1 1 1 0 0 1-1-1 1 1 0 0 1 1-1zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"/></svg></el-icon>
          <span>历史周报</span>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="action-card" @click="router.push('/private-plans')">
          <el-icon :size="28"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M18 8h-1V6a5 5 0 0 0-10 0v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2zm-6 9a2 2 0 1 1 0-4 2 2 0 0 1 0 4zm3-9H9V6a3 3 0 1 1 6 0v2z"/></svg></el-icon>
          <span>个人计划</span>
        </el-card>
      </el-col>
      <el-col :span="6" v-if="userStore.isAdmin">
        <el-card shadow="hover" class="action-card" @click="router.push('/admin/reports')">
          <el-icon :size="28"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5s-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg></el-icon>
          <span>全员周报</span>
        </el-card>
      </el-col>
    </el-row>

    <!-- 管理员: 组会入口 -->
    <el-row v-if="userStore.isAdmin" :gutter="16" style="margin-top: 12px">
      <el-col :span="24">
        <el-card shadow="hover">
          <div class="meeting-entry">
            <div>
              <h4>组会模式</h4>
              <p style="color: #909399; font-size: 13px">全屏展示团队周报，逐人切换，记录行动项</p>
            </div>
            <el-button type="primary" @click="router.push('/admin/reports')">进入组会</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dashboard {
  padding: 24px;
  max-width: 960px;
  margin: 0 auto;
}

.dash-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.dash-header h2 {
  margin: 0 0 4px;
  font-size: 22px;
}

.period-info {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.dash-cards {
  margin-bottom: 16px;
}

.card-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.action-card {
  cursor: pointer;
  text-align: center;
  padding: 20px 0;
  transition: transform 0.15s;
}
.action-card:hover {
  transform: translateY(-2px);
}
.action-card span {
  display: block;
  margin-top: 8px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.meeting-entry {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.meeting-entry h4 {
  margin: 0 0 4px;
  font-size: 15px;
}
</style>
