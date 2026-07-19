<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useUserStore } from "@/stores/user";
import { ElMessage } from "element-plus";

const router = useRouter();
const route = useRoute();
const userStore = useUserStore();

const isAuthPage = computed(() =>
  route.path === "/login" || route.path === "/activate",
);

onMounted(async () => {
  if (!isAuthPage.value) {
    await userStore.fetchMe();
    // fetchMe 不抛异常，手动检查
    if (!userStore.isAuthenticated) {
      router.push("/login");
    }
  }
});

async function handleLogout() {
  await userStore.logout();
  router.push("/login");
  ElMessage.success("已退出登录");
}

const navItems = [
  { path: "/", label: "本周工作台", icon: "🏠" },
  { path: "/reports/current", label: "写周报", icon: "✏️" },
  { path: "/reports", label: "历史周报", icon: "📋" },
  { path: "/private-plans", label: "个人计划", icon: "🔒" },
];

const adminNavItems = [
  { path: "/admin/reports", label: "全员周报", icon: "👥" },
  { path: "/admin/members", label: "成员管理", icon: "⚙️" },
  { path: "/admin/audit", label: "审计日志", icon: "📝" },
];

function isActive(path: string) {
  if (path === "/") return route.path === "/";
  return route.path.startsWith(path);
}
</script>

<template>
  <!-- 登录/激活页：无侧边栏 -->
  <router-view v-if="isAuthPage" />

  <!-- 主布局 -->
  <el-container v-else class="app-layout">
    <el-aside width="200px" class="app-sidebar">
      <div class="sidebar-logo" @click="router.push('/')">
        <strong>周报系统</strong>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :class="['nav-item', { active: isActive(item.path) }]"
        >
          {{ item.icon }} {{ item.label }}
        </router-link>

        <template v-if="userStore.isAdmin">
          <div class="admin-label">管理员</div>
          <router-link
            v-for="item in adminNavItems"
            :key="item.path + item.label"
            :to="item.path"
            :class="['nav-item', { active: isActive(item.path) }]"
          >
            {{ item.icon }} {{ item.label }}
          </router-link>
        </template>
      </nav>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <span class="header-title">{{ userStore.user?.display_name || "" }}</span>
        <div class="header-right">
          <el-tag size="small" :type="userStore.isAdmin ? 'danger' : 'info'">
            {{ userStore.isAdmin ? '管理员' : '成员' }}
          </el-tag>
          <el-button text @click="handleLogout">退出</el-button>
        </div>
      </el-header>

      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; }
</style>

<style scoped>
.app-layout { height: 100vh; }

.app-sidebar {
  background: var(--el-bg-color);
  border-right: 1px solid var(--el-border-color-light);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.sidebar-logo {
  padding: 16px;
  font-size: 16px;
  cursor: pointer;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-shrink: 0;
}

.sidebar-nav {
  padding: 8px 0;
  flex: 1;
}

.nav-item {
  display: block;
  padding: 10px 20px;
  font-size: 14px;
  color: var(--el-text-color-regular);
  text-decoration: none;
  transition: background 0.15s;
}

.nav-item:hover {
  background: var(--el-fill-color-light);
}

.nav-item.active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-weight: 500;
}

.admin-label {
  padding: 16px 20px 4px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 8px;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  height: 48px;
  padding: 0 16px;
}

.header-title { font-size: 14px; }

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.el-main {
  background: var(--el-bg-color-page);
  padding: 0;
}
</style>
