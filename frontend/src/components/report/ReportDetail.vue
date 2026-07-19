<script setup lang="ts">
/** 周报详情 + 附件 PDF 预览 — 成员和管理员共用 */
import { ref, onMounted } from "vue";
import api from "@/utils/api";

const props = defineProps<{
  reportId: string;
  adminView?: boolean;
}>();

interface ReportInfo {
  id: string;
  owner_name: string;
  owner_department: string;
  status: string;
  draft_content_json: any;
  period: { iso_year: number; iso_week: number };
  revisions: Array<{
    id: string;
    revision_no: number;
    submitted_at: string;
    confirmed_pdf_attachment_id: string | null;
  }>;
}

const report = ref<ReportInfo | null>(null);
const previewUrl = ref("");
const loading = ref(true);

const prefix = props.adminView ? "/admin/reports" : "/me/reports";

onMounted(async () => {
  try {
    const { data } = await api.get(`${prefix}/${props.reportId}`);
    report.value = data;

    // Load attachments for this report
    if (data.revisions?.length) {
      const rev = data.revisions[0];
      if (rev.confirmed_pdf_attachment_id) {
        previewUrl.value = `/api/v1/attachments/${rev.confirmed_pdf_attachment_id}/preview-content`;
      }
    }
  } catch (e: any) {
    console.error("Load report failed", e);
  } finally {
    loading.value = false;
  }
});

function contentList(key: string): string[] {
  if (!report.value?.draft_content_json) return [];
  return report.value.draft_content_json[key] || [];
}
</script>

<template>
  <div class="report-detail" v-loading="loading">
    <template v-if="report">
      <div class="rd-header">
        <h3>{{ report.owner_name }} · {{ report.owner_department }}</h3>
        <el-tag :type="report.status === 'submitted' ? 'success' : 'info'">
          {{ report.status === 'submitted' ? '已提交' : report.status === 'draft' ? '草稿' : report.status }}
        </el-tag>
      </div>

      <p class="rd-period">
        第 {{ report.period.iso_week }} 周 ({{ report.period.iso_year }})
      </p>

      <!-- 结构化内容 -->
      <el-descriptions :column="1" border size="small" class="rd-content">
        <el-descriptions-item label="本周完成" v-if="contentList('completed').length">
          <ul><li v-for="item in contentList('completed')" :key="item">{{ item }}</li></ul>
        </el-descriptions-item>
        <el-descriptions-item label="关键结果" v-if="contentList('results').length">
          <ul><li v-for="item in contentList('results')" :key="item">{{ item }}</li></ul>
        </el-descriptions-item>
        <el-descriptions-item label="问题与风险" v-if="contentList('risks').length">
          {{ contentList('risks').join("；") }}
        </el-descriptions-item>
        <el-descriptions-item label="需要协助" v-if="contentList('blockers').length">
          {{ contentList('blockers').join("；") }}
        </el-descriptions-item>
        <el-descriptions-item label="下周计划" v-if="contentList('next_week').length">
          <ul><li v-for="item in contentList('next_week')" :key="item">{{ item }}</li></ul>
        </el-descriptions-item>
      </el-descriptions>

      <!-- PDF 预览 -->
      <div v-if="previewUrl" class="rd-preview">
        <h4>📄 周报 PDF 预览</h4>
        <iframe :src="previewUrl" width="100%" height="600px" frameborder="0" />
        <p class="rd-hint"><a :href="previewUrl" target="_blank">新窗口打开 PDF</a></p>
      </div>
      <div v-else-if="!hasContent" class="rd-empty">
        <p>此周报没有上传文件。上传 Word/PDF 并确认预览后才能在此处查看。</p>
      </div>
      <el-empty v-else description="PDF 处理中或转换失败" :image-size="60" />

      <!-- 修订记录 -->
      <div v-if="report.revisions?.length" class="rd-revisions">
        <h4>修订记录</h4>
        <el-timeline>
          <el-timeline-item
            v-for="rev in report.revisions"
            :key="rev.id"
            :timestamp="rev.submitted_at?.slice(0, 16)?.replace('T', ' ')"
          >
            Revision #{{ rev.revision_no }}
            <span v-if="rev.confirmed_pdf_attachment_id"> · 📄 含PDF</span>
          </el-timeline-item>
        </el-timeline>
      </div>
    </template>
  </div>
</template>

<style scoped>
.report-detail { padding: 16px; }

.rd-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.rd-header h3 { margin: 0; font-size: 18px; }

.rd-period {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin: 0 0 16px;
}

.rd-content { margin-bottom: 16px; }

.rd-content ul {
  margin: 0;
  padding-left: 16px;
}

.rd-preview {
  margin: 16px 0;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  overflow: hidden;
}

.rd-preview h4 {
  margin: 0;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  font-size: 14px;
}

.rd-preview iframe {
  display: block;
}

.rd-hint {
  margin: 8px 12px;
  font-size: 12px;
}

.rd-revisions {
  margin-top: 16px;
}

.rd-revisions h4 {
  font-size: 14px;
  margin: 0 0 8px;
}
</style>
