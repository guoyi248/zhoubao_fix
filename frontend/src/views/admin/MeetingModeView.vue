<script setup lang="ts">
/**
 * 组会模式 — 管理员全屏逐人查看周报。
 *
 * 键盘快捷键：
 *   ← →  切换成员
 *   F     全屏切换
 *   A     新建行动项
 *   D     标记已讨论/取消
 */
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "@/utils/api";

interface Snapshot {
  id: string;
  member_id: string;
  member_name: string;
  member_department: string;
  report_revision_id: string;
  display_order: number;
  report?: any;
}

interface ActionItem {
  id: string;
  title: string;
  owner_name: string;
  due_date: string | null;
  status: string;
}

const route = useRoute();

// ── 状态 ────────────────────────────────────────────────
const meeting = ref<any>(null);
const snapshots = ref<Snapshot[]>([]);
const reportStates = ref<Record<string, any>>({});
const actionItems = ref<ActionItem[]>([]);
const currentIndex = ref(0);
const isFullscreen = ref(false);
const loading = ref(true);
const showRisksOnly = ref(false);
const showUndiscussedOnly = ref(false);
const newActionItemTitle = ref("");

// ── 计算属性 ────────────────────────────────────────────

const filteredSnapshots = computed(() => {
  return snapshots.value.filter((s) => {
    if (showRisksOnly.value) {
      // 简单检查：AI 分析中是否有风险
      const analysis = s.report?.analysis;
      if (!analysis) return false;
      const hasRisks = analysis.items?.some(
        (item: any) => item.item_type === "risk" || item.item_type === "blocker",
      );
      if (!hasRisks) return false;
    }
    if (showUndiscussedOnly.value) {
      const state = reportStates.value[s.report?.id || ""];
      if (state?.discussed) return false;
    }
    return true;
  });
});

const currentSnapshot = computed(() => filteredSnapshots.value[currentIndex.value]);

const totalMembers = computed(() => snapshots.value.length);
const discussedCount = computed(() =>
  Object.values(reportStates.value).filter((s: any) => s.discussed).length,
);

// ── 方法 ────────────────────────────────────────────────

async function loadMeeting() {
  const meetingId = route.params.id as string;
  loading.value = true;
  try {
    const { data } = await api.get(`/admin/meetings/${meetingId}`);
    meeting.value = data;
    snapshots.value = data.snapshots || [];
    reportStates.value = data.report_states || {};
    actionItems.value = data.action_items || [];

    // 加载每位成员的周报详情
    for (const snap of snapshots.value) {
      const { data: report } = await api.get(`/admin/reports/${snap.report_revision_id}`).catch(() => ({ data: null }));
      snap.report = report;
    }
  } catch (e: any) {
    ElMessage.error(e.message || "加载组会失败");
  } finally {
    loading.value = false;
  }
}

function goTo(index: number) {
  if (index >= 0 && index < filteredSnapshots.value.length) {
    currentIndex.value = index;
  }
}

function prev() {
  goTo(currentIndex.value - 1);
}

function next() {
  goTo(currentIndex.value + 1);
}

