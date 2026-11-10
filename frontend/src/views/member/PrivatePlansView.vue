<script setup lang="ts">
import { nextTick, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { Lock, Plus } from "@element-plus/icons-vue";
import api from "@/utils/api";

interface Plan {
  id: string;
  title: string;
  description: string;
  status: string;
  due_date: string | null;
}

const plans = ref<Plan[]>([]);
const loading = ref(true);
const error = ref("");
const showCreate = ref(false);
const creating = ref(false);
const pending = ref(new Set<string>());
const titleInput = ref<HTMLInputElement>();
const newPlan = ref({ title:"", description:"" });

async function loadPlans() {
  loading.value = true;
  error.value = "";
  try {
    plans.value = (await api.get<Plan[]>("/me/private-plans/")).data;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "计划读取失败";
  } finally {
    loading.value = false;
  }
}

async function startPlan() {
  showCreate.value = true;
  await nextTick();
  titleInput.value?.focus();
}

async function createPlan() {
  const title = newPlan.value.title.trim();
  if (!title || creating.value) return;
  creating.value = true;
  try {
    await api.post("/me/private-plans/", { ...newPlan.value, title });
    newPlan.value = { title:"", description:"" };
    showCreate.value = false;
    await loadPlans();
    ElMessage.success("计划已创建");
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : "创建失败");
  } finally {
    creating.value = false;
  }
}

async function togglePlan(plan: Plan, event: Event) {
  if (pending.value.has(plan.id)) return;
  const checkbox = event.currentTarget as HTMLInputElement;
  pending.value.add(plan.id);
  try {
    const status = plan.status === "active" ? "completed" : "active";
    await api.patch("/me/private-plans/" + plan.id, { status });
    plan.status = status;
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : "计划状态更新失败");
  } finally {
    checkbox.checked = plan.status === "completed";
    pending.value.delete(plan.id);
  }
}

async function deletePlan(plan: Plan) {
  if (pending.value.has(plan.id)) return;
  pending.value.add(plan.id);
  try {
    await api.delete("/me/private-plans/" + plan.id);
    await loadPlans();
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : "计划删除失败");
  } finally {
    pending.value.delete(plan.id);
  }
}

onMounted(loadPlans);
</script>

<template>
  <div class="plans" v-loading="loading" :aria-busy="loading">
    <header class="page-heading">
      <div><h1 class="page-title">个人计划</h1><p class="privacy"><el-icon aria-hidden="true"><Lock /></el-icon>仅自己可见</p></div>
      <el-button v-if="!showCreate" type="primary" @click="startPlan"><el-icon><Plus /></el-icon>新建计划</el-button>
    </header>
    <form v-if="showCreate" class="panel plan-form" @submit.prevent="createPlan">
      <label for="plan-title">计划标题</label>
      <input id="plan-title" ref="titleInput" v-model="newPlan.title" required maxlength="500" autocomplete="off" />
      <label for="plan-description">备注 <small>选填</small></label>
      <textarea id="plan-description" v-model="newPlan.description" rows="2"></textarea>
      <div class="form-actions">
        <el-button :disabled="creating" @click="showCreate = false">取消</el-button>
        <el-button type="primary" native-type="submit" :disabled="!newPlan.title.trim()" :loading="creating">创建计划</el-button>
      </div>
    </form>
    <el-alert v-if="error" type="error" :closable="false">
      <template #title>{{ error }} <button class="link-button" @click="loadPlans">重试</button></template>
    </el-alert>
    <section v-else class="panel plan-list" aria-label="计划列表" v-auto-animate>
      <article v-for="plan in plans" :key="plan.id" class="plan-row" :class="{ done: plan.status === 'completed' }">
        <input type="checkbox" class="plan-check" :checked="plan.status === 'completed'" :aria-label="plan.title"
          :disabled="pending.has(plan.id)" @change="togglePlan(plan, $event)" />
        <div class="plan-body"><strong>{{ plan.title }}</strong>
          <p v-if="plan.description">{{ plan.description }}</p>
          <small v-if="plan.due_date">截止 {{ plan.due_date }}</small>
          <small v-if="plan.status === 'cancelled'">已取消</small>
        </div>
        <button class="delete-action" :disabled="pending.has(plan.id)" :aria-label="'删除计划 '+plan.title" @click="deletePlan(plan)">删除</button>
      </article>
      <p v-if="!loading && !plans.length" class="empty-copy">还没有个人计划。</p>
    </section>
  </div>
</template>

<style scoped>
.plans { min-height:150px; }
.privacy { display:flex; align-items:center; gap:5px; font-size:12px; color:var(--muted); margin-top:6px; }
.plan-form { display:grid; gap:7px; margin-bottom:16px; }
.plan-form label { font-size:13px; font-weight:600; }
.plan-form small { font-weight:400; color:var(--muted); }
.plan-form textarea, .plan-form input { width:100%; border:1px solid var(--line); border-radius:6px; padding:8px 10px; color:var(--ink); background:var(--glass-field); }
.plan-form textarea { resize:vertical; }
.plan-form input:focus, .plan-form textarea:focus { outline:2px solid var(--teal); outline-offset:1px; }
.form-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:3px; }
.plan-list { padding:3px clamp(14px,2vw,24px); }
.plan-row { display:flex; align-items:flex-start; gap:10px; padding:13px 0; }
.plan-row + .plan-row { border-top:1px solid var(--line); }
.plan-check { width:17px; height:17px; margin:4px 1px; flex:none; accent-color:var(--teal); cursor:pointer; }
.plan-check:focus-visible { outline:2px solid var(--teal); outline-offset:2px; }
.plan-body { flex:1; min-width:0; }
.plan-body strong { overflow-wrap:anywhere; font-size:14px; line-height:24px; }
.plan-body p, .plan-body small { display:block; margin-top:3px; color:var(--muted); font-size:13px; line-height:1.6; overflow-wrap:anywhere; white-space:pre-line; }
.done strong { text-decoration:line-through; color:var(--muted); font-weight:500; }
.delete-action { padding:3px 4px; border:0; background:none; font-size:12px; color:var(--muted); }
.delete-action:hover { color:#994b43; text-decoration:underline; }
</style>
