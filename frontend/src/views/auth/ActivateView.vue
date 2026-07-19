<script setup lang="ts">
/** 账号激活页面——通过一次性令牌设置密码。 */
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
  <div class="activate-container">
    <el-card class="activate-card">
      <template #header><h2>激活账号</h2></template>
      <el-form @submit.prevent="handleActivate">
        <el-form-item label="设置密码">
          <el-input v-model="password" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" native-type="submit" style="width: 100%">
            激活并设置密码
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.activate-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
}
.activate-card {
  width: 420px;
}
</style>
