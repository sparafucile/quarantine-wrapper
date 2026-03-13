{{/*
quarantine-wrapper: Helm Template Helpers
=========================================
Dynamische Namespace-Namen, Labels, Default-Hostnames und Annotations
für den generischen Quarantine-Wrapper.
*/}}

{{/*
Chart-Name (truncated auf 63 Zeichen, trailing Hyphens entfernt)
*/}}
{{- define "quarantine-wrapper.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Vollqualifizierter App-Name.
Wenn Release-Name den Chart-Namen enthält, wird er nicht doppelt angehängt.
*/}}
{{- define "quarantine-wrapper.fullname" -}}
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

{{/* ============================================================
     NAMESPACE-HELPERS
     ============================================================ */}}

{{/*
App-Namespace: <appName>-quarantine
Hier laufen die isolierten Workloads.
*/}}
{{- define "quarantine-wrapper.appNamespace" -}}
{{- printf "%s-quarantine" (required "appName is required" .Values.appName) }}
{{- end }}

{{/*
Gateway-Namespace: <appName>-quarantine-gw
Hier laufen Squid, mitmproxy, CA-Distribution.
*/}}
{{- define "quarantine-wrapper.gwNamespace" -}}
{{- printf "%s-quarantine-gw" (required "appName is required" .Values.appName) }}
{{- end }}

{{/* ============================================================
     LABEL-HELPERS
     ============================================================ */}}

{{/*
Gemeinsame Labels für alle Ressourcen.
*/}}
{{- define "quarantine-wrapper.labels" -}}
helm.sh/chart: {{ include "quarantine-wrapper.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ .Values.appName }}-quarantine
{{- if .Values.build }}
{{- if .Values.build.number }}
app.kubernetes.io/version: {{ .Values.build.number | quote }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart-Label: <chart-name>-<version>
*/}}
{{- define "quarantine-wrapper.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Labels für den App-Namespace (quarantine).
*/}}
{{- define "quarantine-wrapper.appLabels" -}}
{{ include "quarantine-wrapper.labels" . }}
app.kubernetes.io/component: quarantine
{{- end }}

{{/*
Labels für den Gateway-Namespace (quarantine-gw).
*/}}
{{- define "quarantine-wrapper.gwLabels" -}}
{{ include "quarantine-wrapper.labels" . }}
app.kubernetes.io/component: quarantine-gateway
{{- end }}

{{/*
Selector-Labels für eine spezifische Komponente.
Usage: {{ include "quarantine-wrapper.selectorLabels" (dict "component" "squid" "context" .) }}
*/}}
{{- define "quarantine-wrapper.selectorLabels" -}}
app.kubernetes.io/name: {{ .context.Values.appName }}-quarantine
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* ============================================================
     HOSTNAME-HELPERS
     ============================================================ */}}

{{/*
Default-Hostname für mitmweb.
Wenn mitmproxy.hostname gesetzt ist, wird dieser verwendet.
Sonst: p-mitmweb-<appName>-k8s.<domain>
*/}}
{{- define "quarantine-wrapper.mitmwebHostname" -}}
{{- if .Values.mitmproxy.hostname }}
{{- .Values.mitmproxy.hostname }}
{{- else }}
{{- printf "p-mitmweb-%s-k8s.%s" .Values.appName .Values.gateway.domain }}
{{- end }}
{{- end }}

{{/*
Default-Hostname für hello-world.
Wenn helloWorld.hostname gesetzt ist, wird dieser verwendet.
Sonst: p-<appName>-hello-k8s.<domain>
*/}}
{{- define "quarantine-wrapper.helloWorldHostname" -}}
{{- if .Values.helloWorld.hostname }}
{{- .Values.helloWorld.hostname }}
{{- else }}
{{- printf "p-%s-hello-k8s.%s" .Values.appName .Values.gateway.domain }}
{{- end }}
{{- end }}

{{/*
Default-Hostname für OpenClaw Gateway.
Wenn openclaw.hostname gesetzt ist, wird dieser verwendet.
Sonst: p-<appName>-openclaw-k8s.<domain>
*/}}
{{- define "quarantine-wrapper.openclawHostname" -}}
{{- if .Values.openclaw.hostname }}
{{- .Values.openclaw.hostname }}
{{- else }}
{{- printf "p-%s-openclaw-k8s.%s" .Values.appName .Values.gateway.domain }}
{{- end }}
{{- end }}

{{/* ============================================================
     OPENBAO / EXTERNALSECRET HELPERS
     ============================================================ */}}

{{/*
OpenBao-Pfad für das mitmproxy CA-Keypair.
Default: apps/quarantine/<appName>/mitmproxy-ca
*/}}
{{- define "quarantine-wrapper.openbaoCAPath" -}}
{{- if .Values.ca.openbaoPath }}
{{- .Values.ca.openbaoPath }}
{{- else }}
{{- printf "apps/quarantine/%s/mitmproxy-ca" .Values.appName }}
{{- end }}
{{- end }}

