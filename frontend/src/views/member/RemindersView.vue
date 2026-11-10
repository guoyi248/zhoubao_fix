<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { Setting } from "@element-plus/icons-vue";
import { useUserStore } from "@/stores/user";
import api from "@/utils/api";
import { serviceLabel, type ServiceState } from "@/utils/weeklyServices";
import type { Period } from "@/utils/week";

interface Missing { id: number; name: string; email: string; sent_at: string | null }
interface MailState extends ServiceState {
  weekday: number; time: string; timezone: string; period: Period; email: string; submitted: boolean; sent_at: string | null;
  preview: { subject: string; body: string };
  team?: { missing: Missing[]; sent: { name: string; sent_at: string }[] };
}
const weekDays = ["周一","周二","周三","周四","周五","周六","周日"];
const service = ref<MailState>();
const store = useUserStore();
const email = ref("");
const tab = ref<"missing" | "sent">("missing");
const error = ref("");
const loading = ref(false);
const saving = ref(false);
const active = computed(() => service.value?.enabled && service.value?.configured);
const zone = computed(() => service.value?.timezone === "Asia/Shanghai" ? "北京时间" : service.value?.timezone);
function sentTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hourCycle:"h23",timeZone:service.value?.timezone }).format(new Date(value));
}
async function load() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await api.get<MailState>("/me/reports/reminders");
    service.value = data;
    email.value = data.email;
  } catch (e: any) { error.value = e.message || "提醒信息加载失败"; }
  finally { loading.value = false; }
}
async function save() {
  if (saving.value) return;
  saving.value = true;
  try {
    const { data } = await api.patch<MailState>("/me/reports/reminders", { email: email.value.trim() });
    service.value = data;
    email.value = data.email;
    ElMessage.success("提醒邮箱已保存");
  } catch (e: any) { ElMessage.error(e.message || "邮箱保存失败"); }
  finally { saving.value = false; }
}
onMounted(load);
</script>

<template>
  <div class="reminders" v-loading="loading">
    <header class="page-heading">
      <h1 class="page-title">邮箱提醒</h1>
      <router-link v-if="store.isAdmin" class="settings-link" :to="{path:'/admin/settings',query:{section:'mail'}}">
        <el-icon><Setting /></el-icon> 配置发件邮箱
      </router-link>
    </header>
    <el-alert v-if="error" type="error" :closable="false">
      <template #title>{{ error }} <button class="link-button" @click="load">重试</button></template>
    </el-alert>
    <div v-if="service" class="stack">
      <div class="mail-grid">
        <section class="panel receiver">
          <h2><label for="my-reminder-email">我的收件邮箱</label></h2>
          <form class="mail-form" @submit.prevent="save">
            <input id="my-reminder-email" v-model="email" type="email" autocomplete="email" maxlength="254" placeholder="输入接收提醒的邮箱" />
            <el-button type="primary" native-type="submit" :loading="saving" :disabled="email.trim()===service.email">保存</el-button>
          </form>
          <p class="muted">本周{{ service.submitted ? '已提交' : '尚未提交' }}周报<span v-if="service.sent_at"> · {{ sentTime(service.sent_at) }} 已发送提醒</span><span v-else-if="!service.email && !service.submitted"> · 填写邮箱后可接收提醒</span></p>
        </section>
        <section class="panel schedule">
          <header class="panel-head">
            <h2>提醒时间</h2>
            <span class="service-state" :class="{active}">{{ serviceLabel(service) }}</span>
          </header>
          <p class="schedule-time">每{{ weekDays[service.weekday-1] }} {{ service.time }}<small>{{ zone }}</small></p>
          <p class="muted">{{ !active && !service.setup ? '管理员启用并配置发件邮箱后生效。' : '截止前检查未交周报，每人每周提醒一次。' }}</p>
          <details class="mail-preview">
            <summary>预览提醒邮件</summary>
            <strong>{{ service.preview.subject }}</strong><p>{{ service.preview.body }}</p>
          </details>
        </section>
      </div>
      <section v-if="service.team" class="panel team">
        <header class="panel-head">
          <h2>团队提醒 <small>第 {{ service.period.iso_week }} 周</small></h2>
          <router-link to="/admin/members" class="link-button">管理成员邮箱</router-link>
        </header>
        <div class="tabline" aria-label="团队提醒记录">
          <button :aria-pressed="tab==='missing'" :class="{chosen:tab==='missing'}" @click="tab='missing'">未交周报 <b>{{ service.team.missing.length }}</b></button>
          <button :aria-pressed="tab==='sent'" :class="{chosen:tab==='sent'}" @click="tab='sent'">已发提醒 <b>{{ service.team.sent.length }}</b></button>
        </div>
        <template v-if="tab==='missing'">
          <div v-for="m in service.team.missing" :key="m.id" class="data-row">
            <span class="avatar" aria-hidden="true">{{ m.name.slice(-1) }}</span>
            <span class="person"><strong>{{ m.name }}</strong><small>{{ m.email || '未填写收件邮箱' }}</small></span>
            <span v-if="m.sent_at || (m.email && active)" class="row-end muted">{{ m.sent_at ? '已提醒' : '待提醒' }}</span>
          </div>
          <p v-if="!service.team.missing.length" class="empty-copy">本周已全员提交。</p>
        </template>
        <template v-else>
          <div v-for="(r,i) in service.team.sent" :key="i" class="data-row">
            <strong class="person">{{ r.name }}</strong><time class="row-end muted" :datetime="r.sent_at">{{ sentTime(r.sent_at) }}</time>
          </div>
          <p v-if="!service.team.sent.length" class="empty-copy">本周还没有发送记录。</p>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.reminders h2 { font-size: 17px; }
