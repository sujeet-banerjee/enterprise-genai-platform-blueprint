{{/*
Common helpers for the genai-platform chart (roadmap G2).
*/}}
{{- define "genai-platform.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "genai-platform.fullname" -}}
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

{{- define "genai-platform.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "genai-platform.labels" -}}
helm.sh/chart: {{ include "genai-platform.chart" . }}
{{ include "genai-platform.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "genai-platform.selectorLabels" -}}
app.kubernetes.io/name: {{ include "genai-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "genai-platform.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "genai-platform.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "genai-platform.modelCacheClaim" -}}
{{- if .Values.modelCache.existingClaim }}
{{- .Values.modelCache.existingClaim }}
{{- else }}
{{- printf "%s-model-cache" (include "genai-platform.fullname" .) }}
{{- end }}
{{- end }}
