<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import api from "@/utils/api";

interface ReportItem {
  id: string;
  owner_name: string;
  period_label: string;
  status: string;
  owner_id: string;
  updated_at: string;
}

const router = useRouter();
const reports = ref<ReportItem[]>([]);
const loading = ref(true);
const statusFilter = ref("");

const statusTag: Record<string, string> = {
  draft: "info",
  submitted: "success",
  resubmitted: "warning",
  archived: "",
};

const statusText: Record<string, string> = {
  draft: "草稿",
  submitted: "已提交",
  resubmitted: "补交",
  archived: "已归档",
};

onMounted(loadReports);

async function loadReports() {
  loading.value = true;
  try {
    const params = new URLSearchParams();
    if (statusFilter.value) params.set("status", statusFilter.value);
    const { data } = await api.get(`/admin/reports/?${params.toString()}`);
    reports.value = Array.isArray(data) ? data : [];
  } finally {
    loading.value = false;
  }
}

async function createMeeting() {
  try {
    const { data } = await api.post("/admin/meetings/", {});
    router.push(`/admin/meetings/${data.id}`);
  } catch (e: any) {
    // 可能已有进行中的会议
    if (e.response?.data?.meeting_id) {
      router.push(`/admin/meetings/${e.response.data.meeting_id}`);
    }
  }
}
</script>

<template>
  <div class="all-reports" v-loading="loading">
    <div class="reports-header">
      <h2>全员周报</h2>
      <div class="header-actions">
        <el-select v-model="statusFilter" placeholder="状态筛选" clearable size="small" @change="loadReports" style="width:120px">
          <el-option label="已提交" value="submitted" />
          <el-option label="补交" value="resubmitted" />
          <el-option label="已归档" value="archived" />
        </el-select>
        <el-button type="primary" size="small" @click="createMeeting">进入组会模式</el-button>
      </div>
    </div>

    <el-empty v-if="!loading && reports.length === 0" description="暂无周报数据" />

    <el-table :data="reports" style="width:100%" size="small">
      <el-table-column prop="owner_name" label="成员" width="120" />
      <el-table-column prop="period_label" label="周期" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag[row.status]" size="small">{{ statusText[row.status] || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" width="180">
        <template #default="{ row }">{{ row.updated_at?.slice(0, 16)?.replace('T', ' ') }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default>
          <el-button text type="primary" size="small">查看</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.all-reports { padding: 24px; }
.reports-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.reports-header h2 { font-size: 18px; margin: 0; }
.header-actions { display: flex; gap: 8px; align-items: center; }
</style>