.settings-link { display: inline-flex; align-items: center; gap: 7px; padding: 8px 13px; border: 1px solid var(--line); border-radius: 7px; color: var(--teal); background: var(--paper); text-decoration: none; font-size: 14px; font-weight: 600; }
.settings-link:hover { background: var(--soft); }
.mail-grid { display: grid; grid-template-columns: minmax(0,1.35fr) minmax(250px,.95fr); gap: 16px; align-items: start; }
.receiver { border-top: 3px solid #76a582; }
.mail-form { display: flex; align-items: stretch; gap: 8px; margin: 19px 0 12px; }
.mail-form input { width: 0; min-width: 0; flex: 1; padding: 9px 12px; border: 1px solid var(--line); border-radius: 7px; color: var(--ink); background: var(--glass-field); font-size: 14px; }
.mail-form input:focus-visible { outline: 2px solid #638a69; outline-offset: 1px; }
.mail-form .el-button { height: auto; min-height: 38px; }
.schedule .panel-head { margin-bottom: 14px; }
.schedule-time { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; font-size: 22px; font-weight: 650; }
.schedule-time small,.team h2 small { font-size: 12px; font-weight: 500; color: var(--muted); }
.team h2 small { margin-left: 8px; }
.service-state { display: inline-flex; align-items: center; gap: 5px; color: var(--muted); font-size: 12px; }
.service-state::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #ad8941; }
.service-state.active::before { background: #498759; }
.mail-preview { border-top: 1px solid var(--line); margin-top: 15px; padding-top: 12px; font-size: 13px; }
.mail-preview summary { cursor: pointer; color: var(--teal); }
.mail-preview strong { display: block; margin: 12px 0 5px; }
.mail-preview p { white-space: pre-line; overflow-wrap: anywhere; color: var(--muted); line-height: 1.7; }
.person { min-width: 0; overflow-wrap: anywhere; }
.team .row-end { flex: none; }
@media (max-width: 900px) { .mail-grid { grid-template-columns: 1fr; gap: 12px; } }
@media (max-width: 450px) { .team .panel-head { flex-wrap: wrap; gap: 6px; } }
</style>
