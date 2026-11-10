<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "@/utils/api";
import AttachmentLimitsForm from "./AttachmentLimitsForm.vue";

type Section = "model" | "mail";
type Provider = "openai_compatible" | "ollama";
interface Service {
  enabled: boolean; version: number; source: "environment" | "database"; has_secret: boolean;
}
interface Model extends Service {
  provider: Provider; base_url: string; model: string;
}
interface Mail extends Service {
  weekday: number; time: string; site_url: string; host: string; port: number;
  username: string; from_email: string; use_tls: boolean; use_ssl: boolean;
}
interface Services { model: Model; mail: Mail }

const path = "/admin/config/integrations";
const route = useRoute();
const router = useRouter();
const section = computed<Section>(() => route.query.section === "mail" ? "mail" : "model");
const original = ref<Services>();
const draft = ref<Services>();
const newSecrets = ref({model:"", mail:""});
const clearSecrets = ref({model:false, mail:false});
const issues = ref({model:"", mail:""});
const loading = ref(false);
const saving = ref(false);
const loadError = ref("");
const week = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"];
const showLimits = computed(() => route.query.section === "attachments");
const active = computed(() => draft.value?.[section.value]);
const mailSecurity = computed({
  get: () => draft.value?.mail.use_ssl ? "ssl" : draft.value?.mail.use_tls ? "tls" : "none",
  set: value => {
    if (draft.value) {
      draft.value.mail.use_tls = value === "tls";
      draft.value.mail.use_ssl = value === "ssl";
    }
  },
});
const differentAddress = computed(() => {
  if (!draft.value || !original.value) return false;
  if (section.value === "model") return draft.value.model.provider !== original.value.model.provider ||
    draft.value.model.base_url.replace(/\/+$/, "") !== original.value.model.base_url.replace(/\/+$/, "");
  const a = draft.value.mail, b = original.value.mail;
  return a.host !== b.host || a.port !== b.port || a.username !== b.username || a.use_tls !== b.use_tls || a.use_ssl !== b.use_ssl;
});
watch(differentAddress, changed => {
  if (changed) clearSecrets.value[section.value] = false;
});
function changes(group: Section): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  if (!draft.value || !original.value) return values;
  const current = draft.value[group];
  const baseline = original.value[group];
  for (const field of Object.keys(current) as (keyof typeof current)[]) {
    if (current[field] !== baseline[field]) values[field] = current[field];
  }
  const secretField = group === "model" ? "api_key" : "password";
  if (newSecrets.value[group]) values[secretField] = newSecrets.value[group];
  else if (clearSecrets.value[group]) values[secretField] = "";
  return values;
}
const dirty = computed(() => Object.keys(changes(section.value)).length > 0);
async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    const {data} = await api.get<Services>(path);
    original.value = data;
    draft.value = {model:{...data.model}, mail:{...data.mail}};
    issues.value = {model:"",mail:""};
    newSecrets.value = {model:"",mail:""};
    clearSecrets.value = {model:false,mail:false};
  } catch (e: any) { loadError.value = e.message || "配置读取失败"; }
  finally { loading.value = false; }
}
function choose(group: Section | "attachments") {
  void router.replace({query:{...route.query,section:group}});
}
function providerChanged(provider: Provider) {
  if (!draft.value || !original.value || draft.value.model.provider === provider) return;
  const same = original.value.model.provider === provider;
  Object.assign(draft.value.model, {
    provider, base_url: same ? original.value.model.base_url : "", model: same ? original.value.model.model : "",
  });
  newSecrets.value.model = "";
  clearSecrets.value.model = false;
}
async function save(reset = false) {
  if (!draft.value || !original.value || saving.value) return;
  const group = section.value;
  if (reset) {
    try {
      await ElMessageBox.confirm("恢复后，该服务将使用部署环境中的配置。", "恢复环境默认值", {
        confirmButtonText:"恢复", cancelButtonText:"取消", type:"warning",
      });
    } catch { return; }
  }
  saving.value = true;
  issues.value[group] = "";
  try {
    const {data} = await api.patch(path, {
      section:group, version:original.value[group].version,
      ...(reset ? {reset:true} : {values:changes(group)}),
    });
    if (group === "model") {
      original.value.model = data as Model;
      draft.value.model = {...original.value.model};
    } else {
      original.value.mail = data as Mail;
      draft.value.mail = {...original.value.mail};
    }
    newSecrets.value[group] = "";
    clearSecrets.value[group] = false;
    ElMessage.success(reset ? "已恢复环境默认值" : "配置已保存，将在下一次任务中生效");
  } catch (e:any) { issues.value[group] = e.message || "保存失败"; }
  finally { saving.value = false; }
}
onMounted(load);
</script>

