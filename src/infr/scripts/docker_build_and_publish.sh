#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

DOCKER_CONTEXT_DIR="${REPO_ROOT}/src/infr/containers/prod"
APP_BUILD_DIR="${DOCKER_CONTEXT_DIR}/app_build"
DOCKERFILE="${DOCKER_CONTEXT_DIR}/dockerfile-prod"
PYPROJECT_FILE="${REPO_ROOT}/pyproject.toml"
CHARTS_OUTPUT_DIR="${REPO_ROOT}/build/charts"
GATEWAY_CHART_DIR="${REPO_ROOT}/src/infr/charts/tcp-tunnel/charts/gateway"
BASTION_CHART_DIR="${REPO_ROOT}/src/infr/charts/tcp-tunnel/charts/bastion"

IMAGE_REPO="${IMAGE_REPO:-mginfn}"
IMAGE_NAME="${IMAGE_NAME:-interlink-kubernetes-plugin}"
IMAGE_VERSION="${IMAGE_VERSION:-}"
TAG_PROVIDED=false
PUSH_IMAGE=true
KEEP_BUILD_DIR=false
CREATE_CHART_ARCHIVES=false

log() {
    printf '[build-publish] %s\n' "$*"
}

die() {
    printf '[build-publish] ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: docker_build_and_publish.sh [options]

Options:
  --repo <repo>        Image repository namespace (default: mginfn)
  --name <name>        Image name (default: interlink-kubernetes-plugin)
  --tag <tag>          Image tag/version (prompts to sync pyproject.toml on mismatch)
  --no-push            Build image but skip push and latest tagging
  --create-chart-archives  Create deprecated tcp-tunnel chart archives (default: disabled)
  --keep-build-dir     Keep src/infr/containers/prod/app_build for debugging
  -h, --help           Show this help message
EOF
}

require_commands() {
    local cmd
    for cmd in "$@"; do
        command -v "${cmd}" >/dev/null 2>&1 || die "Missing required command: ${cmd}"
    done
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo)
                [[ $# -ge 2 ]] || die "Missing value for --repo"
                IMAGE_REPO="$2"
                shift 2
                ;;
            --name)
                [[ $# -ge 2 ]] || die "Missing value for --name"
                IMAGE_NAME="$2"
                shift 2
                ;;
            --tag)
                [[ $# -ge 2 ]] || die "Missing value for --tag"
                IMAGE_VERSION="$2"
                TAG_PROVIDED=true
                shift 2
                ;;
            --no-push)
                PUSH_IMAGE=false
                shift
                ;;
            --create-chart-archives)
                CREATE_CHART_ARCHIVES=true
                shift
                ;;
            --keep-build-dir)
                KEEP_BUILD_DIR=true
                shift
                ;;
            -h | --help)
                usage
                exit 0
                ;;
            *)
                usage
                die "Unknown argument: $1"
                ;;
        esac
    done
}

resolve_image_version() {
    [[ -f "${PYPROJECT_FILE}" ]] || die "Could not find ${PYPROJECT_FILE}"
    local pyproject_version
    pyproject_version="$(awk -F'"' '/^version = / {print $2; exit}' "${PYPROJECT_FILE}")"
    [[ -n "${pyproject_version}" ]] || die "Unable to read version from ${PYPROJECT_FILE}"

    if [[ "${TAG_PROVIDED}" != true ]]; then
        IMAGE_VERSION="${pyproject_version}"
        return
    fi

    if [[ "${IMAGE_VERSION}" == "${pyproject_version}" ]]; then
        return
    fi

    log "Version mismatch detected: --tag='${IMAGE_VERSION}' vs pyproject='${pyproject_version}'"

    local answer
    while true; do
        if ! read -r -p "[build-publish] Update ${PYPROJECT_FILE} version to '${IMAGE_VERSION}'? [y/N]: " answer; then
            die "No response received. Aborting due to version mismatch."
        fi
        case "${answer}" in
            [Yy] | [Yy][Ee][Ss])
                update_pyproject_version "${IMAGE_VERSION}"
                log "Updated ${PYPROJECT_FILE} to version '${IMAGE_VERSION}'."
                break
                ;;
            [Nn] | [Nn][Oo] | "")
                log "Keeping ${PYPROJECT_FILE} at version '${pyproject_version}'."
                break
                ;;
            *)
                log "Please answer yes or no."
                ;;
        esac
    done
}

