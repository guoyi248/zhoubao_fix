<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "@/utils/api";

interface User {
  id: string;
  username: string;
  display_name: string;
  role: string;
  department_name: string;
  account_status: string;
}

const users = ref<User[]>([]);
const loading = ref(true);
const showCreate = ref(false);
const newUser = ref({ username: "", display_name: "", role: "member" });

onMounted(loadUsers);

async function loadUsers() {
  loading.value = true;
  try {
    const { data } = await api.get("/admin/users");
    users.value = Array.isArray(data) ? data : [];
  } finally {
    loading.value = false;
  }
}

async function createUser() {
  if (!newUser.value.username || !newUser.value.display_name) return;
  try {
    const res = await api.post("/admin/users/create", newUser.value);
    showCreate.value = false;
    newUser.value = { username: "", display_name: "", role: "member" };
    await loadUsers();
    ElMessage.success(`已创建，激活令牌: ${res.data.activation_token}`);
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function toggleUser(user: User) {
  const action = user.account_status === "active" ? "disable" : "enable";
  try {
    await api.post(`/admin/users/${user.id}/${action}`);
    await loadUsers();
    ElMessage.success(action === "disable" ? "已禁用" : "已恢复");
  } catch (e: any) {
    ElMessage.error(e.message);
  }
}

async function resetPassword(user: User) {
  const { value: pwd } = await ElMessageBox.prompt("请输入新密码（至少8位）", "重置密码", {
    inputType: "password",
  });
  if (pwd) {
    await api.post(`/admin/users/${user.id}/reset-password`, { new_password: pwd });
    ElMessage.success("密码已重置");
  }
}
</script>

<template>
  <div class="members" v-loading="loading">
    <div class="members-header">
      <h2>成员管理</h2>
      <el-button type="primary" size="small" @click="showCreate = !showCreate">
        {{ showCreate ? '取消' : '新建成员' }}
      </el-button>
    </div>

    <el-card v-if="showCreate" style="margin-bottom:16px">
      <el-input v-model="newUser.username" placeholder="账号/工号" style="margin-bottom:8px" />
      <el-input v-model="newUser.display_name" placeholder="姓名" style="margin-bottom:8px" />
      <el-select v-model="newUser.role" style="width:200px;margin-bottom:8px">
        <el-option label="普通成员" value="member" />
        <el-option label="业务管理员" value="admin" />
      </el-select>
      <br />
      <el-button type="primary" @click="createUser" :disabled="!newUser.username||!newUser.display_name">创建</el-button>
    </el-card>

    <el-table :data="users" size="small">
      <el-table-column prop="username" label="账号" width="120" />
      <el-table-column prop="display_name" label="姓名" width="120" />
      <el-table-column prop="department_name" label="部门" width="100" />
      <el-table-column label="角色" width="100">
        <template #default="{ row }">
          <el-tag :type="row.role==='super_admin'?'danger':row.role==='admin'?'warning':'info'" size="small">
            {{ row.role === 'super_admin' ? '超管' : row.role === 'admin' ? '管理员' : '成员' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.account_status==='active'?'success':'danger'" size="small">
            {{ row.account_status === 'active' ? '正常' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button text size="small" @click="toggleUser(row)">
            {{ row.account_status === 'active' ? '禁用' : '恢复' }}
          </el-button>
          <el-button text size="small" @click="resetPassword(row)">重置密码</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.members { padding: 24px; }
.members-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.members-header h2 { font-size: 18px; margin: 0; }
</style>
