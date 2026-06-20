#!/usr/bin/env bash
# Claude Code statusLine command
# Mirrors the devcontainers bash PS1 from ~/.bashrc

input=$(cat)

cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd')

# User part: prefer GITHUB_USER env var, else whoami
if [ -n "${GITHUB_USER:-}" ]; then
    user_label="@${GITHUB_USER}"
else
    user_label="$(whoami)"
fi

user_display=$(printf '\033[0;32m%s\033[0m \033[0m➜' "$user_label")

# Working directory in light blue
dir_display=$(printf '\033[1;34m%s\033[0m' "$cwd")

# Git branch display, matching devcontainers theme logic
git_display=""
if git -C "$cwd" rev-parse --git-dir > /dev/null 2>&1; then
    hide_status=$(git -C "$cwd" --no-optional-locks config --get devcontainers-theme.hide-status 2>/dev/null)
    hide_codespaces=$(git -C "$cwd" --no-optional-locks config --get codespaces-theme.hide-status 2>/dev/null)
    if [ "$hide_status" != "1" ] && [ "$hide_codespaces" != "1" ]; then
        branch=$(git -C "$cwd" --no-optional-locks symbolic-ref --short HEAD 2>/dev/null \
            || git -C "$cwd" --no-optional-locks rev-parse --short HEAD 2>/dev/null)
        if [ -n "$branch" ]; then
            git_display=$(printf '\033[0;36m(\033[1;31m%s' "$branch")
            show_dirty=$(git -C "$cwd" --no-optional-locks config --get devcontainers-theme.show-dirty 2>/dev/null)
            if [ "$show_dirty" = "1" ]; then
                if git -C "$cwd" --no-optional-locks ls-files \
                    --error-unmatch -m --directory --no-empty-directory \
                    -o --exclude-standard ":/*" > /dev/null 2>&1; then
                    git_display="${git_display}$(printf ' \033[1;33m✗')"
                fi
            fi
            git_display="${git_display}$(printf '\033[0;36m)\033[0m')"
        fi
    fi
fi

# Model display
model_display=""
model_name=$(echo "$input" | jq -r '.model.display_name // empty')
if [ -n "$model_name" ]; then
    model_display=$(printf '\033[0;35m[%s]\033[0m' "$model_name")
fi

# Effort level display
effort_display=""
effort_level=$(echo "$input" | jq -r '.effort.level // empty')
if [ -n "$effort_level" ]; then
    effort_display=$(printf '\033[0;36m[effort: %s]\033[0m' "$effort_level")
fi

# Context window usage and size
context_display=""
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
ctx_size=$(echo "$input" | jq -r '.context_window.context_window_size // empty')
used_tokens=$(echo "$input" | jq -r '.context_window.total_input_tokens // empty')
if [ -n "$used_pct" ] && [ -n "$ctx_size" ] && [ -n "$used_tokens" ]; then
    ctx_k=$(echo "$ctx_size" | awk '{printf "%.0fk", $1/1000}')
    used_k=$(echo "$used_tokens" | awk '{printf "%.0fk", $1/1000}')
    context_display=$(printf '\033[0;33m[ctx: %s/%s %.0f%%]\033[0m' "$used_k" "$ctx_k" "$used_pct")
elif [ -n "$used_pct" ]; then
    context_display=$(printf '\033[0;33m[ctx: %.0f%% used]\033[0m' "$used_pct")
fi

# Rate limits display with reset times
rate_display=""
five_h=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
five_h_reset=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
seven_d=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
seven_d_reset=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')
if [ -n "$five_h" ] || [ -n "$seven_d" ]; then
    rate_parts=""
    if [ -n "$five_h" ]; then
        five_h_str="5h:$(printf '%.0f' "$five_h")%"
        if [ -n "$five_h_reset" ]; then
            reset_fmt=$(TZ=Asia/Kolkata date -d "@${five_h_reset}" '+%H:%M' 2>/dev/null \
                || TZ=Asia/Kolkata date -r "${five_h_reset}" '+%H:%M' 2>/dev/null)
            [ -n "$reset_fmt" ] && five_h_str="${five_h_str}(${reset_fmt})"
        fi
        rate_parts="$five_h_str"
    fi
    if [ -n "$seven_d" ]; then
        seven_d_str="7d:$(printf '%.0f' "$seven_d")%"
        if [ -n "$seven_d_reset" ]; then
            reset_fmt=$(TZ=Asia/Kolkata date -d "@${seven_d_reset}" '+%a %H:%M' 2>/dev/null \
                || TZ=Asia/Kolkata date -r "${seven_d_reset}" '+%a %H:%M' 2>/dev/null)
            [ -n "$reset_fmt" ] && seven_d_str="${seven_d_str}(${reset_fmt})"
        fi
        rate_parts="$rate_parts $seven_d_str"
    fi
    rate_display=$(printf '\033[0;31m[%s]\033[0m' "$(echo "$rate_parts" | xargs)")
fi

# Assemble the status line
parts="$user_display $dir_display"
[ -n "$git_display" ] && parts="$parts $git_display"
[ -n "$model_display" ] && parts="$parts $model_display"
[ -n "$effort_display" ] && parts="$parts $effort_display"
[ -n "$context_display" ] && parts="$parts $context_display"
[ -n "$rate_display" ] && parts="$parts $rate_display"

printf '%s' "$parts"
