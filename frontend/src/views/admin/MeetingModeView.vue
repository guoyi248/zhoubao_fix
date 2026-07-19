<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import api from "@/utils/api";

const route = useRoute();
const meeting = ref<any>(null);
const snapshots = ref<any[]>([]);
const currentIndex = ref(0);
const currentReport = ref<any>(null);
const previewUrl = ref("");
const loading = ref(true);
const states = ref<Record<string, any>>({});

const current = computed(() => snapshots.value[currentIndex.value]);
const total = computed(() => snapshots.value.length);

onMounted(async () => {
  try {
    const { data } = await api.get(`/admin/meetings/${route.params.id}`);
    meeting.value = data;
    snapshots.value = data.snapshots || [];
    states.value = data.report_states || {};
    if (snapshots.value.length) loadReport(0);
  } finally { loading.value = false; }
});

async function loadReport(idx: number) {
  currentIndex.value = idx;
  previewUrl.value = "";
  const snap = snapshots.value[idx];
  if (!snap) return;
  currentReport.value = {
    member_name: snap.member_name,
    member_department: snap.member_department,
    structured_content: snap.structured_content,
  };
  if (snap.confirmed_pdf_attachment_id) {
    previewUrl.value = `/api/v1/attachments/${snap.confirmed_pdf_attachment_id}/preview-content`;
  }
}

function prev() { if (currentIndex.value > 0) loadReport(currentIndex.value - 1); }
function next() { if (currentIndex.value < total.value - 1) loadReport(currentIndex.value + 1); }

async function toggleDiscussed() {
  const snap = current.value;
  if (!snap) return;
  const st = states.value[snap.member_id] || {};
  try {
    await api.patch(`/admin/meetings/${meeting.value.id}/reports/${snap.id}`, { discussed: !st.discussed });
    states.value[snap.member_id] = { ...st, discussed: !st.discussed };
  } catch {}
}
</script>

<template>
  <div class="meeting" v-loading="loading">
    <!-- Top bar -->
    <div class="meeting-bar">
      <span><strong>组会模式</strong> · {{ total }} 人</span>
      <span>{{ currentIndex + 1 }} / {{ total }}</span>
      <div>
        <el-button size="small" @click="prev" :disabled="currentIndex===0">上一位</el-button>
        <el-button size="small" @click="next" :disabled="currentIndex>=total-1">下一位</el-button>
        <el-button size="small" @click="toggleDiscussed" :type="states[current?.member_id]?.discussed ? 'success' : 'default'">
          {{ states[current?.member_id]?.discussed ? '✓ 已讨论' : '标记已讨论' }}
        </el-button>
      </div>
    </div>

    <!-- Body -->
    <div class="meeting-body">
      <!-- Left: Member list -->
      <div class="member-list">
        <div v-for="(s, i) in snapshots" :key="s.id"
          :class="['member-item', { current: i === currentIndex, discussed: states[s.member_id]?.discussed }]"
          @click="loadReport(i)">
          <span class="dot">{{ states[s.member_id]?.discussed ? '✓' : '○' }}</span>
          {{ s.member_name }}
          <span class="dept">{{ s.member_department }}</span>
        </div>
      </div>

      <!-- Middle: Report content + PDF -->
      <div class="report-area">
        <template v-if="current">
          <h3>{{ current.member_name }} · {{ current.member_department }}</h3>

          <!-- 结构化内容 -->
          <div v-if="currentReport?.structured_content" class="content-box">
            <div v-if="currentReport.structured_content.completed?.length">
              <strong>本周完成：</strong>
              <ul><li v-for="c in currentReport.structured_content.completed" :key="c">{{ c }}</li></ul>
            </div>
            <div v-if="currentReport.structured_content.risks?.length">
              <strong>风险：</strong>{{ currentReport.structured_content.risks.join('；') }}
            </div>
            <div v-if="currentReport.structured_content.next_week?.length">
              <strong>下周：</strong>
              <ul><li v-for="n in currentReport.structured_content.next_week" :key="n">{{ n }}</li></ul>
            </div>
          </div>

          <!-- PDF preview -->
          <div v-if="previewUrl" class="pdf-box">
            <iframe :src="previewUrl" width="100%" height="500px" frameborder="0" />
            <p><a :href="previewUrl" target="_blank">新窗口打开 PDF</a></p>
          </div>
          <el-empty v-else description="暂无预览 PDF" :image-size="60" />
        </template>
        <el-empty v-else description="请选择成员" />
      </div>

      <!-- Right: Actions -->
      <div class="action-panel">
        <h4>行动项</h4>
        <div v-for="a in (meeting?.action_items || [])" :key="a.id" class="action-item">
          <span :class="{ done: a.status === 'done' }">{{ a.title }}</span>
          <span class="action-meta">{{ a.owner_name || '待分配' }}</span>
        </div>
        <el-empty v-if="!meeting?.action_items?.length" description="暂无" :image-size="40" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.meeting { display:flex; flex-direction:column; height:100vh; background:#fff; }
.meeting-bar { display:flex; align-items:center; justify-content:space-between; padding:8px 16px; border-bottom:1px solid #eee; flex-shrink:0; }
.meeting-body { display:flex; flex:1; overflow:hidden; }
.member-list { width:180px; border-right:1px solid #eee; overflow-y:auto; flex-shrink:0; }
.member-item { padding:10px 12px; cursor:pointer; border-bottom:1px solid #f5f5f5; font-size:14px; }
.member-item:hover { background:#f0f5ff; }
.member-item.current { background:#e6f0ff; font-weight:600; }
.member-item.discussed { opacity:0.6; }
.dot { margin-right:4px; }
.dept { display:block; font-size:11px; color:#999; }
.report-area { flex:1; padding:16px; overflow-y:auto; }
.report-area h3 { margin:0 0 12px; }
.pdf-box { border:1px solid #e5e5e5; border-radius:6px; overflow:hidden; }
.pdf-box p { padding:6px 12px; font-size:12px; margin:0; }
.action-panel { width:220px; border-left:1px solid #eee; padding:12px; overflow-y:auto; flex-shrink:0; }
.action-panel h4 { margin:0 0 8px; font-size:13px; }
.action-item { padding:6px 8px; margin-bottom:4px; background:#f8f8f8; border-radius:4px; font-size:13px; }
.action-item.done { text-decoration:line-through; opacity:0.5; }
.action-meta { display:block; font-size:11px; color:#999; }
</style>
