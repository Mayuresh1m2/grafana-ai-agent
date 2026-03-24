{{/*
Expand the name of the chart.
*/}}
{{- define "grafana-ai-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully-qualified app name.
We truncate at 63 chars because some Kubernetes name fields have that limit.
*/}}
{{- define "grafana-ai-agent.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label.
*/}}
{{- define "grafana-ai-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "grafana-ai-agent.labels" -}}
helm.sh/chart: {{ include "grafana-ai-agent.chart" . }}
app.kubernetes.io/name: {{ include "grafana-ai-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (immutable — used in matchLabels).
*/}}
{{- define "grafana-ai-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "grafana-ai-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Backend service name.
*/}}
{{- define "grafana-ai-agent.backendName" -}}
{{ include "grafana-ai-agent.fullname" . }}-backend
{{- end }}

{{/*
Frontend service name.
*/}}
{{- define "grafana-ai-agent.frontendName" -}}
{{ include "grafana-ai-agent.fullname" . }}-frontend
{{- end }}
