<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'
import {
  connectGrafana,
  connectGrafanaCookie,
  connectGrafanaAzureCli,
  connectGrafanaServiceToken,
} from '@/api/session'

type Mode = 'token' | 'azure-cli' | 'sso' | 'credentials'
type SsoPhase = 'idle' | 'popup-open' | 'awaiting-cookie' | 'connecting' | 'done'

const session = useSessionStore()

const mode        = ref<Mode>('token')
const tokenInput  = ref('')
const azureScope  = ref('')
const ssoPhase    = ref<SsoPhase>('idle')
const cookieInput = ref('')
const username    = ref('')
const password    = ref('')
const connecting  = ref(false)
const error       = ref<string | null>(null)

// ── Popup management ──────────────────────────────────────────────────────────
let popup: Window | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null

function openPopup() {
  error.value = null
  popup = window.open(session.grafanaUrl, 'grafana-sso', 'width=960,height=700,noopener')
  if (!popup) {
    error.value = 'Pop-up was blocked. Allow pop-ups for this page and try again.'
    return
  }
  ssoPhase.value = 'popup-open'
  pollTimer = setInterval(() => {
    if (popup?.closed) {
      stopPoll()
      if (ssoPhase.value === 'popup-open') ssoPhase.value = 'awaiting-cookie'
    }
  }, 600)
}

function iLoggedIn() {
  stopPoll()
  popup?.close()
  ssoPhase.value = 'awaiting-cookie'
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

onUnmounted(stopPoll)

function ensureSessionId() {
  if (!session.sessionId) session.sessionId = `session_${Date.now()}`
}

// ── Service Account Token ─────────────────────────────────────────────────────
async function submitToken() {
  if (!tokenInput.value.trim()) return
  error.value = null
  connecting.value = true
  ensureSessionId()
  try {
    await connectGrafanaServiceToken(
      session.grafanaUrl,
      tokenInput.value.trim(),
      session.sessionId as string,
    )
    session.authStatus = 'complete'
    session.goToStep(3)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    session.authStatus = 'failed'
  } finally {
    connecting.value = false
  }
}

// ── Azure CLI ─────────────────────────────────────────────────────────────────
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

// ── SSO cookie ────────────────────────────────────────────────────────────────
async function submitCookie() {
  if (!cookieInput.value.trim()) return
  error.value = null
  ssoPhase.value = 'connecting'
  ensureSessionId()
  try {
    await connectGrafanaCookie(session.grafanaUrl, cookieInput.value.trim(), session.sessionId as string)
    session.authStatus = 'complete'
    ssoPhase.value = 'done'
    session.goToStep(3)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    session.authStatus = 'failed'
    ssoPhase.value = 'awaiting-cookie'
  }
}

// ── Credentials ───────────────────────────────────────────────────────────────
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
  stopPoll()
  popup?.close()
  session.authStatus = 'idle'
  session.goToStep(1)
}

function resetSso() {
  stopPoll()
  popup?.close()
  ssoPhase.value = 'idle'
  cookieInput.value = ''
  error.value = null
}
</script>