update_pyproject_version() {
    local new_version="$1"
    local tmp_file="${PYPROJECT_FILE}.tmp.$$"

    awk -v new_version="${new_version}" '
        BEGIN {
            in_poetry = 0
            updated = 0
        }
        /^\[tool\.poetry\]/ {
            in_poetry = 1
            print
            next
        }
        /^\[/ {
            if ($0 !~ /^\[tool\.poetry\]/) {
                in_poetry = 0
            }
        }
        {
            if (in_poetry && !updated && $0 ~ /^version = "/) {
                print "version = \"" new_version "\""
                updated = 1
            } else {
                print
            }
        }
        END {
            if (!updated) {
                exit 1
            }
        }
    ' "${PYPROJECT_FILE}" >"${tmp_file}" || die "Failed to update version in ${PYPROJECT_FILE}"

    mv "${tmp_file}" "${PYPROJECT_FILE}"
}

prepare_build_context() {
    log "Preparing application build directory: ${APP_BUILD_DIR}"
    rm -rf "${APP_BUILD_DIR}"
    mkdir -p "${APP_BUILD_DIR}/infr" "${APP_BUILD_DIR}/private"

    cp -r "${REPO_ROOT}/src/app" "${APP_BUILD_DIR}/"
    cp "${REPO_ROOT}/src/main.py" "${APP_BUILD_DIR}/"
    cp -r "${REPO_ROOT}/src/infr/charts" "${APP_BUILD_DIR}/infr/"
    cp "${REPO_ROOT}/src/private/config.sample.ini" "${APP_BUILD_DIR}/private/"
}

export_requirements() {
    log "Exporting Python dependencies to ${DOCKER_CONTEXT_DIR}/requirements.txt"
    poetry export --without-hashes -f requirements.txt -o "${DOCKER_CONTEXT_DIR}/requirements.txt"
}

build_image() {
    local image_tag="$1"
    log "Building image: ${image_tag}"
    docker build "${DOCKER_CONTEXT_DIR}" -f "${DOCKERFILE}" -t "${image_tag}"
}

push_images() {
    local image_tag="$1"
    local latest_tag="$2"

    if [[ "${PUSH_IMAGE}" != true ]]; then
        log "Skipping push (--no-push enabled)."
        return
    fi

    log "Pushing image: ${image_tag}"
    docker push "${image_tag}"
    docker tag "${image_tag}" "${latest_tag}"
    docker push "${latest_tag}"
    log "Tagged latest image: ${latest_tag}"
}

create_chart_archives() {
    local image_version="$1"
    local gateway_archive="${CHARTS_OUTPUT_DIR}/tcp-tunnel-gateway-v${image_version}.tar.gz"
    local bastion_archive="${CHARTS_OUTPUT_DIR}/tcp-tunnel-bastion-v${image_version}.tar.gz"

    mkdir -p "${CHARTS_OUTPUT_DIR}"
    [[ -d "${GATEWAY_CHART_DIR}" ]] || die "Gateway chart directory not found: ${GATEWAY_CHART_DIR}"
    [[ -d "${BASTION_CHART_DIR}" ]] || die "Bastion chart directory not found: ${BASTION_CHART_DIR}"

    log "Creating Helm chart archive: $(basename "${gateway_archive}")"
    tar -czf "${gateway_archive}" -C "${GATEWAY_CHART_DIR}" .

    log "Creating Helm chart archive: $(basename "${bastion_archive}")"
    tar -czf "${bastion_archive}" -C "${BASTION_CHART_DIR}" .
}

maybe_create_chart_archives() {
    local image_version="$1"

    if [[ "${CREATE_CHART_ARCHIVES}" != true ]]; then
        log "Skipping deprecated Helm chart archives (enable with --create-chart-archives)."
        return
    fi

    create_chart_archives "${image_version}"
}

print_run_hints() {
    local image_tag="$1"
    log "Run with (socket mode): docker run --rm -v ${REPO_ROOT}/src/private:/interlink-kubernetes-plugin/private -v ${REPO_ROOT}/.devcontainer/sockets:/root/sockets -e APP_SOCKET_ADDRESS=unix:///root/sockets/.plugin.sock ${image_tag}"
    log "Run with (tcp mode): docker run --rm -v ${REPO_ROOT}/src/private:/interlink-kubernetes-plugin/private -e APP_SOCKET_ADDRESS=http://0.0.0.0 -e APP_SOCKET_PORT=4000 -p 30400:4000 ${image_tag}"
}

cleanup() {
    if [[ "${KEEP_BUILD_DIR}" == true ]]; then
        log "Keeping application build directory: ${APP_BUILD_DIR}"
        return
    fi

    rm -rf "${APP_BUILD_DIR}"
}

main() {
    parse_args "$@"
    require_commands awk mv
    resolve_image_version
    require_commands cp docker mkdir poetry rm
    if [[ "${CREATE_CHART_ARCHIVES}" == true ]]; then
        require_commands tar
    fi

    local image_tag="${IMAGE_REPO}/${IMAGE_NAME}:${IMAGE_VERSION}"
    local latest_tag="${IMAGE_REPO}/${IMAGE_NAME}:latest"

    log "Repository root: ${REPO_ROOT}"
    log "Docker context: ${DOCKER_CONTEXT_DIR}"
    log "Image: ${image_tag}"

    trap cleanup EXIT

    prepare_build_context
    export_requirements
    build_image "${image_tag}"
    push_images "${image_tag}" "${latest_tag}"
    maybe_create_chart_archives "${IMAGE_VERSION}"
    print_run_hints "${image_tag}"
    log "Done."
}

main "$@"
