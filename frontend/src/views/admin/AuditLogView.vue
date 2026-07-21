<script setup lang="ts">
import { ref, onMounted } from "vue";
import api from "@/utils/api";

interface AuditEvent {
  event_id: string;
  event_type: string;
  created_at: string;
  actor_name: string;
  actor_ip: string;
  target_type: string;
  target_id: string;
  result: string;
  summary: string;
  risk_level: string;
}

const events = ref<AuditEvent[]>([]);
const loading = ref(true);
const filter = ref({ days: 7, event_type: "", actor: "" });

const eventTypeLabels: Record<string, string> = {
  LOGIN_SUCCESS: "登录成功",
  LOGIN_FAILURE: "登录失败",
  USER_CREATED: "创建用户",
  USER_DISABLED: "禁用用户",
  USER_ENABLED: "恢复用户",
  ROLE_CHANGED: "角色变更",
  PASSWORD_RESET: "密码重置",
  REPORT_SUBMITTED: "周报提交",
  REPORT_RESUBMITTED: "周报补交",
  REPORT_VIEWED_BY_ADMIN: "管理员查看周报",
  ATTACHMENT_UPLOADED: "附件上传",
  ATTACHMENT_DOWNLOADED: "附件下载",
  ATTACHMENT_REJECTED: "附件拒绝",
  PREVIEW_RETRIED: "预览重试",
  AI_REGENERATED: "AI 重新生成",
  AI_ITEM_EDITED: "AI 条目人工修改",
  MEETING_STARTED: "组会开始",
  REPORT_MARKED_DISCUSSED: "标记已讨论",
  EXPORT_CREATED: "导出创建",
  EXPORT_DOWNLOADED: "导出下载",
  SYSTEM_SETTING_CHANGED: "系统配置变更",
  EMERGENCY_ACCOUNT_ENABLED: "应急账号启用",
};

async function loadEvents() {
  loading.value = true;
  try {
    const params = new URLSearchParams();
    if (filter.value.days) params.set("days", String(filter.value.days));
    if (filter.value.event_type) params.set("event_type", filter.value.event_type);
    if (filter.value.actor) params.set("actor", filter.value.actor);
    const { data } = await api.get(`/admin/audit?${params.toString()}`);
    events.value = data.events || [];
  } finally {
    loading.value = false;
  }
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString("zh-CN");
}

onMounted(loadEvents);
</script>

<template>
  <div class="audit" v-loading="loading">
    <div class="audit-header">
      <h2>审计日志</h2>
      <div class="filters">
        <el-select v-model="filter.days" @change="loadEvents" style="width:120px">
          <el-option :value="1" label="最近1天" />
          <el-option :value="7" label="最近7天" />
          <el-option :value="30" label="最近30天" />
        </el-select>
        <el-select v-model="filter.event_type" @change="loadEvents" clearable placeholder="全部类型" style="width:160px">
          <el-option v-for="(label, key) in eventTypeLabels" :key="key" :value="key" :label="label" />
        </el-select>
        <el-input v-model="filter.actor" @change="loadEvents" clearable placeholder="操作人" style="width:140px" />
      </div>
    </div>

    <el-table :data="events" size="small" max-height="calc(100vh - 200px)">
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="类型" width="130">
        <template #default="{ row }">{{ eventTypeLabels[row.event_type] || row.event_type }}</template>
      </el-table-column>
      <el-table-column prop="actor_name" label="操作人" width="100" />
      <el-table-column prop="actor_ip" label="IP" width="130" />
      <el-table-column label="目标" min-width="160">
        <template #default="{ row }">{{ row.target_type ? `${row.target_type}#${row.target_id}` : '-' }}</template>
      </el-table-column>
      <el-table-column label="结果" width="70">
        <template #default="{ row }">
          <el-tag :type="row.result==='success'?'success':row.result==='denied'?'danger':'warning'" size="small">
            {{ row.result === 'success' ? '成功' : row.result === 'denied' ? '拒绝' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="风险" width="60">
        <template #default="{ row }">
          <el-tag :type="row.risk_level==='high'?'danger':row.risk_level==='medium'?'warning':'info'" size="small">
            {{ row.risk_level === 'high' ? '高' : row.risk_level === 'medium' ? '中' : '低' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="summary" label="摘要" min-width="200" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<style scoped>
.audit { padding: 24px; }
.audit-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
.audit-header h2 { font-size: 18px; margin: 0; }
.filters { display: flex; gap: 8px; }
</style>
