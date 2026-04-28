const API_BASE = window.localStorage.getItem('apiBase') || 'http://127.0.0.1:8765';
const { createApp } = Vue;

createApp({
  data() {
    return {
      apiBase: API_BASE,
      token: localStorage.getItem('token') || '',
      me: null,
      loginForm: { username: 'admin', password: 'admin123' },
      question: '',
      answer: '',
      history: [],
      selected: null,
      users: [],
      questions: [],
      models: [],
      newModel: { name: '', provider: 'openai-compatible', base_url: '', api_key: '', is_active: false },
    };
  },
  computed: {
    currentModelTip() {
      const active = this.models.find((m) => m.is_active);
      return active ? `当前模型: ${active.name}` : '当前模型: 未配置';
    },
  },
  methods: {
    async api(path, options = {}) {
      const res = await fetch(`${this.apiBase}${path}`, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '请求失败');
      return data;
    },
    async doLogin() {
      const data = await this.api('/api/auth/login', { method: 'POST', body: JSON.stringify(this.loginForm) });
      this.token = data.token;
      localStorage.setItem('token', this.token);
      await this.loadMe();
      await this.loadHistory();
      if (this.me?.is_admin) await this.loadModels();
    },
    async loadMe() { this.me = await this.api('/api/auth/me'); },
    async ask() {
      if (!this.question.trim()) return;
      const data = await this.api('/api/chat', { method: 'POST', body: JSON.stringify({ question: this.question }) });
      this.answer = data.answer;
      this.question = '';
      await this.loadHistory();
    },
    async loadHistory() { this.history = await this.api('/api/history'); },
    selectHistory(h) { this.selected = h; this.answer = h.answer; this.question = h.question; },
    async loadUsers() { this.users = await this.api('/api/admin/users'); },
    async loadQuestions() { this.questions = await this.api('/api/admin/questions'); },
    async loadModels() { this.models = await this.api('/api/admin/models'); },
    async saveUser(u) {
      await this.api(`/api/admin/users/${u.id}`, {
        method: 'PATCH', body: JSON.stringify({ is_admin: u.is_admin, can_use_ai: u.can_use_ai }),
      });
    },
    async createModel() {
      await this.api('/api/admin/models', { method: 'POST', body: JSON.stringify(this.newModel) });
      this.newModel = { name: '', provider: 'openai-compatible', base_url: '', api_key: '', is_active: false };
      await this.loadModels();
    },
    async activateModel(id) {
      await this.api(`/api/admin/models/${id}/activate`, { method: 'PATCH' });
      await this.loadModels();
    },
  },
  async mounted() {
    if (this.token) {
      await this.loadMe();
      await this.loadHistory();
      if (this.me?.is_admin) await this.loadModels();
    }
  },
}).mount('#app');