<template>
  <div class="settings-page stack">
    <header class="glass-panel settings-heading">
      <h1 class="page-title">系统配置</h1>
      <nav class="settings-tabs" aria-label="配置分区">
        <button type="button" :aria-pressed="!showLimits && section==='model'" @click="choose('model')">AI 模型</button>
        <button type="button" :aria-pressed="section==='mail'" @click="choose('mail')">邮箱提醒</button>
        <button type="button" :aria-pressed="showLimits" @click="choose('attachments')">附件限制</button>
      </nav>
    </header>
    <KeepAlive><AttachmentLimitsForm v-if="showLimits" /></KeepAlive>
    <template v-if="!showLimits">
    <p v-if="loadError" role="alert" class="panel">{{ loadError }} <button class="link-button" @click="load">重试</button></p>
    <p v-else-if="loading || !draft || !active" class="panel" role="status">正在读取设置…</p>
    <form v-else class="panel settings-panel" @submit.prevent="save()">
      <fieldset :disabled="saving">
        <div class="enable-row">
          <div><h2 id="enable-service">{{ section==='model' ? '启用 AI 服务' : '提醒未交周报的成员' }}</h2>
            <p id="enable-hint">{{ section==='model' ? '周报自动解析和大肥鱼对话共用此模型。' : '收件地址取自「用户管理」里的提醒收件邮箱。' }}</p></div>
          <label class="switch-label">
            <input v-model="active.enabled" type="checkbox" role="switch" aria-labelledby="enable-service" aria-describedby="enable-hint">
            <span>{{ active.enabled ? '已启用' : '已关闭' }}</span>
          </label>
        </div>
        <template v-if="section==='model'">
          <fieldset class="provider-field"><legend>模型服务</legend>
          <div class="provider-options">
            <label :class="{chosen:draft.model.provider==='openai_compatible'}">
              <input type="radio" name="provider" value="openai_compatible" :checked="draft.model.provider==='openai_compatible'" @change="providerChanged('openai_compatible')">
              <span>在线模型（OpenAI 兼容）</span>
            </label>
            <label :class="{chosen:draft.model.provider==='ollama'}">
              <input type="radio" name="provider" value="ollama" :checked="draft.model.provider==='ollama'" @change="providerChanged('ollama')">
              <span>本地 Ollama</span>
            </label>
          </div></fieldset>
          <div class="setting-fields">
            <label class="wide">服务地址<input v-model.trim="draft.model.base_url" type="url" :required="active.enabled"
              :placeholder="draft.model.provider==='ollama' ? 'http://127.0.0.1:11434' : 'https://api.example.com/v1'"><small>填写周报服务器可访问的地址。</small></label>
            <label class="wide">模型名称<input v-model.trim="draft.model.model" :required="active.enabled" maxlength="180"
              :placeholder="draft.model.provider==='ollama' ? '填写 Ollama 已安装的模型名' : '填写服务商提供的模型 ID'"></label>
          </div>
        </template>
        <template v-else>
          <div class="setting-fields mail-schedule">
            <label>每周提醒日<select v-model.number="draft.mail.weekday"><option v-for="(name,i) in week" :key="name" :value="i+1">{{ name }}</option></select></label>
            <label>发送时间（系统时区）<input v-model="draft.mail.time" type="time" required></label>
            <label class="wide">周报站点网址<input v-model.trim="draft.mail.site_url" type="url" :required="active.enabled" placeholder="https://weekly.example.com"><small>用于生成邮件里的提交链接。</small></label>
          </div>
          <h3>SMTP 发件设置</h3>
          <div class="setting-fields">
            <label>SMTP 服务器<input v-model.trim="draft.mail.host" :required="active.enabled" placeholder="smtp.example.com"></label>
            <label>端口<input v-model.number="draft.mail.port" type="number" min="1" max="65535" required></label>
            <label>连接方式<select v-model="mailSecurity"><option value="tls">STARTTLS</option><option value="ssl">SSL / TLS</option><option value="none">不加密</option></select></label>
            <label>发件邮箱<input v-model.trim="draft.mail.from_email" type="email" :required="active.enabled" placeholder="team@example.com"></label>
          </div>
        </template>
        <div class="setting-fields credentials">
          <label v-if="section==='mail'">SMTP 用户名<input v-model.trim="draft.mail.username" autocomplete="off"></label>
          <label :class="{wide:section==='model'}">{{ section==='model'?'API 密钥':'SMTP 密码或授权码' }}
            <input :key="section" v-model="newSecrets[section]" type="password" autocomplete="new-password" maxlength="4096"
              :disabled="clearSecrets[section]" :placeholder="active.has_secret && !differentAddress ? '已设置，留空保留' : '按服务要求填写'">
            <small v-if="section==='model' && !(differentAddress && active.has_secret)">此处填写的密钥会在服务器上加密保存。</small>
            <small v-if="differentAddress && active.has_secret">连接信息已更改。新服务如需凭据，请重新填写。</small>
          </label>
          <label v-if="active.has_secret && !differentAddress" class="check-field wide"><input v-model="clearSecrets[section]" type="checkbox" @change="newSecrets[section]=''">清除当前凭据</label>
        </div>
        <div v-if="issues[section]" class="error-row" role="alert">{{ issues[section] }} <button type="button" class="link-button" @click="load">重新载入</button></div>
        <footer>
          <span class="config-source">{{ active.source==='environment' ? '当前使用环境默认值' : '当前使用管理员配置' }}</span>
          <div class="save-actions">
            <button v-if="active.source==='database'" type="button" class="link-button" @click="save(true)">恢复环境默认值</button>
            <button class="save" type="submit" :disabled="!dirty || saving">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </footer>
      </fieldset>
    </form>
    </template>
  </div>
