import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const DashboardView = {
  setup() {
    const data = ref(null); const health = ref(null); const err = ref("");
    async function reload() {
      err.value = "";
      try {
        health.value = await api("/api/health");
        data.value = await api("/api/dashboard");
      } catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reload);
    return { data, health, err, reload };
  },
  template: `
  <div class="grid">
    <div class="panel span-12">
      <h2>发布控制台</h2>
      <p class="muted">{{ health && health.skeleton }}</p>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
    <div class="panel span-4" v-if="data"><div class="muted">开关数</div><p class="stat">{{ data.flags }}</p></div>
    <div class="panel span-4" v-if="data"><div class="muted">已生效</div><p class="stat">{{ data.active }}</p></div>
    <div class="panel span-4" v-if="data"><div class="muted">开放影子</div><p class="stat">{{ data.open_shadows }}</p></div>

    <div class="panel span-12" v-if="data">
      <h2>导出白名单 · 动作账核对（gbf07）</h2>
      <p class="hint">爬坡计划创建动作码 schedule_create 必须在导出白名单内；导出与动作账条数一致才是真绿。</p>
      <p>
        <span class="badge" :style="{background: data.audit_green ? '#1a7f37' : '#cf222e', color:'#fff', padding:'2px 10px', borderRadius:'10px'}">
          {{ data.audit_green ? '账实一致 · 真绿' : '导出缺行 · 非假绿' }}
        </span>
        <span class="muted" style="margin-left:0.6rem">
          动作账 {{ data.audit_ledger && data.audit_ledger.audit_total }} 条 ·
          导出 {{ data.audit_ledger && data.audit_ledger.export_count }} 条 ·
          缺行 {{ data.audit_missing_count }}
        </span>
      </p>
      <div class="err" v-if="!data.audit_green">
        白名单漏配/被摘动作码：{{ (data.audit_missing_actions || []).join(', ') || 'schedule_create' }}；
        此时汇总复核正式写口拒写，不得把缺行当已复核。
      </div>
    </div>

    <div class="panel span-6" v-if="data">
      <h2>状态分布</h2>
      <table><thead><tr><th>状态</th><th>数量</th></tr></thead>
      <tbody><tr v-for="s in data.by_status" :key="s.status"><td>{{ s.label }}</td><td>{{ s.c }}</td></tr></tbody></table>
    </div>
    <div class="panel span-6" v-if="data">
      <h2>最近变更</h2>
      <table><thead><tr><th>动作</th><th>详情</th><th>操作者</th></tr></thead>
      <tbody><tr v-for="h in data.recent" :key="h.id"><td>{{ h.action }}</td><td>{{ h.detail }}</td><td>{{ h.actor }}</td></tr></tbody></table>
      <button class="btn secondary" style="margin-top:0.7rem" @click="reload">刷新</button>
    </div>
  </div>`
};
