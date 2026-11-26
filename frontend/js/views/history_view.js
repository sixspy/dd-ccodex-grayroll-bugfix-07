import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const HistoryView = {
  setup() {
    const items = ref([]); const err = ref(""); const ledger = ref(null);
    async function reload() {
      try {
        const body = await api("/api/history");
        items.value = body.items || [];
        ledger.value = body.ledger || null;
      }
      catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reload);
    return { items, err, ledger, reload };
  },
  template: `
  <div class="panel">
    <h2>变更历史</h2>
    <p>
      <span class="badge" :style="{background: ledger && ledger.green ? '#1a7f37' : '#cf222e', color:'#fff', padding:'2px 10px', borderRadius:'10px'}">
        {{ ledger ? (ledger.green ? '台账核对一致 · 真绿' : '台账导出缺行 · 非假绿') : '台账状态加载中' }}
      </span>
      <span class="muted" style="margin-left:.6rem" v-if="ledger">
        动作账 {{ ledger.audit_total }} / 导出 {{ ledger.export_count }} / 缺行 {{ ledger.missing_count }}
      </span>
    </p>
    <div class="err" v-if="err">{{ err }}</div>
    <table>
      <thead><tr><th>时间动作</th><th>开关</th><th>环境</th><th>详情</th><th>操作者</th></tr></thead>
      <tbody>
        <tr v-for="it in items" :key="it.id">
          <td>{{ it.action }}<span class="muted" v-if="it.action==='schedule'">（同动作账 schedule_create）</span></td>
          <td>{{ it.flag_key || '-' }}</td><td>{{ it.env_code || '-' }}</td>
          <td>{{ it.detail }}</td><td>{{ it.actor }}</td>
        </tr>
      </tbody>
    </table>
    <button class="btn secondary" style="margin-top:0.7rem" @click="reload">刷新</button>
  </div>`
};