{{/*
OpenBao-Pfad für den Authentik API-Token.
Default: infra/authentik/api-token (shared über alle Quarantine-Apps)
Per-App override via authentik.openbaoPath möglich.
*/}}
{{- define "quarantine-wrapper.openbaoAuthentikPath" -}}
{{- if .Values.authentik.openbaoPath }}
{{- .Values.authentik.openbaoPath }}
{{- else }}
{{- "infra/authentik/api-token" }}
{{- end }}
{{- end }}

{{/* ============================================================
     PROXY-HELPERS
     ============================================================ */}}

{{/*
Squid-Service FQDN (für NetworkPolicies und Env-Vars in App-Pods).
*/}}
{{- define "quarantine-wrapper.squidFQDN" -}}
{{- printf "squid.%s.svc.p-k8s-cluster.local" (include "quarantine-wrapper.gwNamespace" .) }}
{{- end }}

{{/*
mitmproxy-Service FQDN.
*/}}
{{- define "quarantine-wrapper.mitmproxyFQDN" -}}
{{- printf "mitmproxy.%s.svc.p-k8s-cluster.local" (include "quarantine-wrapper.gwNamespace" .) }}
{{- end }}

{{/*
Proxy-Env-Vars für Quarantine-Pods.
Wird als Container env-Block eingebunden.
*/}}
{{- define "quarantine-wrapper.proxyEnv" -}}
- name: http_proxy
  value: {{ printf "http://mitmproxy.%s:8080" (include "quarantine-wrapper.gwNamespace" .) | quote }}
- name: https_proxy
  value: {{ printf "http://mitmproxy.%s:8080" (include "quarantine-wrapper.gwNamespace" .) | quote }}
- name: HTTP_PROXY
  value: {{ printf "http://mitmproxy.%s:8080" (include "quarantine-wrapper.gwNamespace" .) | quote }}
- name: HTTPS_PROXY
  value: {{ printf "http://mitmproxy.%s:8080" (include "quarantine-wrapper.gwNamespace" .) | quote }}
- name: no_proxy
  value: {{ printf ".%s.svc,.%s.svc,%s" (include "quarantine-wrapper.appNamespace" .) (include "quarantine-wrapper.gwNamespace" .) .Values.network.serviceCIDR | quote }}
- name: NO_PROXY
  value: {{ printf ".%s.svc,.%s.svc,%s" (include "quarantine-wrapper.appNamespace" .) (include "quarantine-wrapper.gwNamespace" .) .Values.network.serviceCIDR | quote }}
- name: SSL_CERT_FILE
  value: "/etc/ssl/custom/ca-certificates.crt"
- name: REQUESTS_CA_BUNDLE
  value: "/etc/ssl/custom/ca-certificates.crt"
- name: NODE_EXTRA_CA_CERTS
  value: "/etc/ssl/custom/ca-certificates.crt"
{{- end }}

{{/*
CA-Trust initContainer für Quarantine-Pods.
Installiert das mitmproxy CA-Zertifikat im Trust-Store.
*/}}
{{- define "quarantine-wrapper.caTrustInitContainer" -}}
- name: trust-mitmproxy-ca
  image: {{ printf "%s:%s" .Values.ca.initImage.repository .Values.ca.initImage.tag }}
  command: ["/bin/sh", "-c"]
  args:
    - |
      if [ -f /ca-cert/mitmproxy-ca-cert.pem ]; then
        cp /ca-cert/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy-ca.crt
        update-ca-certificates
        cp /etc/ssl/certs/ca-certificates.crt /shared-certs/ca-certificates.crt
      else
        echo "WARN: CA cert not found, using system certs"
        cp /etc/ssl/certs/ca-certificates.crt /shared-certs/ca-certificates.crt
      fi
  volumeMounts:
    - name: mitmproxy-ca-cert
      mountPath: /ca-cert
      readOnly: true
    - name: shared-certs
      mountPath: /shared-certs
{{- end }}

{{/*
CA-Trust Volumes für Quarantine-Pods.
*/}}
{{- define "quarantine-wrapper.caTrustVolumes" -}}
- name: mitmproxy-ca-cert
  configMap:
    name: mitmproxy-ca-cert
    optional: true
- name: shared-certs
  emptyDir: {}
{{- end }}

{{/*
CA-Trust Volume-Mounts für den App-Container.
*/}}
{{- define "quarantine-wrapper.caTrustVolumeMounts" -}}
- name: shared-certs
  mountPath: /etc/ssl/custom
  readOnly: true
{{- end }}

{{/* ============================================================
     SERVICE-PORT HELPERS
     ============================================================ */}}

{{/*
Generiert eine kommaseparierte Liste aller Service-Ports.
Wird für CiliumNetworkPolicy toPorts verwendet.
*/}}
{{- define "quarantine-wrapper.servicePorts" -}}
{{- $ports := list }}
{{- range .Values.services }}
{{- $ports = append $ports (.port | toString) }}
{{- end }}
{{- join "," $ports }}
{{- end }}
