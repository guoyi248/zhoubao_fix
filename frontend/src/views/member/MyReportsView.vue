<script setup lang="ts">
import { ref, onMounted } from "vue";
import api from "@/utils/api";
import ReportDetail from "@/components/report/ReportDetail.vue";

interface ReportItem {
  id: string; period_label: string; status: string;
  updated_at: string; current_revision_id: string | null;
}
const reports = ref<ReportItem[]>([]);
const loading = ref(true);
const selectedId = ref("");
const statusTag: Record<string, string> = { draft: "info", submitted: "success", resubmitted: "warning", archived: "" };

onMounted(async () => {
  try {
    const { data } = await api.get("/me/reports");
    reports.value = Array.isArray(data) ? data : [];
  } finally { loading.value = false; }
});
</script>

<template>
  <div class="my-reports" v-loading="loading">
    <h3 style="margin:0 0 16px;padding:24px 24px 0">我的历史周报</h3>
    <el-empty v-if="!loading && !reports.length" description="暂无历史周报" />
    <el-table v-else :data="reports" size="small" highlight-current-row
      @row-click="(r: any) => selectedId = r.id" style="cursor:pointer">
      <el-table-column prop="period_label" label="周期" width="120" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }"><el-tag :type="statusTag[row.status]" size="small">{{ row.status }}</el-tag></template>
      </el-table-column>
      <el-table-column label="更新时间" width="180">
        <template #default="{ row }">{{ row.updated_at?.slice(0,16)?.replace('T',' ') }}</template>
      </el-table-column>
      <el-table-column label="修订">
        <template #default="{ row }">{{ row.current_revision_id ? '#'+row.current_revision_id.slice(0,8) : '-' }}</template>
      </el-table-column>
    </el-table>
    <ReportDetail v-if="selectedId" :report-id="selectedId" />
  </div>
</template>
