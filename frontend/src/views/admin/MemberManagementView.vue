<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Plus, Search, MoreFilled } from "@element-plus/icons-vue";
import api from "@/utils/api";
import { useUserStore } from "@/stores/user";

type Role = "member" | "admin";
interface Member {
  id: number; username: string; display_name: string; email: string; role: Role;
  account_status: string; last_login_at: string | null; last_login_ip: string | null;
  last_login_location: string | null;
}
interface Form { username: string; display_name: string; email: string; role: Role }
const emptyForm = (): Form => ({ username:"", display_name:"", email:"", role:"member" });
const store = useUserStore();
const router = useRouter();
const statusLabels: Record<string,string> = { invited:"待激活", pending_approval:"待审批", active:"正常", disabled:"已停用" };
const users = ref<Member[]>([]);
const query = ref("");
const role = ref<Role | "">("");
const total = ref(0);
const page = ref(1);
const loading = ref(false);
const error = ref("");
const showForm = ref(false);
const target = ref<Member | null>(null);
const form = ref<Form>(emptyForm());
const saving = ref(false);
const formError = ref("");
const inviteLink = ref("");
let requestNo = 0;
let searchTimer: number | undefined;
function searchAfterTyping() {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => load(), 250);
}
onBeforeUnmount(() => window.clearTimeout(searchTimer));

function readableError(cause: any) {
  const data = cause?.response?.data;
  if (data && typeof data === "object") {
    if (data.message) return data.message;
    const field = Object.values(data).find(Array.isArray);
    if (field) return field.join(" ");
  }
  return cause?.message || "请求失败，请重试";
}
async function load(p = 1) {
  window.clearTimeout(searchTimer);
  const no = ++requestNo;
  loading.value = true;
  error.value = "";
  try {
    const {data} = await api.get("/admin/users", {params:{ page:p, q:query.value.trim(), role:role.value }});
    if (no !== requestNo) return;
    users.value = data.users; page.value = data.page; total.value = data.total;
  } catch (cause) { if (no === requestNo) error.value = readableError(cause); }
  finally { if (no === requestNo) loading.value = false; }
}
function openForm(member: Member | null) {
  target.value = member;
  form.value = member ? { username:member.username, display_name:member.display_name, email:member.email, role:member.role } : emptyForm();
  formError.value = ""; showForm.value = true;
}
async function save() {
  if (saving.value) return;
  saving.value = true; formError.value = "";
  try {
    if (target.value) {
      await api.patch("/admin/users/" + target.value.id, form.value);
      if (target.value.id === store.user?.id) await store.fetchMe();
      ElMessage.success("用户信息已更新");
    } else {
      const {data} = await api.post("/admin/users/create", form.value);
      const url = new URL("/activate", window.location.origin);
      url.searchParams.set("token", data.activation_token);
      inviteLink.value = url.href;
    }
    showForm.value = false;
    await load(target.value ? page.value : 1);
  } catch (cause) { formError.value = readableError(cause); }
  finally { saving.value = false; }
}
function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai",hour12:false}) : "尚未登录";
}
async function action(command: string, member: Member) {
  const url = "/admin/users/" + member.id;
  try {
    if (command === "history") {
      await router.push({path:"/admin/audit",query:{ actor_id:String(member.id), name:member.display_name }});
      return;
    }
    if (command === "reset") {
      const {value} = await ElMessageBox.prompt("设置新密码（至少 8 位）", "重置 " + member.display_name + " 的密码", {
        inputType:"password", inputPattern:/^.{8,128}$/, inputErrorMessage:"请输入 8 至 128 位密码",
        confirmButtonText:"重置密码", cancelButtonText:"取消",
      });
      await api.post(url + "/reset-password", { new_password:value });
      ElMessage.success("密码已重置");
    } else if (command === "delete") {
      await ElMessageBox.confirm("删除后该账号无法登录，账号名、已提交的周报和操作记录会留作历史记录。",
        "删除用户「" + member.display_name + "」？", {confirmButtonText:"删除用户",cancelButtonText:"取消",type:"warning"});
      await api.delete(url + "/delete");
      ElMessage.success("用户已删除");
    } else {
      const disable = command === "disable";
      if (disable) await ElMessageBox.confirm("该用户的登录会话将失效，可在这里恢复账号。","停用「" + member.display_name + "」？",
        {confirmButtonText:"停用",cancelButtonText:"取消",type:"warning"});
      await api.post(url + (disable ? "/disable" : "/enable"));
      ElMessage.success(disable ? "账号已停用" : "账号已恢复");
    }
    await load(page.value);
  } catch (cause) { if (cause !== "cancel" && cause !== "close") ElMessage.error(readableError(cause)); }
}
onMounted(() => load());
</script>

