#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/deploy/.env"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-sub2api-postgres}"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker command not found" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[ERROR] Missing env file: ${ENV_FILE}" >&2
  echo "        Copy deploy/.env.example to deploy/.env first." >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

POSTGRES_USER="${POSTGRES_USER:-sub2api}"
POSTGRES_DB="${POSTGRES_DB:-sub2api}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"

if [[ -z "${POSTGRES_PASSWORD}" ]]; then
  echo "[ERROR] POSTGRES_PASSWORD is empty in ${ENV_FILE}" >&2
  exit 1
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "${POSTGRES_CONTAINER}" 2>/dev/null || true)" != "true" ]]; then
  echo "[ERROR] PostgreSQL container is not running: ${POSTGRES_CONTAINER}" >&2
  exit 1
fi

BACKUP_DIR="${REPO_ROOT}/deploy/backups"
mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/openai-model-mapping-backup-${TIMESTAMP}.jsonl"

MODEL_MAPPING_JSON='{"claude-haiku*":"gpt-5.3-codex-spark","claude-sonnet*":"gpt-5.4","claude-opus*":"gpt-5.4","gpt-5":"gpt-5","gpt-5.1":"gpt-5.1","gpt-5.1-codex":"gpt-5.1-codex","gpt-5.1-codex-max":"gpt-5.1-codex-max","gpt-5.1-codex-mini":"gpt-5.1-codex-mini","gpt-5.2":"gpt-5.2","gpt-5.2-codex":"gpt-5.2-codex","gpt-5.3-codex":"gpt-5.3-codex","gpt-5.3-codex-spark":"gpt-5.3-codex-spark","gpt-5.4":"gpt-5.4"}'

echo "[INFO] Backing up current OpenAI account model_mapping to: ${BACKUP_FILE}"
docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_CONTAINER}" \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -At <<'SQL' > "${BACKUP_FILE}"
SELECT json_build_object(
  'id', id,
  'name', name,
  'status', status,
  'schedulable', schedulable,
  'model_mapping', COALESCE(credentials->'model_mapping', '{}'::jsonb)
)::text
FROM accounts
WHERE deleted_at IS NULL
  AND platform = 'openai'
ORDER BY id;
SQL

echo "[INFO] Applying corrected model_mapping to all OpenAI accounts"
docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_CONTAINER}" \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<SQL
\set ON_ERROR_STOP on

WITH updated AS (
  UPDATE accounts
  SET credentials = jsonb_set(
        COALESCE(credentials, '{}'::jsonb),
        '{model_mapping}',
        \$json\$${MODEL_MAPPING_JSON}\$json\$::jsonb,
        true
      ),
      updated_at = NOW()
  WHERE deleted_at IS NULL
    AND platform = 'openai'
  RETURNING id
)
SELECT COUNT(*) AS updated_count FROM updated;
SQL

echo "[INFO] Preview of updated mappings:"
docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" "${POSTGRES_CONTAINER}" \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -P pager=off -c "
SELECT id, name, credentials->'model_mapping' AS model_mapping
FROM accounts
WHERE deleted_at IS NULL
  AND platform = 'openai'
ORDER BY id
LIMIT 5;
"

echo "[SUCCESS] OpenAI account model_mapping updated."
echo "[SUCCESS] Backup saved at: ${BACKUP_FILE}"
