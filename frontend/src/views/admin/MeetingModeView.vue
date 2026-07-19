<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import api from "@/utils/api";

const route = useRoute();
const router = useRouter();
const meeting = ref<any>(null);
const snapshots = ref<any[]>([]);
const currentIndex = ref(0);
const previewUrl = ref("");
const loading = ref(true);
const states = ref<Record<string, any>>({});
const isFullscreen = ref(false);

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
  document.addEventListener("keydown", onKey);
});
onUnmounted(() => document.removeEventListener("keydown", onKey));

function onKey(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
  if (e.key === "ArrowLeft") prev();
  if (e.key === "ArrowRight") next();
  if (e.key === "f" || e.key === "F") toggleFullscreen();
  if (e.key === "d" || e.key === "D") toggleDiscussed();
}

function loadReport(idx: number) {
  currentIndex.value = idx;
  previewUrl.value = "";
  const snap = snapshots.value[idx];
  if (!snap) return;
  if (snap.confirmed_pdf_attachment_id) {
    previewUrl.value = `/api/v1/attachments/${snap.confirmed_pdf_attachment_id}/preview-content`;
  }
}

function prev() { if (currentIndex.value > 0) loadReport(currentIndex.value - 1); }
function next() { if (currentIndex.value < total.value - 1) loadReport(currentIndex.value + 1); }
function goTo(val: any) { loadReport(Number(val)); }

async function toggleDiscussed() {
  const snap = current.value;
  if (!snap) return;
  const st = states.value[snap.member_id] || {};
  try {
    await api.patch(`/admin/meetings/${meeting.value.id}/reports/${snap.id}`, { discussed: !st.discussed });
    states.value[snap.member_id] = { ...st, discussed: !st.discussed };
  } catch {}
}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen();
    isFullscreen.value = true;
  } else {
    document.exitFullscreen();
    isFullscreen.value = false;
  }
}
</script>

<template>
  <div class="meeting" v-loading="loading">
    <!-- Top bar -->
    <div class="meeting-bar">
      <div class="bar-left">
        <strong>组会模式</strong>
        <el-select v-model="currentIndex" @change="goTo" size="small" style="width:180px;margin-left:12px" placeholder="选择成员">
          <el-option v-for="(s, i) in snapshots" :key="s.id" :label="`${states[s.member_id]?.discussed ? '✓ ' : ''}${s.member_name} · ${s.member_department}`" :value="i" />
        </el-select>
        <span style="margin-left:8px;font-size:13px;color:#999">{{ currentIndex + 1 }} / {{ total }}</span>
      </div>
      <div class="bar-center">
        <el-button-group size="small">
          <el-button @click="prev" :disabled="currentIndex===0">← 上一位</el-button>
          <el-button @click="next" :disabled="currentIndex>=total-1">下一位 →</el-button>
        </el-button-group>
        <el-button size="small" @click="toggleDiscussed" :type="states[current?.member_id]?.discussed ? 'success' : 'default'" style="margin-left:8px">
          {{ states[current?.member_id]?.discussed ? '✓ 已讨论' : '标记已讨论' }}
        </el-button>
      </div>
      <div class="bar-right">
        <el-button size="small" @click="toggleFullscreen">{{ isFullscreen ? '退出全屏' : '全屏' }}</el-button>
        <el-button size="small" type="danger" @click="router.push('/admin/reports')">退出组会</el-button>
      </div>
    </div>

    <!-- Body: PDF full page -->
    <div class="meeting-body">
      <template v-if="current && previewUrl">
        <!-- Member info overlay -->
        <div class="pdf-header">
          <span>{{ current.member_name }} · {{ current.member_department }}</span>
          <span>Revision #{{ current.report_revision_id?.slice(0,8) || '?' }}</span>
        </div>
        <!-- Full PDF -->
        <iframe :src="previewUrl" class="pdf-full" frameborder="0" />
      </template>
      <div v-else-if="current" class="no-pdf">
        <el-empty description="该成员未上传 PDF 周报" :image-size="80" />
        <p style="text-align:center;color:#999;font-size:13px">{{ current.member_name }} · {{ current.member_department }}</p>
      </div>
      <el-empty v-else description="请选择成员查看周报" :image-size="100" />
    </div>

    <!-- Bottom bar: quick nav -->
    <div class="meeting-footer">
      <span>← → 切换</span>
      <span>D 标记讨论</span>
      <span>F 全屏</span>
    </div>
  </div>
</template>

<style scoped>
.meeting {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #1a1a1a;
  color: #fff;
}

/* Top bar */
.meeting-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #2a2a2a;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
  z-index: 10;
}
.bar-left, .bar-center, .bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bar-left strong { font-size: 15px; }

/* Body: PDF fills everything */
.meeting-body {
  flex: 1;
  overflow: hidden;
  position: relative;
  background: #333;
}

.pdf-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  justify-content: space-between;
  padding: 8px 16px;
  background: rgba(0,0,0,0.7);
  font-size: 14px;
  z-index: 5;
}

.pdf-full {
  width: 100%;
  height: 100%;
  border: none;
}

.no-pdf {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  background: #1a1a1a;
}

/* Bottom bar */
.meeting-footer {
  display: flex;
  justify-content: center;
  gap: 24px;
  padding: 4px 16px;
  background: #2a2a2a;
  font-size: 11px;
  color: #666;
  flex-shrink: 0;
}
</style>
