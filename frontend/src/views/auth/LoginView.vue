<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import AuthFrame from "@/components/AuthFrame.vue";
import { useUserStore } from "@/stores/user";

const router = useRouter();
const route = useRoute();
const userStore = useUserStore();
const form = ref({ username: "", password: "", totp_code: "" });
const loading = ref(false);
const error = ref("");

async function handleLogin() {
  if (loading.value || !form.value.username || !form.value.password) return;
  loading.value = true;
  error.value = "";
  try {
    await userStore.login(form.value.username, form.value.password, form.value.totp_code || undefined);
    const next = typeof route.query.next === "string" ? route.query.next : "/";
    const dest = next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") ? router.resolve(next) : null;
    await router.replace(dest?.matched.length && !["login", "activate"].includes(String(dest.name)) ? dest.fullPath : "/");
  } catch (e: any) {
    error.value = e.response?.data?.message || e.message || "登录失败，请重试";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthFrame>
    <h1 id="auth-title">登录工作区</h1>
    <el-form label-position="top" @submit.prevent="handleLogin">
      <el-form-item label="账号">
        <el-input v-model="form.username" autocomplete="username" placeholder="工号或用户名" />
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="form.password" autocomplete="current-password" type="password" show-password placeholder="请输入密码" />
      </el-form-item>
      <details class="totp">
        <summary>使用动态验证码</summary>
        <el-input v-model="form.totp_code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="6 位动态验证码" aria-label="动态验证码" />
      </details>
      <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon />
      <el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" :disabled="!form.username || !form.password">登录</el-button>
      </el-form-item>
    </el-form>
  </AuthFrame>
</template>

<style scoped>
.totp { color:var(--muted); font-size:13px; }
.totp summary { width:fit-content; cursor:pointer; }
.totp .el-input { margin-top:8px; }
</style>
