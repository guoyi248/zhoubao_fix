<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { MagicStick, Refresh } from "@element-plus/icons-vue";
import api from "@/utils/api";
const route = useRoute();
const emit=defineEmits<{ loaded:[revision:string, status:string] }>();
const props=defineProps<{revisionId:string}>();
interface Item { id:string;item_type:string;title:string;detail:string;human_status:string }
interface Result {status:string;input_warnings?:string[];summary?:string;items?:Item[];model_name?:string;enabled?:boolean;error_message?:string}
const result=ref<Result>();const error=ref("");const working=ref(false);const refresh=ref(0);
const labels:Record<string,string>={achievement:"本周进展",blocker:"阻塞",risk:"风险",coordination:"待协调",next_plan:"下周计划",meeting_topic:"讨论建议"};
const groups=computed(()=>Object.entries(labels).map(([type,label])=>({label,items:(result.value?.items||[]).filter(i=>i.item_type===type&&i.human_status!=="rejected")})).filter(g=>g.items.length));
const pending=computed(()=>["pending","queued","running"].includes(result.value?.status||""));
watch(()=>[props.revisionId,refresh.value] as const,([id],_,cleanup)=>{
  let live=true;let timer:ReturnType<typeof setTimeout>;cleanup(()=>{live=false;clearTimeout(timer);});
  result.value=undefined;error.value="";working.value=false;
  async function fetchResult(){
    try{const {data}=await api.get<Result>("/reports/"+id+"/analysis");if(!live)return;result.value=data;emit("loaded",id,data.status);if(pending.value)timer=setTimeout(fetchResult,3500);}
    catch(e:any){if(live)error.value=e.message||"进展总结加载失败";}
  }
  void fetchResult();
},{immediate:true});
async function generate(){
  const id=props.revisionId;working.value=true;error.value="";
  try{await api.post("/reports/"+id+"/analysis/regenerate");if(id===props.revisionId)refresh.value++;}
  catch(e:any){if(id===props.revisionId)error.value=e.message||"无法生成总结";}
  finally{if(id===props.revisionId)working.value=false;}
}
</script>
<template>
  <section class="summary-box" aria-label="AI 进展总结" aria-live="polite">
    <header class="panel-head">
      <h3><el-icon aria-hidden="true"><MagicStick /></el-icon>AI 进展总结</h3>
      <button v-if="result?.enabled && !pending && !error" class="link-button" :disabled="working" @click="generate">
        <el-icon aria-hidden="true"><Refresh /></el-icon>{{ working ? '请求中…' : result.status==='completed' ? '重新生成' : '生成总结' }}
      </button>
    </header>
    <p v-if="error" class="muted">{{ error }} <button class="link-button" @click="refresh++">重试</button></p>
    <template v-else-if="result?.status === 'completed'">
      <p v-if="result.summary" class="summary-lead">{{ result.summary }}</p>
      <section v-for="group in groups" :key="group.label" class="summary-group">
        <h4>{{ group.label }}</h4>
        <ul><li v-for="item in group.items" :key="item.id">{{ item.title }}<span v-if="item.detail && item.detail !== item.title"> · {{ item.detail }}</span></li></ul>
      </section>
      <p v-for="warning in result.input_warnings" :key="warning" class="muted">{{ warning }}</p>
      <p v-if="!result.summary && !groups.length && !result.input_warnings?.length" class="muted">本版未提取到进展内容。</p>
    </template>
    <p v-else class="muted">
      {{ !result ? '正在读取…' : pending ? '正在解析这版周报…' : result.status==='disabled' ? '尚未启用模型解析。' : result.status==='unconfigured' ? '模型服务尚未配置完整。' : result.status==='failed' ? (result.error_message || '本版解析失败。') : '这版周报尚未生成总结。' }}
      <router-link v-if="result && route.name!=='analysis' && ['disabled','unconfigured'].includes(result.status)" class="link-button" to="/analysis">查看服务</router-link>
    </p>
  </section>
</template>

<style scoped>
.summary-box { padding:15px 18px; min-width:0; border:1px solid #d2e3d3; background:#f3f8f1; border-radius:9px; }
.summary-box .panel-head { gap:10px; margin:0 0 9px; }
.summary-box h3 { display:flex; align-items:center; gap:7px; font-size:15px; }
.summary-box h3 .el-icon { color:var(--teal); }
.summary-lead { color:var(--ink); font-size:14px; line-height:1.8; white-space:pre-line; overflow-wrap:anywhere; }
.summary-group { margin-top:12px; font-size:13px; line-height:1.7; overflow-wrap:anywhere; }
.summary-group h4 { font-size:13px; }
.summary-group ul { padding-inline-start:19px; margin:3px 0; }
.summary-group li span { color:var(--muted); }
.summary-box .muted .link-button { margin-left:5px; }
</style>
