#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/run-benchmarks.sh [--mode MODE] BENCHMARK [ZSTD_VERSION RESULT_NAME]...

Example:
  scripts/run-benchmarks.sh ZstdInputStreamNoFinalizerBenchmark \
    1.5.7-16-V1 ffm \
    1.5.7-16-V2-GCC ffm-gcc

The 1.5.7-16-LOCAL artifact is always run under the name "orig".

Modes:
  ALL         Replace and regenerate all benchmark artifacts (default).
  GC          Replace only results.txt files.
  NATIVEMEM   Replace only native-memory summaries and their JMH result files.
  FLAMEGRAPH  Replace only CPU flamegraphs.
EOF
}

MODE=ALL
while (( $# > 0 )); do
    case $1 in
        --mode)
            if (( $# < 2 )); then
                echo "Error: --mode requires a value." >&2
                usage >&2
                exit 2
            fi
            MODE=${2^^}
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "Error: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
        *) break ;;
    esac
done

if [[ ! $MODE =~ ^(ALL|GC|NATIVEMEM|FLAMEGRAPH)$ ]]; then
    echo "Error: mode must be ALL, GC, NATIVEMEM, or FLAMEGRAPH: $MODE" >&2
    exit 2
fi
readonly MODE

if (( $# == 0 )); then
    usage
    exit 2
fi

if (( $# % 2 == 0 )); then
    echo "Error: expected 1, 3, 5, ... arguments (a benchmark followed by version/name pairs)." >&2
    usage >&2
    exit 2
fi

BENCHMARK=$1
shift

if [[ ! $BENCHMARK =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "Error: benchmark must be a simple Java class name." >&2
    exit 2
fi

readonly PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
readonly POM="$PROJECT_DIR/pom.xml"
readonly BENCHMARK_JAR="$PROJECT_DIR/target/benchmarks.jar"
readonly RESULT_DIR="$PROJECT_DIR/docs/$BENCHMARK"
readonly DEFAULT_JAVA=${DEFAULT_JAVA:-${JAVA_25:-$HOME/.sdkman/candidates/java/25.0.2-tem/bin/java}}
readonly JAVA_11=${JAVA_11:-$HOME/.sdkman/candidates/java/11.0.32-amzn/bin/java}
readonly ASYNC_PROFILER_LIB=${ASYNC_PROFILER_LIB:-$HOME/tools/async-profiler-4.5-linux-x64/lib/libasyncProfiler.so}
readonly JAVA_DEFAULT_DIR=${JAVA_DEFAULT_DIR:-jdk-25-0-2-tem}
readonly JAVA_11_DIR=${JAVA_11_DIR:-jdk-11-0-32-amzn}
readonly -a CHUNK_SIZES=(1 8 64 512 4096 16384 65536)

declare -a VERSIONS=("1.5.7-16-LOCAL")
declare -a RESULT_NAMES=("orig")
declare -A SEEN_NAMES=([orig]=1)

while (( $# > 0 )); do
    version=$1
    result_name=$2
    shift 2

    if [[ ! $version =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
        echo "Error: invalid Maven version: $version" >&2
        exit 2
    fi
    if [[ ! $result_name =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
        echo "Error: invalid result name: $result_name" >&2
        exit 2
    fi
    if [[ -n ${SEEN_NAMES[$result_name]+x} ]]; then
        echo "Error: duplicate result name: $result_name" >&2
        exit 2
    fi

    VERSIONS+=("$version")
    RESULT_NAMES+=("$result_name")
    SEEN_NAMES["$result_name"]=1
done

TASKS_PER_TARGET=0
[[ $MODE == ALL || $MODE == GC ]] && TASKS_PER_TARGET=$((TASKS_PER_TARGET + 1))
[[ $MODE == ALL || $MODE == NATIVEMEM ]] && TASKS_PER_TARGET=$((TASKS_PER_TARGET + ${#CHUNK_SIZES[@]}))
[[ $MODE == ALL || $MODE == FLAMEGRAPH ]] && TASKS_PER_TARGET=$((TASKS_PER_TARGET + ${#CHUNK_SIZES[@]}))
readonly TASKS_PER_TARGET
readonly TOTAL_STEPS=$(( ${#VERSIONS[@]} + TASKS_PER_TARGET * (${#VERSIONS[@]} + 1) ))
CURRENT_STEP=0

announce() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    printf '\n[%s] [%d/%d] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$CURRENT_STEP" "$TOTAL_STEPS" "$1"
}

completed() {
    printf '[%s] Completed: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

run_inhibited() {
    gnome-session-inhibit --inhibit idle:suspend --reason "Running JMH" "$@"
}

for command in mvn gnome-session-inhibit "$DEFAULT_JAVA"; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Error: required command is unavailable: $command" >&2
        exit 1
    fi
done

if [[ ! -x $JAVA_11 ]]; then
    echo "Error: Java 11 executable is unavailable: $JAVA_11" >&2
    exit 1
fi
if [[ $MODE != GC && ! -f $ASYNC_PROFILER_LIB ]]; then
    echo "Error: async-profiler library is unavailable: $ASYNC_PROFILER_LIB" >&2
    exit 1
fi
if [[ ! -f $PROJECT_DIR/src/main/java/org/zygiert/$BENCHMARK.java ]]; then
    echo "Error: benchmark source does not exist: src/main/java/org/zygiert/$BENCHMARK.java" >&2
    exit 1
fi

for version in "${VERSIONS[@]}"; do
    artifact="$HOME/.m2/repository/com/github/luben/zstd-jni/$version/zstd-jni-$version.jar"
    if [[ ! -f $artifact ]]; then
        echo "Error: zstd-jni artifact is not installed locally: $artifact" >&2
        exit 1
    fi
done

pom_backup=$(mktemp)
cp -- "$POM" "$pom_backup"
restore_pom() {
    cp -- "$pom_backup" "$POM"
    rm -f -- "$pom_backup"
}
trap restore_pom EXIT

set_zstd_version() {
    local version=$1
    local updated_pom
    updated_pom=$(mktemp "$PROJECT_DIR/.pom.xml.XXXXXX")

    awk -v version="$version" '
        /<artifactId>zstd-jni<\/artifactId>/ { zstd_dependency = 1 }
        zstd_dependency && /<version>[^<]+<\/version>/ {
            sub(/>[^<]+</, ">" version "<")
            zstd_dependency = 0
            replaced = 1
        }
        { print }
        END { if (!replaced) exit 1 }
    ' "$POM" > "$updated_pom"
    mv -- "$updated_pom" "$POM"
}

find_throughput_benchmark() {
    local benchmark_method
    mapfile -t matching_methods < <(
        "$DEFAULT_JAVA" -jar "$BENCHMARK_JAR" -l 2>/dev/null |
            awk -v benchmark="$BENCHMARK" '$0 ~ ("\\." benchmark "\\.[^.]*Throughput$") { print }'
    )
    if (( ${#matching_methods[@]} != 1 )); then
        echo "Error: expected exactly one *Throughput method for $BENCHMARK; found ${#matching_methods[@]}." >&2
        exit 1
    fi
    benchmark_method=${matching_methods[0]}
    printf '%s\n' "$benchmark_method"
}

run_profiled_benchmarks() {
    local result_name=$1
    local java_dir=$2
    local jvm=$3
    local destination="$RESULT_DIR/$java_dir/$result_name"
    local chunk_size
    local -a jvm_option=()
    local -a flamegraphs=()

    if [[ -n $jvm ]]; then
        jvm_option=(-jvm "$jvm")
    fi

    mkdir -p -- "$destination"

    if [[ $MODE == ALL || $MODE == GC ]]; then
        rm -f -- "$destination/results.txt"
        announce "$result_name on $java_dir: GC benchmark"
        run_inhibited "$DEFAULT_JAVA" -jar "$BENCHMARK_JAR" "$BENCHMARK" -prof gc \
            -rf text -rff "$destination/results.txt" "${jvm_option[@]}"
        completed "$result_name on $java_dir: GC benchmark"
    fi

    if [[ $MODE == ALL || $MODE == NATIVEMEM ]]; then
        for chunk_size in "${CHUNK_SIZES[@]}"; do
            local native_profiler_dir="$PROJECT_DIR/target/async-profiler-native-$result_name-$java_dir-$chunk_size"
            local chunk_destination="$destination/chunk-$chunk_size"
            local native_raw_output
            native_raw_output=$(mktemp)
            rm -rf -- "$native_profiler_dir"
            mkdir -p -- "$chunk_destination"
            rm -f -- "$chunk_destination/summary-nativemem.txt" \
                "$chunk_destination/results-nativemem.json"

            announce "$result_name on $java_dir: native-memory profile (chunk $chunk_size)"
            run_inhibited "$DEFAULT_JAVA" -jar "$BENCHMARK_JAR" "$THROUGHPUT_BENCHMARK" \
                -p "chunkSize=$chunk_size" \
                -prof "async:libPath=$ASYNC_PROFILER_LIB;event=nativemem;output=text;dir=$native_profiler_dir" \
                -f 1 -wi 3 -i 3 -rf json -rff "$chunk_destination/results-nativemem.json" \
                "${jvm_option[@]}" \
                > "$native_raw_output" 2>&1
            awk '
            /^[[:space:]]+bytes[[:space:]]+percent[[:space:]]+samples[[:space:]]+top[[:space:]]*$/ {
                capture = 1
                print
                next
            }
            capture && /^[[:space:]]*-+[[:space:]]+-+[[:space:]]+-+[[:space:]]+-+[[:space:]]*$/ {
                print
                next
            }
            capture && /^[[:space:]]*[0-9]+[[:space:]]+[0-9.]+%[[:space:]]+[0-9]+[[:space:]]+/ {
                print
                next
            }
            capture { exit }
            ' "$native_raw_output" > "$chunk_destination/summary-nativemem.txt"
            if [[ ! -s "$chunk_destination/summary-nativemem.txt" ]]; then
                echo "Error: native-memory summary footer was not found for chunk $chunk_size." >&2
                exit 1
            fi
            if [[ ! -s "$chunk_destination/results-nativemem.json" ]]; then
                echo "Error: native-memory JMH result was not written for chunk $chunk_size." >&2
                exit 1
            fi
            rm -f -- "$native_raw_output"
            rm -rf -- "$native_profiler_dir"
            completed "$result_name on $java_dir: native-memory profile (chunk $chunk_size); details saved to chunk-$chunk_size"
        done
    fi

    if [[ $MODE == ALL || $MODE == FLAMEGRAPH ]]; then
        for chunk_size in "${CHUNK_SIZES[@]}"; do
            local profiler_dir="$PROJECT_DIR/target/async-profiler-$result_name-$java_dir-$chunk_size"
            local flamegraph_destination="$destination/chunk-$chunk_size"
            local flamegraph
            rm -rf -- "$profiler_dir"
            mkdir -p -- "$flamegraph_destination"
            rm -f -- "$flamegraph_destination/flame-cpu-forward.html"

            announce "$result_name on $java_dir: CPU flamegraph (chunk $chunk_size)"
            run_inhibited "$DEFAULT_JAVA" -jar "$BENCHMARK_JAR" "$THROUGHPUT_BENCHMARK" \
                -p "chunkSize=$chunk_size" \
                -prof "async:libPath=$ASYNC_PROFILER_LIB;event=cpu;output=flamegraph;direction=forward;dir=$profiler_dir" \
                "${jvm_option[@]}"

            mapfile -t flamegraphs < <(find "$profiler_dir" -type f -name '*.html' -print)
            if (( ${#flamegraphs[@]} != 1 )); then
                echo "Error: expected one flamegraph for chunk $chunk_size; found ${#flamegraphs[@]}." >&2
                exit 1
            fi
            flamegraph=${flamegraphs[0]}
            cp -- "$flamegraph" "$flamegraph_destination/flame-cpu-forward.html"
            rm -rf -- "$profiler_dir"
            completed "$result_name on $java_dir: CPU flamegraph (chunk $chunk_size)"
        done
    fi
}

if [[ $MODE == ALL ]]; then
    rm -rf -- "$RESULT_DIR"
    mkdir -p -- "$RESULT_DIR"
elif [[ ! -f $RESULT_DIR/readme.md ]]; then
    echo "Error: partial mode requires an existing benchmark directory with readme.md: $RESULT_DIR" >&2
    exit 1
fi

echo "JDK 11: $JAVA_11"
echo "Default JDK: $DEFAULT_JAVA"
echo "async-profiler: $ASYNC_PROFILER_LIB"
echo "Result directory: $RESULT_DIR"
echo "Mode: $MODE"

if [[ $MODE == ALL ]]; then
    dataset_size=$(wc -c < "$PROJECT_DIR/src/main/resources/dataset-formatted.xml")
    {
        printf '`orig` results use local artifact `1.5.7-16-LOCAL`.\n\n'
        for index in "${!VERSIONS[@]}"; do
            if (( index == 0 )); then
                continue
            fi
            printf '`%s` results use artifact `%s` built from branch: [<FILL IN REMOTE BRANCH>](<FILL IN REMOTE BRANCH URL>)\n\n' \
                "${RESULT_NAMES[$index]}" "${VERSIONS[$index]}"
        done
        printf 'Test dataset has `%s bytes`.\n' "$dataset_size"
    } > "$RESULT_DIR/readme.md"
fi

for index in "${!VERSIONS[@]}"; do
    version=${VERSIONS[$index]}
    result_name=${RESULT_NAMES[$index]}

    announce "building benchmark jar with zstd-jni $version ($result_name)"
    set_zstd_version "$version"
    (cd "$PROJECT_DIR" && mvn clean package)
    completed "benchmark jar with zstd-jni $version ($result_name)"
    if [[ $MODE != GC ]]; then
        THROUGHPUT_BENCHMARK=$(find_throughput_benchmark)
    fi

    run_profiled_benchmarks "$result_name" "$JAVA_DEFAULT_DIR" ""
    if [[ $result_name == orig ]]; then
        run_profiled_benchmarks "$result_name" "$JAVA_11_DIR" "$JAVA_11"
    fi
done

echo
echo "Benchmark results written to: $RESULT_DIR"
if [[ $MODE == ALL ]] && (( ${#VERSIONS[@]} > 1 )); then
    echo "Please replace every remote-branch placeholder in $RESULT_DIR/readme.md."
fi
