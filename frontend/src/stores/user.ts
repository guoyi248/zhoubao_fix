/**
 * 用户状态管理（Pinia）。
 * 仅保存会话 UI 状态，不缓存敏感数据到持久化存储。
 */
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/utils/api";

export interface UserInfo {
  id: string;
  username: string;
  display_name: string;
  role: "member" | "admin" | "super_admin";
  department_name: string;
  totp_enabled: boolean;
}

export const useUserStore = defineStore("user", () => {
  const user = ref<UserInfo | null>(null);
  const loading = ref(false);

  const isAuthenticated = computed(() => user.value !== null);
  const isAdmin = computed(() => user.value?.role === "admin" || user.value?.role === "super_admin");
  const isSuperAdmin = computed(() => user.value?.role === "super_admin");

  async function fetchMe() {
    loading.value = true;
    try {
      const { data } = await api.get<UserInfo>("/me");
      user.value = data;
    } catch {
      user.value = null;
    } finally {
      loading.value = false;
    }
  }

  async function login(username: string, password: string, totpCode?: string) {
    const { data } = await api.post<UserInfo>("/auth/login", {
      username,
      password,
      totp_code: totpCode,
    });
    user.value = data;
    return data;
  }

  async function logout() {
    await api.post("/auth/logout");
    user.value = null;
  }

  function clearUser() {
    user.value = null;
  }

  return {
    user,
    loading,
    isAuthenticated,
    isAdmin,
    isSuperAdmin,
    fetchMe,
    login,
    logout,
    clearUser,
  };
});