</template>

<style scoped>
.settings-page{max-width:860px}
.settings-heading{display:grid;gap:10px;border:1px solid var(--glass-edge);border-radius:13px;padding:clamp(16px,2.3vw,26px) clamp(18px,3vw,32px) 0}
.settings-tabs{display:flex;flex-wrap:wrap;gap:0 18px}
.settings-tabs button{border:0;border-bottom:2px solid transparent;padding:8px 3px 12px;background:transparent;color:var(--muted);font-weight:600}
.settings-tabs button[aria-pressed=true]{color:var(--teal);border-color:#408565}.settings-panel{padding:clamp(18px,3vw,32px);max-width:860px}
fieldset{border:0;margin:0;padding:0;min-width:0}.enable-row,footer{display:flex;align-items:center;justify-content:space-between;gap:16px}
.enable-row{border-bottom:1px solid var(--line);padding-bottom:16px}.enable-row h2{font-size:17px;margin:0}.enable-row p,.setting-fields small{font-size:13px;font-weight:400;color:var(--muted);margin:4px 0 0;line-height:1.5}
.switch-label{display:inline-flex;align-items:center;gap:7px;white-space:nowrap;font-size:13px}
.switch-label input{appearance:none;position:relative;width:36px;height:21px;margin:0;border:1px solid #899a91;border-radius:15px;background:#e1e7e2}
.switch-label input:before{content:'';position:absolute;top:2px;left:2px;width:15px;height:15px;border-radius:100%;background:#fff;box-shadow:0 1px 3px #59685b50}
.switch-label input:checked{background:#347855;border-color:#347855}.switch-label input:checked:before{left:17px}
.settings-panel h3{font-size:15px;margin:22px 0 10px}.provider-options,.setting-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.provider-field{margin:18px 0}.provider-field legend{font-size:13px;font-weight:600;margin-bottom:7px;padding:0}
.provider-options{display:flex;gap:6px;flex-wrap:wrap}.provider-options label{cursor:pointer;display:flex;align-items:center;gap:6px;border:1px solid var(--line);padding:7px 11px;border-radius:6px;font-size:13px}
.provider-options label.chosen{border-color:#83a78b;background:rgb(202 226 201 / 53%)}.provider-options input,.check-field input{accent-color:#337855}.mail-schedule{margin-top:18px}.config-source{color:var(--muted)}
.setting-fields>label{display:flex;flex-direction:column;gap:5px;font-size:13px;font-weight:600}.setting-fields .wide{grid-column:1/-1}
.setting-fields input:not([type=checkbox]),.setting-fields select{border:1px solid #a7b9ad;border-radius:6px;background:rgb(255 255 255 / 68%);color:var(--ink);width:100%;padding:9px 11px;min-height:39px;font:inherit;font-weight:400}
.settings-panel :is(input,select,button):focus-visible{outline:2px solid #41815f;outline-offset:2px}.setting-fields small{margin:0}.credentials{margin-top:15px}
.setting-fields .check-field{flex-direction:row;align-items:center;font-weight:400}.error-row{color:#9e3529;margin:12px 0;font-size:14px}
footer{border-top:1px solid var(--line);padding-top:17px;margin-top:22px;font-size:13px}.save-actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.save{background:#276447;color:white;border:0;border-radius:7px;padding:9px 17px;font-size:14px;font-weight:650}.save:disabled{background:#dae4dc;color:#627169}
@media(max-width:620px){.setting-fields,.provider-options{grid-template-columns:1fr}.enable-row{align-items:flex-start}footer{align-items:flex-start;flex-direction:column}.provider-options{gap:8px}.settings-page{min-width:0}}
</style>
