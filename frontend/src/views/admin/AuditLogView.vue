<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Search } from "@element-plus/icons-vue";
import api from "@/utils/api";

interface AuditEntry {
  event_id:string; event_type:string; event_label:string; created_at:string;
  actor_name:string; actor_username:string; actor_ip:string|null; actor_location:string;
  result:string; summary:string;
}
const route = useRoute();
const router = useRouter();
const groups = [{id:"", name:"全部记录"}, {id:"login",name:"登录记录"}, {id:"report",name:"周报操作"}, {id:"account",name:"用户管理"}];
const group = ref("");
const days = ref(7);
const query = ref("");
const logs = ref<AuditEntry[]>([]);
const page = ref(1);
const total = ref(0);
const loading = ref(false);
const error = ref("");
let generation = 0;
let searchTimer: number | undefined;
function searchAfterTyping() {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => load(), 250);
}
onBeforeUnmount(() => window.clearTimeout(searchTimer));
function formatTime(iso:string) { return new Date(iso).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai",hour12:false}); }
async function load(p = 1) {
  window.clearTimeout(searchTimer);
  const current = ++generation;
  loading.value=true; error.value="";
  try {
    const {data}=await api.get("/admin/audit/",{params:{days:days.value,group:group.value,actor:query.value.trim(),actor_id:route.query.actor_id,page:p}});
    if(current!==generation) return;
    logs.value=data.events; total.value=data.count; page.value=data.page;
  } catch(e:any){ if(current===generation)error.value=e?.message || "记录加载失败"; }
  finally { if(current===generation)loading.value=false; }
}
function selectGroup(id:string){ group.value=id; void load(); }
watch(()=>route.query.actor_id,()=>{ query.value=""; void load(); },{immediate:true});
</script>

<template>
  <div class="stack">
    <header class="glass-heading"><h1 class="page-title">操作记录</h1></header>
    <section class="panel audit-panel" aria-label="操作记录筛选和列表">
      <nav class="log-tabs" aria-label="记录类型"><button v-for="g in groups" :key="g.id" :aria-pressed="group===g.id" @click="selectGroup(g.id)">{{ g.name }}</button></nav>
      <form class="filters" @submit.prevent="load()">
        <el-tag v-if="route.query.actor_id" closable @close="router.replace({path:'/admin/audit'})">{{ route.query.name || '所选用户' }}</el-tag>
        <el-input v-else v-model="query" placeholder="搜索账号或姓名" aria-label="搜索操作人" :prefix-icon="Search" clearable @input="searchAfterTyping" />
        <el-select v-model="days" aria-label="选择记录时间范围" @change="load()">
          <el-option v-for="d in [1,7,30,90,365]" :key="d" :value="d" :label="'最近 '+d+' 天'" />
        </el-select>
      </form>
      <p v-if="error" role="alert">{{ error }} <button class="link-button" @click="load(page)">重试</button></p>
      <div v-else v-loading="loading" :aria-busy="loading">
        <div class="log-grid headings" aria-hidden="true"><span>操作</span><span>操作人</span><span>地点 / IP</span><span>北京时间</span></div>
        <article v-for="event in logs" :key="event.event_id" class="log-grid log-row">
          <div><strong>{{ event.event_label }}</strong><span v-if="event.result!=='success'" class="failed">{{ event.result==='denied'?'已拒绝':'失败' }}</span><small v-if="event.summary">{{ event.summary }}</small></div>
          <div>{{ event.actor_name || '未认证用户' }}<small v-if="event.actor_username">{{ event.actor_username }}</small></div>
          <div>{{ event.actor_location || "未记录地点" }}<small>{{ event.actor_ip || "未记录 IP" }}</small></div>
          <time :datetime="event.created_at"><span class="mobile-label">北京时间</span>{{ formatTime(event.created_at) }}</time>
        </article>
        <p v-if="!loading && !logs.length" class="empty-copy">所选时间内没有匹配的记录。</p>
        <footer><span>共 {{ total }} 条记录</span><el-pagination v-if="total>30" small layout="prev,pager,next" :total="total" :page-size="30" :current-page="page" @current-change="load" /></footer>
      </div>
    </section>
  </div>
</template>

<style scoped>
.mobile-label { display:none; }
@media(max-width:740px) { .mobile-label { display:block; margin-bottom:2px; font-size:11px; } }
.log-tabs,.filters,.audit-panel footer{display:flex;align-items:center;flex-wrap:wrap;gap:12px}.log-tabs{border-bottom:1px solid var(--line);gap:20px}.log-tabs button{background:none;border:0;border-bottom:2px solid transparent;padding:4px 0 10px;color:var(--muted);font:inherit;font-size:14px}.log-tabs button[aria-pressed="true"]{border-color:#38734f;color:#2b6846;font-weight:650}.filters{margin:15px 0}.filters .el-input{max-width:240px}.filters .el-select{width:132px}.log-grid{display:grid;grid-template-columns:minmax(140px,2fr) minmax(75px,.75fr) minmax(120px,1.15fr) minmax(128px,.95fr);gap:14px;align-items:center}.headings{color:var(--muted);font-size:12px;background:#f2f6f1;padding:8px 10px;border-radius:7px}.log-row{font-size:13px;border-bottom:1px solid var(--line);padding:13px 10px;overflow-wrap:anywhere}.log-row strong{font-size:14px}.log-row small,.log-row time,.audit-panel footer{color:var(--muted);font-size:12px}.log-row small{display:block;margin-top:3px}.log-row time{font-variant-numeric:tabular-nums}.failed{font-size:11px;color:#974238;margin-left:6px}.audit-panel footer{justify-content:space-between;margin-top:12px}
@media(max-width:740px){.headings{display:none}.log-grid.log-row{grid-template-columns:minmax(0,1fr) minmax(105px,.8fr);padding:15px 0;gap:10px}.filters .el-input{width:100%;max-width:none}.log-tabs{gap:11px}.log-tabs button{font-size:13px}}
</style>
