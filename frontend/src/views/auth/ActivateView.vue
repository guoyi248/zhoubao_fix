<script setup lang="ts">
/** 账号激活页面——通过一次性令牌设置密码。 */
import AuthFrame from "@/components/AuthFrame.vue";
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import api from "@/utils/api";
import { ElMessage } from "element-plus";

const route = useRoute();
const router = useRouter();

const token = ref((route.query.token as string) || "");
const password = ref("");
const loading = ref(false);

async function handleActivate() {
  if (loading.value || !token.value || password.value.length < 8) return;
  loading.value = true;
  try {
    await api.post("/auth/activate", { token: token.value, password: password.value });
    ElMessage.success("账号已激活，请登录");
    router.push("/login");
  } catch (e: any) {
    ElMessage.error(e.message || "激活失败");
  } finally {
    loading.value = false;
  }
}
</script>
<template>
  <AuthFrame>
    <h1 id="auth-title">激活账号</h1>
    <el-form label-position="top" @submit.prevent="handleActivate">
      <el-form-item label="设置密码">
        <el-input v-model="password" type="password" autocomplete="new-password" show-password placeholder="至少 8 位字符" />
      </el-form-item>
      <el-alert v-if="!token" type="warning" :closable="false" title="请从管理员发给你的完整激活链接进入。" />
      <el-form-item>
        <el-button type="primary" native-type="submit" :disabled="!token || password.length < 8" :loading="loading">激活账号</el-button>
      </el-form-item>
    </el-form>
  </AuthFrame>
</template>
