declare -A pids
for tf in 1h 1d 1wk 1mo; do
  ( set -o pipefail
    uv run stock-data --config config/stock-data-$tf.toml update-all 2>&1 \
      | sed "s/^/[$tf] /" ) &
  pids[$tf]=$!
done

rc=0
for tf in "${!pids[@]}"; do
  if ! wait "${pids[$tf]}"; then
    echo "FAILED: $tf" >&2
    rc=1
  fi
done
exit $rc