<template>
  <div class="step-panel">
    <h2 class="step-panel__title">Authenticate with Grafana</h2>

    <!-- Mode toggle -->
    <div class="mode-tabs">
      <button :class="['mode-tab', { active: mode === 'token' }]" @click="mode = 'token'; error = null">
        Service Account Token
      </button>
      <button :class="['mode-tab', { active: mode === 'azure-cli' }]" @click="mode = 'azure-cli'; error = null">
        Azure CLI
      </button>
      <button :class="['mode-tab', { active: mode === 'sso' }]" @click="mode = 'sso'; resetSso()">
        Microsoft SSO
      </button>
      <button :class="['mode-tab', { active: mode === 'credentials' }]" @click="mode = 'credentials'; error = null">
        Username / Password
      </button>
    </div>

    <!-- ── Service Account Token ── -->
    <template v-if="mode === 'token'">
      <p class="step-panel__desc">
        Paste a Grafana service account token. This is also used by the
        <strong>Grafana MCP server</strong> to run live queries during your investigation.
      </p>

      <div class="info-box">
        <p class="info-box__title">How to create a token</p>
        <ol class="info-box__steps">
          <li>Open Grafana → <strong>Administration</strong> → <strong>Service accounts</strong></li>
          <li>Click <strong>Add service account</strong>, set role to <strong>Viewer</strong> (or higher)</li>
          <li>Click <strong>Add service account token</strong> → <strong>Generate token</strong></li>
          <li>Copy the token — it is shown only once</li>
        </ol>
        <p class="info-box__note">
          The token is passed as <code>GRAFANA_API_KEY</code> to the MCP server, which runs
          <code>{{ session.grafanaUrl }}</code> queries on your behalf.
        </p>
      </div>

      <form class="auth-form" @submit.prevent="submitToken">
        <label class="field">
          <span class="field__label">Service account token</span>
          <input
            v-model="tokenInput"
            type="password"
            class="field__input field__input--mono"
            placeholder="glsa_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            autocomplete="off"
            :disabled="connecting"
          />
          <span class="field__hint">Starts with <code>glsa_</code> (Grafana ≥ 9) or <code>eyJ</code> (older API key)</span>
        </label>

        <div v-if="connecting" class="status-card">
          <span class="spinner" aria-label="Connecting…" />
          <span class="status-card__title">Validating token…</span>
        </div>

        <p v-if="error" class="status-error">{{ error }}</p>

        <div class="step-panel__nav">
          <button type="button" class="btn-ghost" :disabled="connecting" @click="back">Back</button>
          <button type="submit" class="btn-primary" :disabled="connecting || !tokenInput.trim()">
            {{ connecting ? 'Connecting…' : 'Connect' }}
          </button>
        </div>
      </form>
    </template>

    <!-- ── Azure CLI ── -->
    <template v-else-if="mode === 'azure-cli'">
      <p class="step-panel__desc">
        Uses your existing <code>az login</code> session.
        Note: the MCP server requires a service account token — this mode uses direct API calls only.
      </p>

      <div class="info-box">
        <p class="info-box__title">Prerequisites</p>
        <ol class="info-box__steps">
          <li>Run <code>az login</code> on this machine</li>
          <li>Find the Grafana app's <strong>Application (client) ID</strong> in Azure Portal → App registrations</li>
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
          <span class="field__hint">Format: <code>api://&lt;grafana-client-id&gt;/.default</code></span>
        </label>

        <div v-if="connecting" class="status-card">
          <span class="spinner" aria-label="Connecting…" />
          <span class="status-card__title">Fetching token via Azure CLI…</span>
        </div>

        <p v-if="error" class="status-error">{{ error }}</p>

        <div class="step-panel__nav">
          <button type="button" class="btn-ghost" :disabled="connecting" @click="back">Back</button>
          <button type="submit" class="btn-primary" :disabled="connecting || !azureScope.trim()">
            {{ connecting ? 'Connecting…' : 'Connect' }}
          </button>
        </div>
      </form>
    </template>

    <!-- ── SSO flow ── -->
    <template v-else-if="mode === 'sso'">
      <p class="step-panel__desc">
        Open Grafana in a pop-up, complete the Microsoft login, then copy the session cookie below.
        Note: the MCP server requires a service account token — this mode uses direct API calls only.
      </p>

      <div v-if="ssoPhase === 'idle'" class="step-panel__actions">
        <button class="btn-primary" @click="openPopup">Open Grafana login</button>
      </div>

      <div v-else-if="ssoPhase === 'popup-open'" class="status-card">
        <span class="spinner" aria-label="Waiting for login…" />
        <div>
          <p class="status-card__title">Complete the Microsoft login in the popup.</p>
          <p class="status-card__hint">The wizard advances automatically when you close it.</p>
        </div>
        <button class="btn-ghost btn--sm" @click="iLoggedIn">I'm logged in</button>
      </div>

      <template v-else-if="ssoPhase === 'awaiting-cookie' || ssoPhase === 'connecting'">
        <div class="cookie-guide">
          <p class="cookie-guide__title">Copy the session cookie from the Grafana tab:</p>
          <ol class="cookie-guide__steps">
            <li>Open DevTools — press <kbd>F12</kbd></li>
            <li>Go to the <strong>Network</strong> tab and refresh</li>
            <li>Click any request to <code>{{ session.grafanaUrl }}</code></li>
            <li>In <strong>Headers → Request Headers</strong>, find <code>Cookie</code></li>
            <li>Right-click → <em>Copy value</em> and paste below</li>
          </ol>
        </div>

        <label class="field">
          <span class="field__label">Cookie header value</span>
          <textarea
            v-model="cookieInput"
            rows="3"
            class="field__input field__input--mono"
            placeholder="grafana_session=abc123; grafana_session_expiry=…"
            :disabled="ssoPhase === 'connecting'"
          />
        </label>

        <p v-if="error" class="status-error">{{ error }}</p>

        <div class="step-panel__nav">
          <button class="btn-ghost" :disabled="ssoPhase === 'connecting'" @click="resetSso">Start over</button>
          <button
            class="btn-primary"
            :disabled="!cookieInput.trim() || ssoPhase === 'connecting'"
            @click="submitCookie"
          >
            {{ ssoPhase === 'connecting' ? 'Validating…' : 'Connect' }}
          </button>
        </div>
      </template>
    </template>

    <!-- ── Credentials ── -->
    <template v-else-if="mode === 'credentials'">
      <p class="step-panel__desc">
        Headless browser login — your password is never stored.
        Note: the MCP server requires a service account token — this mode uses direct API calls only.
      </p>

      <form class="auth-form" @submit.prevent="submitCredentials">
        <label class="field">
          <span class="field__label">Username / e-mail</span>
          <input v-model="username" type="text" autocomplete="username" placeholder="admin" class="field__input" :disabled="connecting" />
        </label>
        <label class="field">
          <span class="field__label">Password</span>
          <input v-model="password" type="password" autocomplete="current-password" placeholder="••••••••" class="field__input" :disabled="connecting" />
        </label>

        <div v-if="connecting" class="status-card">
          <span class="spinner" aria-label="Logging in…" />
          <span class="status-card__title">Logging in via headless browser…</span>
        </div>

        <p v-if="error" class="status-error">{{ error }}</p>

        <div class="step-panel__nav">
          <button type="button" class="btn-ghost" :disabled="connecting" @click="back">Back</button>
          <button type="submit" class="btn-primary" :disabled="connecting || !username || !password">
            {{ connecting ? 'Connecting…' : 'Connect' }}
          </button>
        </div>
      </form>
    </template>

    <!-- SSO idle back button -->
    <div v-if="mode === 'sso' && ssoPhase === 'idle'" class="step-panel__nav">
      <button class="btn-ghost" @click="back">Back</button>
    </div>
  </div>