async function toggleDiscussed() {
  const snap = currentSnapshot.value;
  if (!snap) return;
  const state = reportStates.value[snap.report?.id || ""];
  const currently = state?.discussed ?? false;

  try {
    await api.patch(`/admin/meetings/${meeting.value.id}/reports/${snap.id}`, {
      discussed: !currently,
    });
    reportStates.value[snap.report?.id || ""] = { ...state, discussed: !currently };
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function addActionItem() {
  if (!newActionItemTitle.value.trim()) return;
  try {
    const { data } = await api.post(`/admin/meetings/${meeting.value.id}/action-items`, {
      title: newActionItemTitle.value,
      source_report_id: currentSnapshot.value?.report?.id,
    });
    actionItems.value.push(data);
    newActionItemTitle.value = "";
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function resolveActionItem(item: ActionItem) {
  try {
    await api.patch(`/admin/action-items/${item.id}`, { status: "done" });
    item.status = "done";
  } catch (e: any) {
    ElMessage.error(e.message);
  }
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

async function startMeeting() {
  try {
    await api.post(`/admin/meetings/${meeting.value.id}/start`);
    meeting.value.status = "in_progress";
    ElMessage.success("组会已开始");
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function finishMeeting() {
  try {
    await ElMessageBox.confirm("确认结束本次组会？将无法再添加行动项。", "结束组会");
    await api.post(`/admin/meetings/${meeting.value.id}/finish`);
    meeting.value.status = "finished";
    ElMessage.success("组会已结束");
  } catch {
    // 取消
  }
}

// ── 键盘事件 ────────────────────────────────────────────

function onKeydown(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

  switch (e.key) {
    case "ArrowLeft":
      prev();
      break;
    case "ArrowRight":
      next();
      break;
    case "f":
    case "F":
      toggleFullscreen();
      break;
    case "a":
    case "A":
      e.preventDefault();
      document.getElementById("action-input")?.focus();
      break;
    case "d":
    case "D":
      toggleDiscussed();
      break;
  }
}

onMounted(() => {
  loadMeeting();
  window.addEventListener("keydown", onKeydown);
});

onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <div class="meeting-mode" :class="{ fullscreen: isFullscreen }">
    <!-- 顶部工具栏 -->
    <div class="meeting-toolbar">
      <div class="toolbar-left">
        <strong>第 {{ meeting?.reporting_period_id }} 周组会</strong>
        <span class="meeting-status">
          已讨论 {{ discussedCount }} / {{ totalMembers }}
        </span>
      </div>
      <div class="toolbar-center">
        <el-button-group>
          <el-button :icon="'ArrowLeft'" @click="prev" :disabled="currentIndex === 0">上一位</el-button>
          <el-button :icon="'ArrowRight'" @click="next" :disabled="currentIndex >= filteredSnapshots.length - 1">下一位</el-button>
        </el-button-group>
        <span class="member-progress">{{ currentIndex + 1 }} / {{ filteredSnapshots.length }}</span>
      </div>
      <div class="toolbar-right">
        <el-checkbox v-model="showRisksOnly" size="small">只看风险</el-checkbox>
        <el-checkbox v-model="showUndiscussedOnly" size="small">只看未讨论</el-checkbox>
        <el-button v-if="meeting?.status === 'planned'" type="success" @click="startMeeting" size="small">开始组会</el-button>
        <el-button v-if="meeting?.status === 'in_progress'" type="warning" @click="finishMeeting" size="small">结束组会</el-button>
        <el-button @click="toggleFullscreen" size="small">全屏</el-button>
      </div>
    </div>

    <!-- 主体三栏 -->
    <div class="meeting-body" v-loading="loading">
      <!-- 左栏：成员列表 -->
      <div class="member-sidebar">
        <div
          v-for="(snap, idx) in filteredSnapshots"
          :key="snap.id"
          :class="['member-item', { current: idx === currentIndex, discussed: reportStates[snap.report?.id]?.discussed }]"
          @click="goTo(idx)"
        >
          <span class="member-status">
            <el-icon v-if="reportStates[snap.report?.id]?.discussed" color="#67c23a"><svg viewBox="0 0 1024 1024" width="14" height="14"><path d="M512 64a448 448 0 1 1 0 896 448 448 0 0 1 0-896z" fill="currentColor"/><path d="M325 480l115 115 259-259" fill="white" stroke="white" stroke-width="40"/></svg></el-icon>
            <el-icon v-else color="#c0c4cc"><svg viewBox="0 0 1024 1024" width="14" height="14"><path d="M512 64a448 448 0 1 1 0 896 448 448 0 0 1 0-896z" fill="currentColor"/></svg></el-icon>
          </span>
          <span class="member-name">{{ snap.member_name }}</span>
          <span class="member-dept">{{ snap.member_department }}</span>
        </div>
      </div>

      <!-- 中栏：当前成员周报 -->
      <div class="report-main">
        <template v-if="currentSnapshot">
          <div class="report-header">
            <h3>{{ currentSnapshot.member_name }} · {{ currentSnapshot.member_department }}</h3>
            <el-button
              :type="reportStates[currentSnapshot.report?.id]?.discussed ? 'success' : 'default'"
              @click="toggleDiscussed"
              size="small"
            >
              {{ reportStates[currentSnapshot.report?.id]?.discussed ? '✓ 已讨论' : '标记已讨论' }}
            </el-button>
          </div>

          <!-- 结构化周报内容 -->
          <div class="report-content" v-if="currentSnapshot.report">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="本周完成" v-if="currentSnapshot.report.draft_content_json?.completed?.length">
                <ul>
                  <li v-for="item in currentSnapshot.report.draft_content_json.completed" :key="item">{{ item }}</li>
                </ul>
              </el-descriptions-item>
              <el-descriptions-item label="风险与阻塞">
                {{ currentSnapshot.report.draft_content_json?.risks?.join("；") || "无" }}
              </el-descriptions-item>
              <el-descriptions-item label="下周计划" v-if="currentSnapshot.report.draft_content_json?.next_week?.length">
                <ul>
                  <li v-for="item in currentSnapshot.report.draft_content_json.next_week" :key="item">{{ item }}</li>
                </ul>
              </el-descriptions-item>
              <el-descriptions-item label="关键结果">
                {{ currentSnapshot.report.draft_content_json?.results?.join("；") || "—" }}
              </el-descriptions-item>
            </el-descriptions>

            <!-- 修订信息 -->
            <p class="revision-info">
              Revision #{{ currentSnapshot.report.revisions?.[0]?.revision_no || "?" }}
              提交于 {{ currentSnapshot.report.revisions?.[0]?.submitted_at?.slice(0, 10) || "—" }}
              · SHA: {{ currentSnapshot.report.revisions?.[0]?.content_sha256?.slice(0, 8) || "—" }}
            </p>
          </div>
        </template>
        <el-empty v-else description="选择一位成员开始查看" />
      </div>

      <!-- 右栏：行动项 + 备注 -->
      <div class="action-sidebar">
        <h4>会议行动项</h4>
        <div class="action-list">
          <div
            v-for="item in actionItems"
            :key="item.id"
            :class="['action-item', item.status]"
          >
            <span>{{ item.title }}</span>
            <span class="action-meta">
              {{ item.owner_name || "待分配" }}
              <span v-if="item.due_date"> · {{ item.due_date }}</span>
            </span>
            <el-button
              v-if="item.status === 'open'"
              size="small"
              type="success"
              @click="resolveActionItem(item)"
            >
              完成
            </el-button>
          </div>
        </div>

        <div class="add-action" v-if="meeting?.status === 'in_progress'">
          <el-input
            id="action-input"
            v-model="newActionItemTitle"
            placeholder="新建行动项..."
            @keyup.enter="addActionItem"
            size="small"
          >
            <template #append>
              <el-button @click="addActionItem" :disabled="!newActionItemTitle.trim()">添加</el-button>
            </template>
          </el-input>
        </div>

        <div class="meeting-notes" v-if="meeting?.notes">
          <h4>会议备注</h4>
          <p>{{ meeting.notes }}</p>
        </div>
      </div>
    </div>

    <!-- 底部快捷键提示 -->
    <div class="meeting-footer">
      <span>← → 切换成员</span>
      <span>D 标记已讨论</span>
      <span>A 新建行动项</span>
      <span>F 全屏</span>
    </div>
  </div>
</template>

<style scoped>
.meeting-mode {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--el-bg-color-page);
}

.meeting-mode.fullscreen {
  position: fixed;
  inset: 0;
  z-index: 9999;
}

/* 工具栏 */
.meeting-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
}

.toolbar-left { display: flex; align-items: center; gap: 12px; }
.toolbar-center { display: flex; align-items: center; gap: 8px; }
.toolbar-right { display: flex; align-items: center; gap: 12px; }
.meeting-status { color: var(--el-text-color-secondary); font-size: 13px; }
.member-progress { font-size: 14px; color: var(--el-text-color-regular); }

/* 三栏主体 */
.meeting-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* 左栏 */
.member-sidebar {
  width: 200px;
  border-right: 1px solid var(--el-border-color-light);
  overflow-y: auto;
  flex-shrink: 0;
}

.member-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  cursor: pointer;
  border-bottom: 1px solid var(--el-border-color-lighter);
  transition: background 0.15s;
}

.member-item:hover { background: var(--el-fill-color-light); }
.member-item.current { background: var(--el-color-primary-light-9); font-weight: 600; }
.member-item.discussed { opacity: 0.7; }
.member-name { flex: 1; font-size: 14px; }
.member-dept { font-size: 12px; color: var(--el-text-color-secondary); }

/* 中栏 */
.report-main {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}

.report-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.report-content ul {
  margin: 0;
  padding-left: 16px;
}

.revision-info {
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

/* 右栏 */
.action-sidebar {
  width: 280px;
  border-left: 1px solid var(--el-border-color-light);
  overflow-y: auto;
  padding: 16px;
  flex-shrink: 0;
}

.action-sidebar h4 {
  margin: 0 0 8px;
  font-size: 14px;
}

.action-item {
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 6px;
  background: var(--el-fill-color);
  font-size: 13px;
}

.action-item.done {
  opacity: 0.6;
  text-decoration: line-through;
}

.action-meta {
  display: block;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.add-action {
  margin-top: 12px;
}

.meeting-notes {
  margin-top: 16px;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.meeting-notes h4 { margin: 0 0 4px; font-size: 13px; }

/* 底部 */
.meeting-footer {
  display: flex;
  justify-content: center;
  gap: 24px;
  padding: 6px 16px;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-light);
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
}
</style>
