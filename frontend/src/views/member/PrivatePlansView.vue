<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import api from "@/utils/api";

interface Plan {
  id: string;
  title: string;
  description: string;
  status: string;
  due_date: string | null;
  created_at: string;
}

const plans = ref<Plan[]>([]);
const loading = ref(true);
const showCreate = ref(false);
const newPlan = ref({ title: "", description: "", due_date: "" });

onMounted(loadPlans);

async function loadPlans() {
  loading.value = true;
  try {
    const { data } = await api.get("/me/private-plans/");
    plans.value = data;
  } finally {
    loading.value = false;
  }
}

async function createPlan() {
  if (!newPlan.value.title.trim()) return;
  try {
    await api.post("/me/private-plans/", newPlan.value);
    newPlan.value = { title: "", description: "", due_date: "" };
    showCreate.value = false;
    await loadPlans();
    ElMessage.success("已创建");
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function togglePlan(plan: Plan) {
  const newStatus = plan.status === "active" ? "completed" : "active";
  try {
    await api.patch(`/me/private-plans/${plan.id}`, { status: newStatus });
    plan.status = newStatus;
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function deletePlan(plan: Plan) {
  try {
    await api.delete(`/me/private-plans/${plan.id}`);
    await loadPlans();
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}
</script>

<template>
  <div class="plans" v-loading="loading">
    <div class="plans-header">
      <h2>🔒 个人计划</h2>
      <el-tag size="small" type="warning">仅本人可见</el-tag>
      <el-button type="primary" @click="showCreate = !showCreate" size="small" style="margin-left: auto">
        {{ showCreate ? '取消' : '新建' }}
      </el-button>
    </div>

    <el-card v-if="showCreate" style="margin-bottom: 16px">
      <el-input v-model="newPlan.title" placeholder="计划标题" style="margin-bottom: 8px" />
      <el-input v-model="newPlan.description" placeholder="描述（可选）" type="textarea" :rows="2" style="margin-bottom: 8px" />
      <el-button type="primary" @click="createPlan" :disabled="!newPlan.title.trim()">创建</el-button>
    </el-card>

    <el-empty v-if="!loading && plans.length === 0" description="暂无个人计划" />

    <el-card v-for="plan in plans" :key="plan.id" :class="['plan-item', plan.status]">
      <div class="plan-row">
        <el-checkbox
          :model-value="plan.status === 'completed'"
          @change="togglePlan(plan)"
        />
        <span :class="['plan-title', { done: plan.status === 'completed' }]">{{ plan.title }}</span>
        <span class="plan-date" v-if="plan.due_date">截止 {{ plan.due_date }}</span>
        <el-button text type="danger" size="small" @click="deletePlan(plan)">删除</el-button>
      </div>
      <p v-if="plan.description" class="plan-desc">{{ plan.description }}</p>
    </el-card>
  </div>
</template>

<style scoped>
.plans { padding: 24px; max-width: 640px; margin: 0 auto; }
.plans-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.plans-header h2 { font-size: 18px; margin: 0; }
.plan-item { margin-bottom: 8px; }
.plan-item.completed { opacity: 0.6; }
.plan-row { display: flex; align-items: center; gap: 8px; }
.plan-title { flex: 1; font-size: 14px; }
.plan-title.done { text-decoration: line-through; }
.plan-date { font-size: 12px; color: var(--el-text-color-placeholder); }
.plan-desc { margin: 4px 0 0 28px; font-size: 13px; color: var(--el-text-color-secondary); }
</style>
