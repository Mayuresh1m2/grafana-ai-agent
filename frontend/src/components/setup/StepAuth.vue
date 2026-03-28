<script setup lang="ts">
import { ref } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'
import { connectGrafana, connectGrafanaAzureCli, connectGrafanaToken, reauthSsoBrowser } from '@/api/session'

type Mode = 'token' | 'sso' | 'credentials' | 'azure-cli'
const session = useSessionStore()

const mode         = ref<Mode>('token')
const serviceToken = ref('')
const azureScope   = ref('')
const username     = ref('')
const password     = ref('')
const connecting   = ref(false)
const error        = ref<string | null>(null)

function ensureSessionId() {
  if (!session.sessionId) session.sessionId = `session_${Date.now()}`
}

async function submitToken() {
  if (!serviceToken.value.trim()) return
  error.value = null
  connecting.value = true
  ensureSessionId()
  try {
    await connectGrafanaToken(session.grafanaUrl, serviceToken.value.trim(), session.sessionId as string)
    session.authStatus = 'complete'
    session.goToStep(3)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    session.authStatus = 'failed'
  } finally {
    connecting.value = false
  }
}

async function submitSso() {
  error.value = null
  connecting.value = true
  ensureSessionId()
  try {
    await reauthSsoBrowser(session.sessionId as string, session.grafanaUrl)
    session.authStatus = 'complete'
    session.goToStep(3)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    session.authStatus = 'failed'
  } finally {
    connecting.value = false
  }
}

async function submitAzureCli() {
  if (!azureScope.value.trim()) return
  error.value = null
  connecting.value = true
  ensureSessionId()
  try {
    await connectGrafanaAzureCli(session.grafanaUrl, azureScope.value.trim(), session.sessionId as string)
    session.authStatus = 'complete'
    session.goToStep(3)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    session.authStatus = 'failed'
  } finally {
    connecting.value = false
  }
}

async function submitCredentials() {
  if (!username.value || !password.value) return
  error.value = null
  connecting.value = true
  ensureSessionId()
  try {
    await connectGrafana(session.grafanaUrl, username.value, password.value, session.sessionId as string)
    session.authStatus = 'complete'
    session.goToStep(3)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    session.authStatus = 'failed'
  } finally {
    connecting.value = false
  }
}

function back() {
  session.authStatus = 'idle'
  session.goToStep(1)
}


</script>

<template>
  <div class="step-panel">
    <h2 class="step-panel__title">Authenticate with Grafana</h2>

    <!-- Mode toggle -->
    <div class="mode-tabs">
      <button
        :class="['mode-tab', { active: mode === 'token' }]"
        @click="mode = 'token'"
      >
        Service Account Token
      </button>
      <button
        :class="['mode-tab', { active: mode === 'azure-cli' }]"
        @click="mode = 'azure-cli'"
      >
        Azure CLI
      </button>
      <button
        :class="['mode-tab', { active: mode === 'sso' }]"
        @click="mode = 'sso'; error = null"
      >
        Microsoft SSO
      </button>
      <button
        :class="['mode-tab', { active: mode === 'credentials' }]"
        @click="mode = 'credentials'"
      >
        Username / Password
      </button>
    </div>

    <!-- ── Service Account Token flow ── -->
    <template v-if="mode === 'token'">
      <p class="step-panel__desc">
        Paste a Grafana service account token. Tokens start with <code>glsa_</code>
        (Grafana ≥ 9) or <code>eyJ</code> (older API keys).
      </p>

      <form class="auth-form" @submit.prevent="submitToken">
        <label class="field">
          <span class="field__label">Service account token</span>
          <input
            v-model="serviceToken"
            type="password"
            class="field__input field__input--mono"
            placeholder="glsa_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            autocomplete="off"
            :disabled="connecting"
          />
          <span class="field__hint">
            Create one in Grafana → Administration → Service accounts.
          </span>
        </label>

        <div v-if="connecting" class="status-card">
          <span class="spinner" aria-label="Connecting…" />
          <span class="status-card__title">Validating token…</span>
        </div>

        <p v-if="error" class="status-error">{{ error }}</p>

        <div class="step-panel__nav">
          <button type="button" class="btn-ghost" :disabled="connecting" @click="back">
            Back
          </button>
          <button
            type="submit"
            class="btn-primary"
            :disabled="connecting || !serviceToken.trim()"
          >
            {{ connecting ? 'Connecting…' : 'Connect' }}
          </button>
        </div>
      </form>
    </template>

    <!-- ── Azure CLI flow ── -->
    <template v-else-if="mode === 'azure-cli'">
      <p class="step-panel__desc">
        Uses your existing <code>az login</code> session — no browser popup needed.
        The backend fetches and auto-refreshes the Azure AD token via
        <code>AzureCliCredential</code>.
      </p>

      <div class="azure-info">
        <p class="azure-info__title">Prerequisites</p>
        <ol class="azure-info__steps">
          <li>Run <code>az login</code> on this machine if you haven't already</li>
          <li>
            Find the Grafana app's <strong>Application (client) ID</strong> in
            Azure Portal → App registrations → your Grafana app → Overview
          </li>
        </ol>
      </div>

      <form class="auth-form" @submit.prevent="submitAzureCli">
        <label class="field">
          <span class="field__label">Grafana Azure AD scope</span>
          <input
            v-model="azureScope"
            type="text"
            class="field__input field__input--mono"
            placeholder="api://00000000-0000-0000-0000-000000000000/.default"
            :disabled="connecting"
          />
          <span class="field__hint">
            Format: <code>api://&lt;grafana-client-id&gt;/.default</code>
          </span>
        </label>

        <div v-if="connecting" class="status-card">
          <span class="spinner" aria-label="Connecting…" />
          <span class="status-card__title">Fetching token via Azure CLI…</span>
        </div>

        <p v-if="error" class="status-error">{{ error }}</p>

        <div class="step-panel__nav">
          <button type="button" class="btn-ghost" :disabled="connecting" @click="back">
            Back
          </button>
          <button
            type="submit"
            class="btn-primary"
            :disabled="connecting || !azureScope.trim()"
          >
            {{ connecting ? 'Connecting…' : 'Connect' }}
          </button>
        </div>
      </form>
    </template>

    <!-- ── SSO flow ── -->
    <template v-else-if="mode === 'sso'">
      <p class="step-panel__desc">
        A browser window will open so you can log in with Microsoft SSO.
        Once you complete login the window closes automatically and the session is established.
      </p>

      <div v-if="connecting" class="status-card">
        <span class="spinner" aria-label="Waiting for login…" />
        <div>
          <p class="status-card__title">Browser window opened</p>
          <p class="status-card__hint">Complete your Microsoft SSO login to continue (up to 3 min).</p>
        </div>
      </div>

      <p v-if="error" class="status-error">{{ error }}</p>

      <div class="step-panel__nav">
        <button class="btn-ghost" :disabled="connecting" @click="back">Back</button>
        <button class="btn-primary" :disabled="connecting" @click="submitSso">
          {{ connecting ? 'Waiting for login…' : 'Log in with SSO' }}
        </button>
      </div>
    </template>

    <!-- ── Credentials flow ── -->
    <template v-else-if="mode === 'credentials'">
      <p class="step-panel__desc">
        Enter your Grafana credentials. A headless browser will log in and extract
        the session cookie — your password is never stored.
      </p>

      <form class="auth-form" @submit.prevent="submitCredentials">
        <label class="field">
          <span class="field__label">Username / e-mail</span>
          <input
            v-model="username"
            type="text"
            autocomplete="username"
            placeholder="admin"
            class="field__input"
            :disabled="connecting"
          />
        </label>

        <label class="field">
          <span class="field__label">Password</span>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="••••••••"
            class="field__input"
            :disabled="connecting"
          />
        </label>

        <div v-if="connecting" class="status-card">
          <span class="spinner" aria-label="Logging in…" />
          <span class="status-card__title">Logging in via headless browser…</span>
        </div>

        <p v-if="error" class="status-error">{{ error }}</p>

        <div class="step-panel__nav">
          <button type="button" class="btn-ghost" :disabled="connecting" @click="back">
            Back
          </button>
          <button
            type="submit"
            class="btn-primary"
            :disabled="connecting || !username || !password"
          >
            {{ connecting ? 'Connecting…' : 'Connect' }}
          </button>
        </div>
      </form>
    </template>

  </div>