</template>

<style scoped>
.step-panel { display: flex; flex-direction: column; gap: 1rem; }
.step-panel__title { font-size: 1.25rem; font-weight: 600; margin: 0; }
.step-panel__desc  { color: var(--text-muted); font-size: 0.9rem; margin: 0; }
.step-panel__actions { display: flex; gap: 0.75rem; }
.step-panel__nav   { display: flex; gap: 0.75rem; margin-top: 0.25rem; }

.mode-tabs { display: flex; border-bottom: 1px solid var(--border); gap: 0; flex-wrap: wrap; }
.mode-tab {
  padding: 0.45rem 1rem; font-size: 0.85rem; background: none; border: none;
  border-bottom: 2px solid transparent; color: var(--text-muted); cursor: pointer; margin-bottom: -1px;
}
.mode-tab.active { color: var(--accent-blue); border-bottom-color: var(--accent-blue); }

.info-box {
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 0.65rem 0.75rem; font-size: 0.82rem;
}
.info-box__title { font-weight: 600; margin: 0 0 0.4rem; }
.info-box__steps { margin: 0 0 0.5rem; padding-left: 1.2rem; line-height: 1.7; color: var(--text-muted); }
.info-box__steps strong, .info-box__steps code { color: var(--text); }
.info-box__note  { margin: 0; color: var(--text-muted); font-size: 0.8rem; }
.info-box__note code { color: var(--text); }

.status-card {
  display: flex; align-items: flex-start; gap: 0.75rem; padding: 0.75rem;
  background: var(--surface-2); border-radius: var(--radius); border: 1px solid var(--border);
}
.status-card__title { font-size: 0.9rem; margin: 0 0 0.2rem; }
.status-card__hint  { font-size: 0.8rem; color: var(--text-muted); margin: 0; }

.cookie-guide {
  padding: 0.75rem; background: var(--surface-2); border-radius: var(--radius);
  border: 1px solid var(--border); font-size: 0.85rem;
}
.cookie-guide__title { font-weight: 500; margin: 0 0 0.5rem; }
.cookie-guide__steps { margin: 0; padding-left: 1.25rem; line-height: 1.7; color: var(--text-muted); }
.cookie-guide__steps strong, .cookie-guide__steps code, .cookie-guide__steps em { color: var(--text); }
kbd {
  display: inline-block; padding: 0.1rem 0.35rem; background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 3px; font-size: 0.8rem;
}

.auth-form { display: flex; flex-direction: column; gap: 0.75rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.field__label { font-size: 0.8rem; font-weight: 500; color: var(--text-muted); }
.field__input {
  padding: 0.5rem 0.75rem; border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface-2); color: var(--text); font-size: 0.9rem; outline: none; resize: vertical;
}
.field__input--mono { font-family: var(--font-mono, monospace); font-size: 0.8rem; }
.field__hint { font-size: 0.75rem; color: var(--text-muted); }
.field__hint code { font-size: 0.75rem; }
.field__input:focus { border-color: var(--accent-blue); }
.field__input:disabled { opacity: 0.6; cursor: not-allowed; }

.status-error { font-size: 0.85rem; color: var(--status-error); margin: 0; }
.btn--sm { padding: 0.3rem 0.65rem; font-size: 0.8rem; white-space: nowrap; flex-shrink: 0; }

.spinner {
  display: inline-block; flex-shrink: 0; width: 16px; height: 16px;
  border: 2px solid var(--border); border-top-color: var(--accent-blue);
  border-radius: 50%; animation: spin 0.7s linear infinite; margin-top: 2px;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
