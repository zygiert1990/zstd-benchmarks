#!/usr/bin/env bash

set -Eeuo pipefail

# Every entry is one full `run-benchmarks.sh` invocation: a benchmark class name
# followed by zero or more `ZSTD_VERSION RESULT_NAME` pairs. Add new benchmarks here.
readonly -a BENCHMARK_RUNS=(
    "ZstdInputStreamNoFinalizerBenchmark 1.5.7-16-V2 ffm"
    "ZstdOutputStreamNoFinalizerBenchmark 1.5.7-16-FFM ffm 1.5.7-16-FFM-ARENA ffm-arena"
)

usage() {
    cat <<'EOF'
Usage:
  scripts/run-all-benchmarks.sh [OPTIONS]

Runs every invocation listed in BENCHMARK_RUNS (see the top of this script) through
scripts/run-benchmarks.sh, one after another.

Options:
  -n, --dry-run     Print the invocations without running them.
      --fail-fast   Stop at the first failing invocation (default: run all, report at the end).
  -h, --help        Show this help.
EOF
}

DRY_RUN=0
FAIL_FAST=0

while (( $# > 0 )); do
    case $1 in
        -n|--dry-run) DRY_RUN=1 ;;
        --fail-fast) FAIL_FAST=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Error: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

readonly DRY_RUN FAIL_FAST

readonly SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
readonly RUN_BENCHMARKS="$SCRIPT_DIR/run-benchmarks.sh"

if [[ ! -x $RUN_BENCHMARKS ]]; then
    echo "Error: run-benchmarks.sh is missing or not executable: $RUN_BENCHMARKS" >&2
    exit 1
fi
if (( ${#BENCHMARK_RUNS[@]} == 0 )); then
    echo "Error: BENCHMARK_RUNS is empty; nothing to run." >&2
    exit 2
fi

declare -a SUCCEEDED=()
declare -a FAILED=()

format_duration() {
    local seconds=$1
    printf '%02d:%02d:%02d' $(( seconds / 3600 )) $(( seconds % 3600 / 60 )) $(( seconds % 60 ))
}

suite_started_at=$SECONDS

for index in "${!BENCHMARK_RUNS[@]}"; do
    read -r -a run_arguments <<< "${BENCHMARK_RUNS[$index]}"
    benchmark=${run_arguments[0]}

    if (( DRY_RUN )); then
        printf '%s %s\n' "$RUN_BENCHMARKS" "${run_arguments[*]}"
        continue
    fi

    printf '\n========================================================================\n'
    printf '[%s] [run %d/%d] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$(( index + 1 ))" "${#BENCHMARK_RUNS[@]}" "${run_arguments[*]}"
    printf '========================================================================\n'

    run_started_at=$SECONDS
    status=0
    "$RUN_BENCHMARKS" "${run_arguments[@]}" || status=$?
    run_duration=$(( SECONDS - run_started_at ))

    if (( status == 0 )); then
        SUCCEEDED+=("$benchmark")
        printf '[%s] Completed %s in %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
            "$benchmark" "$(format_duration "$run_duration")"
    else
        FAILED+=("$benchmark (exit $status)")
        printf '[%s] FAILED %s after %s with exit code %d\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
            "$benchmark" "$(format_duration "$run_duration")" "$status" >&2
        if (( FAIL_FAST )); then
            break
        fi
    fi
done

if (( DRY_RUN )); then
    exit 0
fi

printf '\n========================================================================\n'
printf 'Suite finished in %s\n' "$(format_duration $(( SECONDS - suite_started_at )))"
printf 'Succeeded: %d\n' "${#SUCCEEDED[@]}"
for entry in "${SUCCEEDED[@]}"; do
    printf '  - %s\n' "$entry"
done
if (( ${#FAILED[@]} > 0 )); then
    printf 'Failed: %d\n' "${#FAILED[@]}"
    for entry in "${FAILED[@]}"; do
        printf '  - %s\n' "$entry"
    done
    exit 1
fi
