import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const SchedulesView = {
  setup() {
    const items = ref([]);
    const form = ref({
      flag_id: 5, env_id: 1,
      steps_json: '[{"percent":10,"after_hours":0},{"percent":30,"after_hours":24},{"percent":50,"after_hours":48}]',
      note: "批量推送爬坡",
    });
    const err = ref(""); const msg = ref("");
    const ledger = ref(null); const exportRows = ref([]); const busy = ref(false);
    const duelOut = ref("");

    async function reload() { items.value = (await api("/api/schedules")).items || []; }
    async function create() {
      err.value = ""; msg.value = "";
      try {
        const r = await api("/api/schedules", { method: "POST", body: JSON.stringify(form.value) });
        msg.value = `已登记爬坡 #${r.id}，动作账写入 ${r.audit_action || "schedule_create"}`;
        await reload();
        await loadLedger();
      } catch (e) { err.value = e.message || String(e); }
    }
    async function applyNext(id) {
      err.value = "";
      try { const r = await api(`/api/schedules/${id}/apply-next`, { method: "POST", body: "{}" }); msg.value = `已推进到 ${r.applied_percent}%`; await reload(); }
      catch (e) { err.value = e.message || String(e); }
    }
    async function loadLedger() {
      try {
        ledger.value = await api("/api/audit/ledger");
        const ex = await api("/api/audit/export?limit=200");
        exportRows.value = (ex.items || []).filter(x => x.action === "schedule_create");
      } catch (e) { err.value = e.message || String(e); }
    }
    async function review() {
      err.value = ""; msg.value = "";
      try {
        const r = await api("/api/audit/review", { method: "POST", body: JSON.stringify({ scope: "schedule_export" }) });
        msg.value = `复核通过 #${r.review_id}：账实一致（甲路径正式复核已落账）`;
        await loadLedger();
      } catch (e) { err.value = "复核拒写：" + (e.message || String(e)); }
    }
    async function healWhitelist() {
      err.value = ""; msg.value = ""; busy.value = true;
      try {
        const r = await api("/api/audit/reconcile", { method: "POST", body: "{}" });
        msg.value = `白名单已同事务补齐 ${r.reconciled_actions} 个动作码，账实一致=${r.consistent}`;
        await loadLedger();
      } catch (e) { err.value = e.message || String(e); }
      finally { busy.value = false; }
    }
    async function duelWhitelist() {
      // 页面内演示互斥：连发两笔相同的正式白名单变更，恰一笔成功，败方 409 只记争用。
      err.value = ""; duelOut.value = "对打中…"; busy.value = true;
      const payload = JSON.stringify({ action: "schedule_create" });
      const call = () => api("/api/audit/export-whitelist", { method: "POST", body: payload })
        .then(() => "200 胜方（正式变更）")
        .catch((e) => `409 败方（${e.message || "争用，仅留痕"}）`);
      try {
        const [a, b] = await Promise.all([call(), call()]);
        duelOut.value = `双路结果：${a} ｜ ${b}`;
        await loadLedger();
      } finally { busy.value = false; }
    }
    onMounted(async () => { await reload(); await loadLedger(); });
    return {
      items, form, err, msg, create, applyNext, reload, loadLedger,
      ledger, exportRows, review, healWhitelist, duelWhitelist, duelOut, busy,
    };
  },
  template: `
  <div class="grid">
    <div class="panel span-5">
      <h2>比例爬坡计划</h2>
      <p class="hint">本地调度草案；推进下一步会写入正式百分比规则。创建即同事务写动作账 schedule_create。</p>
      <div class="field"><label>开关ID</label><input type="number" v-model.number="form.flag_id" /></div>
      <div class="field"><label>环境ID</label><input type="number" v-model.number="form.env_id" /></div>
      <div class="field"><label>步骤 JSON</label><textarea v-model="form.steps_json" rows="4"></textarea></div>
      <div class="field"><label>备注</label><input v-model="form.note" /></div>
      <button class="btn" @click="create">登记计划</button>
      <p class="muted" v-if="msg">{{ msg }}</p>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
    <div class="panel span-7">
      <h2>计划列表</h2>
      <table>
        <thead><tr><th>ID</th><th>开关</th><th>环境</th><th>状态</th><th>游标</th><th></th></tr></thead>
        <tbody>
          <tr v-for="it in items" :key="it.id">
            <td>{{ it.id }}</td><td>{{ it.flag_key }}</td><td>{{ it.env_code }}</td>
            <td>{{ it.status }}</td><td>{{ it.cursor_step }}</td>
            <td><button class="btn secondary" v-if="it.status==='planned' || it.status==='running'" @click="applyNext(it.id)">推进一步</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel span-12">
      <h2>导出白名单 · 台账核对（计划创建动作不得被滤掉）</h2>
      <p>
        <span class="badge" :style="{background: ledger && ledger.green ? '#1a7f37' : '#cf222e', color:'#fff', padding:'2px 10px', borderRadius:'10px'}">
          {{ ledger ? (ledger.green ? '导出含计划创建 · 账实一致' : '导出缺行 · 非假绿') : '核对中…' }}
        </span>
        <span class="muted" style="margin-left:0.6rem" v-if="ledger">
          动作账 {{ ledger.audit_total }} · 导出 {{ ledger.export_count }} ·
          schedule_create 账 {{ ledger.schedule_create_audit }} · 导出命中 {{ exportRows.length }}
        </span>
      </p>
      <p class="hint" v-if="ledger && !ledger.green">
        缺失动作码：{{ (ledger.missing_actions || []).join(', ') }}。甲路径：缺口下汇总复核正式零增拒写。
      </p>
      <button class="btn" @click="loadLedger">重新核对</button>
      <button class="btn secondary" @click="review">复核台账（甲路径闸门）</button>
      <button class="btn secondary" :disabled="busy" @click="healWhitelist">同事务补齐白名单</button>
      <button class="btn secondary" :disabled="busy" @click="duelWhitelist">双路对打白名单变更互斥</button>
      <p class="muted" v-if="duelOut">{{ duelOut }}</p>
      <p class="hint">并发脚本：scripts/duel_audit_drop_schedule（两笔请求屏障齐发，恰一笔正式成功，败方只记争用）。</p>
    </div>
  </div>`
};