</template>

<style scoped>
.step-panel { display: flex; flex-direction: column; gap: 1rem; }
.step-panel__title { font-size: 1.25rem; font-weight: 600; margin: 0; }
.step-panel__desc  { color: var(--text-muted); font-size: 0.9rem; margin: 0; }
.step-panel__actions { display: flex; gap: 0.75rem; }
.step-panel__nav   { display: flex; gap: 0.75rem; margin-top: 0.25rem; }

/* Mode tabs */
.mode-tabs { display: flex; border-bottom: 1px solid var(--border); gap: 0; }
.mode-tab {
  padding: 0.45rem 1rem;
  font-size: 0.85rem;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  cursor: pointer;
  margin-bottom: -1px;
}
.mode-tab.active { color: var(--accent-blue); border-bottom-color: var(--accent-blue); }

/* Status card */
.status-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.75rem;
  background: var(--surface-2);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}
.status-card__title { font-size: 0.9rem; margin: 0 0 0.2rem; }
.status-card__hint  { font-size: 0.8rem; color: var(--text-muted); margin: 0; }

/* Fields */
.auth-form { display: flex; flex-direction: column; gap: 0.75rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.field__label { font-size: 0.8rem; font-weight: 500; color: var(--text-muted); }
.field__input {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  color: var(--text);
  font-size: 0.9rem;
  outline: none;
  resize: vertical;
}
.field__input--mono { font-family: var(--font-mono, monospace); font-size: 0.8rem; }
.field__hint { font-size: 0.75rem; color: var(--text-muted); }
.field__hint code { font-size: 0.75rem; }

.azure-info {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.65rem 0.75rem;
  font-size: 0.82rem;
}
.azure-info__title { font-weight: 600; margin: 0 0 0.4rem; }
.azure-info__steps { margin: 0; padding-left: 1.2rem; line-height: 1.7; color: var(--text-muted); }
.azure-info__steps strong, .azure-info__steps code { color: var(--text); }
.field__input:focus { border-color: var(--accent-blue); }
.field__input:disabled { opacity: 0.6; cursor: not-allowed; }

.status-ok    { font-size: 0.85rem; color: var(--status-ok); margin: 0; }
.status-error { font-size: 0.85rem; color: var(--status-error); margin: 0; }

.btn--sm { padding: 0.3rem 0.65rem; font-size: 0.8rem; white-space: nowrap; flex-shrink: 0; }

.spinner {
  display: inline-block;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  margin-top: 2px;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