<template>
  <div class="stack users-page">
    <header class="section-heading glass-heading">
      <h1 class="page-title">用户管理</h1>
      <el-button type="primary" :icon="Plus" @click="openForm(null)">新增用户</el-button>
    </header>
    <section class="panel directory" aria-label="用户列表">
      <form class="tools" @submit.prevent="load()">
        <el-input v-model="query" aria-label="搜索用户" placeholder="搜索姓名、账号或邮箱" :prefix-icon="Search" clearable @input="searchAfterTyping" />
        <el-select v-model="role" aria-label="按角色筛选" @change="load()"><el-option label="全部角色" value="" />
          <el-option label="管理员" value="admin" /><el-option label="普通用户" value="member" /></el-select>
      </form>
      <p v-if="error" role="alert">{{ error }} <button class="link-button" @click="load(page)">重试</button></p>
      <div v-else v-loading="loading" :aria-busy="loading">
        <div class="user-grid columns" aria-hidden="true"><span>成员</span><span>权限与状态</span><span>最近登录 · 北京时间</span><span>操作</span></div>
        <article v-for="member in users" :key="member.id" class="user-grid user-row">
          <div class="identity"><span class="user-avatar" aria-hidden="true">{{ member.display_name.slice(-1) }}</span><div><strong>{{ member.display_name }}</strong>
            <small>{{ member.username }}</small><small v-if="member.email">{{ member.email }}</small></div></div>
          <div><span class="role-chip" :class="{admin:member.role==='admin'}">{{ member.role==='admin'?'管理员':'普通用户' }}</span>
            <small>{{ statusLabels[member.account_status] || member.account_status }}</small></div>
          <div class="last-login"><span v-if="member.last_login_at" class="mobile-label">最近登录（北京时间）</span><span>{{ formatTime(member.last_login_at) }}</span>
            <small v-if="member.last_login_at">{{ member.last_login_location || "未记录地点" }} · {{ member.last_login_ip || "IP 未记录" }}</small></div>
          <div class="row-actions"><el-button text @click="openForm(member)">编辑</el-button>
            <el-dropdown trigger="click" @command="action($event, member)"><el-button text :icon="MoreFilled" :aria-label="'更多操作 · '+member.display_name" />
              <template #dropdown><el-dropdown-menu>
                <el-dropdown-item command="history">操作记录</el-dropdown-item><el-dropdown-item command="reset">重置密码</el-dropdown-item>
                <el-dropdown-item v-if="member.id !== store.user?.id && member.account_status==='active'" command="disable">停用账号</el-dropdown-item>
                <el-dropdown-item v-if="member.account_status==='disabled'" command="enable">恢复账号</el-dropdown-item>
                <el-dropdown-item v-if="member.id !== store.user?.id" command="delete" divided>删除用户</el-dropdown-item>
              </el-dropdown-menu></template>
            </el-dropdown></div>
        </article>
        <p v-if="!loading && !users.length" class="empty-copy">没有找到符合条件的用户。</p>
        <footer><small>共 {{ total }} 位用户</small><el-pagination v-if="total>25" small layout="prev,pager,next" :total="total" :page-size="25" :current-page="page" @current-change="load" /></footer>
      </div>
    </section>
    <el-dialog v-model="showForm" :title="target?'编辑用户':'新增用户'" width="min(440px, 92vw)" :close-on-click-modal="false" :show-close="!saving" :close-on-press-escape="!saving">
      <form id="user-editor" class="user-form" @submit.prevent="save">
        <label>账号<input v-model.trim="form.username" required maxlength="150" autocomplete="off" /></label>
        <label>姓名<input v-model.trim="form.display_name" required maxlength="150" autocomplete="off" /></label>
        <label>提醒收件邮箱<input v-model.trim="form.email" type="email" placeholder="可选" maxlength="254" /></label>
        <label>角色<select v-model="form.role" aria-label="角色" :disabled="target?.id === store.user?.id"><option value="member">普通用户</option><option value="admin">管理员</option></select></label>
        <p v-if="target?.id === store.user?.id" class="hint">更改自己的角色需由另一位管理员操作。</p>
        <p v-else-if="form.role==='admin'" class="hint">管理员可展示组会、维护知识库和管理系统。</p>
        <p v-if="formError" class="error" role="alert">{{ formError }}</p>
      </form>
      <template #footer><el-button :disabled="saving" @click="showForm=false">取消</el-button><el-button type="primary" native-type="submit" form="user-editor" :loading="saving">{{ target?'保存':'创建账号' }}</el-button></template>
    </el-dialog>
    <el-dialog :model-value="!!inviteLink" @close="inviteLink=''" title="账号已创建" width="min(440px, 92vw)">
      <p>将激活链接发给成员，24 小时内可设置密码。</p>
      <el-input aria-label="激活链接" :model-value="inviteLink" readonly @focus="($event.target as HTMLInputElement).select()" />
      <template #footer><el-button type="primary" @click="inviteLink=''">完成</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mobile-label { display:none; }
