<script setup lang="ts">
/**
 * 登录页面。
 * 支持用户名/工号 + 密码 + 可选 TOTP。
 */
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { useUserStore } from "@/stores/user";
import { ElMessage } from "element-plus";
import api from "@/utils/api";

const router = useRouter();
const userStore = useUserStore();

const form = ref({ username: "", password: "", totp_code: "" });
const loading = ref(false);
const csrfReady = ref(false);

onMounted(async () => {
  // 先获取 CSRF cookie
  try {
    await api.get("/auth/csrf");
    csrfReady.value = true;
  } catch {
    // 可能还没启动后端
  }
});

async function handleLogin() {
  if (!csrfReady.value) {
    ElMessage.warning("正在连接服务器...");
    return;
  }
  loading.value = true;
  try {
    await userStore.login(form.value.username, form.value.password, form.value.totp_code || undefined);
    ElMessage.success("登录成功");
    router.push("/");
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || e.message || "登录失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-container">
    <el-card class="login-card">
      <template #header>
        <h2>周报整合系统</h2>
      </template>
      <el-form @submit.prevent="handleLogin">
        <el-form-item label="账号">
          <el-input v-model="form.username" placeholder="工号或用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="验证码">
          <el-input v-model="form.totp_code" placeholder="TOTP 验证码（如已启用）" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" native-type="submit" style="width: 100%">
            登录
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: var(--el-bg-color-page);
}
.login-card {
  width: 420px;
}
</style>
