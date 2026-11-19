#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

# -- provider keys -> the env vars ifseen auto-detects -------------------------------------
export_opt() {
    if bashio::config.has_value "$1"; then
        export "$2"="$(bashio::config "$1")"
    fi
}
export_opt gemini_api_key GEMINI_API_KEY
export_opt typesafe_api_key TYPESAFE_API_KEY
export_opt openai_api_key OPENAI_API_KEY
export_opt openai_base_url OPENAI_BASE_URL
export_opt azure_decision_endpoint AZURE_DECISION_ENDPOINT
export_opt azure_decision_key AZURE_DECISION_KEY
export_opt azure_decision_deployment AZURE_DECISION_DEPLOYMENT
IFSEEN_PROVIDER="$(bashio::config 'provider')"; export IFSEEN_PROVIDER

# -- MQTT: explicit options win, else the Supervisor's MQTT service (e.g. Mosquitto add-on) --
if bashio::config.has_value 'mqtt_host'; then
    IFSEEN_MQTT_HOST="$(bashio::config 'mqtt_host')"; export IFSEEN_MQTT_HOST
    IFSEEN_MQTT_PORT="$(bashio::config 'mqtt_port' '1883')"; export IFSEEN_MQTT_PORT
    if bashio::config.has_value 'mqtt_username'; then
        IFSEEN_MQTT_USERNAME="$(bashio::config 'mqtt_username')"; export IFSEEN_MQTT_USERNAME
    fi
    if bashio::config.has_value 'mqtt_password'; then
        IFSEEN_MQTT_PASSWORD="$(bashio::config 'mqtt_password')"; export IFSEEN_MQTT_PASSWORD
    fi
elif bashio::services.available 'mqtt'; then
    IFSEEN_MQTT_HOST="$(bashio::services 'mqtt' 'host')"; export IFSEEN_MQTT_HOST
    IFSEEN_MQTT_PORT="$(bashio::services 'mqtt' 'port')"; export IFSEEN_MQTT_PORT
    IFSEEN_MQTT_USERNAME="$(bashio::services 'mqtt' 'username')"; export IFSEEN_MQTT_USERNAME
    IFSEEN_MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"; export IFSEEN_MQTT_PASSWORD
    if bashio::var.true "$(bashio::services 'mqtt' 'ssl')"; then
        export IFSEEN_MQTT_TLS=true
    fi
    bashio::log.info "Using the MQTT broker from the Supervisor: ${IFSEEN_MQTT_HOST}:${IFSEEN_MQTT_PORT}"
else
    bashio::log.warning "No MQTT broker found (install the Mosquitto add-on or set mqtt_host): no Home Assistant entities will be created."
fi

# -- rules ------------------------------------------------------------------------------------
WORK=/tmp/ifseen
rm -rf "${WORK}" && mkdir -p "${WORK}/inline"
args=()
if bashio::config.has_value 'rules'; then
    name="$(bashio::config 'name' 'ifseen')"
    name="${name//[^A-Za-z0-9_-]/-}"
    bashio::config 'rules' > "${WORK}/inline/${name}.yaml"
    args+=("${WORK}/inline/${name}.yaml")
fi
rules_path="$(bashio::config 'rules_path')"
if [ -d "${rules_path}" ]; then
    shopt -s nullglob
    for f in "${rules_path}"/*.yaml "${rules_path}"/*.yml; do
        args+=("${f}")
    done
    shopt -u nullglob
elif [ -f "${rules_path}" ]; then
    args+=("${rules_path}")
fi

if [ "${#args[@]}" -eq 0 ]; then
    mkdir -p /config
    cp -n /usr/share/ifseen/example.yaml /config/front-door.yaml.example
    bashio::exit.nok "No rules found in ${rules_path}. Rename /addon_configs/<this add-on>/front-door.yaml.example to front-door.yaml and edit it, or paste rules into the 'rules' option."
fi

# Adds the mqtt: section (credentials as ${VAR} references, never written to disk) and the
# default provider to each file, validates it and writes the result to ${WORK}/out.
if ! output="$(ifseen-addon-config "${WORK}/out" "${args[@]}")"; then
    bashio::exit.nok "Fix the rules file errors above, then restart the add-on."
fi
mapfile -t prepared <<< "${output}"

extra=()
if bashio::config.true 'dry_run'; then
    extra+=(--dry-run)
fi

cd /config 2>/dev/null || cd /
bashio::log.info "Starting ifseen with ${#prepared[@]} watcher(s)"
# serve: one process, one watcher and one Home Assistant device per rules file. The HTTP API
# stays on the container's loopback interface.
exec ifseen serve "${extra[@]}" "${prepared[@]}"