.hint { color:var(--muted); line-height:1.5; }
@media(max-width:760px) {
  .mobile-label { display:block; color:var(--muted); margin-bottom:2px; font-size:11px; }
}
.section-heading,.tools,.row-actions,.directory footer{display:flex;align-items:center;gap:10px}.section-heading,.directory footer{justify-content:space-between}.tools{flex-wrap:wrap;margin-bottom:15px}.tools .el-input{max-width:275px}.tools .el-select{width:132px}.user-grid{display:grid;grid-template-columns:minmax(150px,1.5fr) minmax(96px,.7fr) minmax(152px,1.4fr) 96px;gap:14px;align-items:center}.columns{background:var(--surface-soft,#f3f7f3);border-radius:7px;padding:8px 10px;color:var(--muted);font-size:12px}.user-row{padding:14px 10px;border-bottom:1px solid var(--line);font-size:14px;overflow-wrap:anywhere}.user-row small,.directory footer small{display:block;color:var(--muted);font-size:12px;margin-top:3px}.identity{display:flex;align-items:center;gap:10px}.user-avatar{flex:0 0 35px;height:35px;display:grid;place-items:center;border-radius:10px;color:#315f43;background:#e5efe5}.role-chip{font-size:12px}.role-chip.admin{color:#2c6847;font-weight:650}.row-actions{gap:0}.row-actions .el-button{padding:7px}.directory footer{margin-top:11px}.user-form{display:grid;gap:13px}.user-form label{display:grid;gap:4px;color:var(--muted);font-size:13px}.user-form input,.user-form select{width:100%;border:1px solid var(--line,#ccd9d1);background:#fff;border-radius:6px;padding:9px;color:var(--ink);font:inherit}.hint,.error{font-size:13px}.error{color:#a33b34}
@media(max-width:760px){.columns{display:none}.user-grid.user-row{grid-template-columns:minmax(0,1fr) auto;gap:8px 12px;padding:13px 0}.identity{grid-column:1}.last-login{font-size:12px}.user-row>div:nth-child(2){text-align:right}.row-actions{justify-content:flex-end}.tools .el-input{max-width:100%;width:100%}}
</style>
