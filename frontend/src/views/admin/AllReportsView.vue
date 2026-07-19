<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import api from "@/utils/api";
import ReportDetail from "@/components/report/ReportDetail.vue";

interface ReportItem {
  id: string; owner_name: string; period_label: string;
  status: string; updated_at: string;
}
const router = useRouter();
const reports = ref<ReportItem[]>([]);
const loading = ref(true);
const selectedId = ref("");
const statusFilter = ref("");
const statusTag: Record<string, string> = { draft: "info", submitted: "success", resubmitted: "warning" };
const statusText: Record<string, string> = { draft: "草稿", submitted: "已提交", resubmitted: "补交" };

onMounted(loadReports);
async function loadReports() {
  loading.value = true;
  try {
    const p = new URLSearchParams();
    if (statusFilter.value) p.set("status", statusFilter.value);
    const { data } = await api.get(`/admin/reports/?${p.toString()}`);
    reports.value = Array.isArray(data) ? data : [];
  } finally { loading.value = false; }
}
async function createMeeting() {
  try {
    const { data } = await api.post("/admin/meetings/", {});
    router.push(`/admin/meetings/${data.id}`);
  } catch (e: any) {
    if (e.response?.data?.meeting_id) router.push(`/admin/meetings/${e.response.data.meeting_id}`);
  }
}
</script>

<template>
  <div class="page" v-loading="loading">
    <div style="display:flex;justify-content:space-between;align-items:center;padding:24px 24px 0">
      <h3 style="margin:0">全员周报</h3>
      <div style="display:flex;gap:8px">
        <el-select v-model="statusFilter" placeholder="筛选" clearable size="small" @change="loadReports" style="width:100px">
          <el-option label="已提交" value="submitted" /><el-option label="补交" value="resubmitted" />
        </el-select>
        <el-button type="primary" size="small" @click="createMeeting">进入组会</el-button>
      </div>
    </div>

    <el-empty v-if="!loading && !reports.length" description="暂无周报" />

    <el-table v-else :data="reports" size="small" highlight-current-row
      @row-click="(r: any) => selectedId = r.id" style="cursor:pointer;margin-top:16px">
      <el-table-column prop="owner_name" label="成员" width="100" />
      <el-table-column prop="period_label" label="周期" width="100" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }"><el-tag :type="statusTag[row.status]" size="small">{{ statusText[row.status] || row.status }}</el-tag></template>
      </el-table-column>
      <el-table-column label="更新时间" width="160">
        <template #default="{ row }">{{ row.updated_at?.slice(0,16)?.replace('T',' ') }}</template>
      </el-table-column>
    </el-table>

    <ReportDetail v-if="selectedId" :report-id="selectedId" admin-view />
  </div>
</template>
