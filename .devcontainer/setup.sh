#!/bin/bash

# Exit on error (but allow grep to fail)
set -e
set +o pipefail

# Target home directory for installation (use vscode user's home)
TARGET_HOME="/root"

# Create log file
LOG_FILE="/root/setup-log.txt"
if [ ! -d "/root" ]; then
    LOG_FILE="/tmp/setup-log.txt"
fi


# Simple logging function
log() {
    echo "  → $*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   → $*" >> "$LOG_FILE" 2>/dev/null || true
}

# Log file operations with source and target
log_file_op() {
    local operation="$1"
    local source="$2"
    local target="$3"
    echo "  [$operation] Source: $source"
    echo "                Target: $target"
    echo "  [$operation] Source: $source → Target: $target" >> "$LOG_FILE" 2>/dev/null || true
}

log "========================================"
log "Starting development setup..."
log "========================================"
log "Script execution started at: $(date '+%Y-%m-%d %H:%M:%S')"
log "User: $(whoami)"
log "Home directory: $HOME"
log "Current directory: $(pwd)"
log "Log file location: $LOG_FILE"

# Clone the repository
REPO_URL="https://github.com/rajvermacas/development-setup.git"
TEMP_DIR="/tmp/development-setup"

log ""
log "=== STEP 1: Repository Cloning ==="
log "Repository URL: $REPO_URL"
log "Temporary clone directory: $TEMP_DIR"

# Remove existing temp directory if it exists
if [ -d "$TEMP_DIR" ]; then
    log "Found existing directory at $TEMP_DIR"
    log "Removing existing directory..."
    rm -rf "$TEMP_DIR" 2>/dev/null || true
    log "Directory removed successfully"
else
    log "No existing directory found at $TEMP_DIR"
fi

# Clone the repository
log "Starting git clone operation..."
log "Command: git clone $REPO_URL $TEMP_DIR"
if git clone "$REPO_URL" "$TEMP_DIR" 2>/dev/null; then
    log "✓ Repository cloned successfully"
    log "Clone completed at: $(date '+%H:%M:%S')"
    log "Repository size: $(du -sh "$TEMP_DIR" 2>/dev/null | cut -f1)"
    REPO_AVAILABLE=true
else
    log "✗ Failed to clone repository"
    log "Clone failed at: $(date '+%H:%M:%S')"
    log "Continuing setup without repository files..."
    REPO_AVAILABLE=false
fi

# Create target directories
log ""
log "=== STEP 2: Creating Target Directories ==="
log "Preparing to create directory structure..."

# Claude directories
log "Creating Claude directories..."
TARGET_DIR="$TARGET_HOME/.claude"
log "Main Claude directory: $TARGET_DIR"
mkdir -p "$TARGET_DIR"
log "Created: $TARGET_DIR"

for subdir in agents commands output-styles skills; do
    FULL_PATH="$TARGET_DIR/$subdir"
    log "Creating subdirectory: $FULL_PATH"
    mkdir -p "$FULL_PATH"
    log "✓ Created: $FULL_PATH"
done

# Codex directories
log "Creating Codex directories..."
TARGET_DIR="$TARGET_HOME/.codex"
log "Main Codex directory: $TARGET_DIR"
mkdir -p "$TARGET_DIR"
log "Created: $TARGET_DIR"

for subdir in commands skills; do
    FULL_PATH="$TARGET_DIR/$subdir"
    log "Creating subdirectory: $FULL_PATH"
    mkdir -p "$FULL_PATH"
    log "✓ Created: $FULL_PATH"
done

# Gemini directories
log "Creating Gemini directories..."
TARGET_DIR="$TARGET_HOME/.gemini/commands"
log "Target: $TARGET_DIR"
mkdir -p "$TARGET_DIR"
log "✓ Created: $TARGET_DIR"

# Project templates directory
log "Creating project templates directory..."
TARGET_DIR="$TARGET_HOME/projects/claude-code-templates"
log "Target: $TARGET_DIR"
mkdir -p "$TARGET_DIR"
log "✓ Created: $TARGET_DIR"

# User directory for VSCode settings
log "Creating User directory for VSCode settings..."
TARGET_DIR="$TARGET_HOME/User"
log "Target: $TARGET_DIR"
mkdir -p "$TARGET_DIR"
log "✓ Created: $TARGET_DIR"

log "✓ All directories created successfully"


# Copy configuration files
if [ "$REPO_AVAILABLE" = true ]; then
    log ""
    log "=== STEP 3: Copying Configuration Files ==="

    # Ensure target home directory exists
    if [ ! -d "$TARGET_HOME" ]; then
        log "Creating target home directory: $TARGET_HOME"
        mkdir -p "$TARGET_HOME"
    fi

    # Check if we can write to the target directory
    if [ ! -w "$TARGET_HOME" ]; then
        log "Warning: Cannot write to $TARGET_HOME"
        log "Error: No write access to $TARGET_HOME"
        exit 1
    fi

    log "Starting file copy operations..."
    log "Source base directory: $TEMP_DIR"

    # Copy Claude agents
    log ""
    log "Processing Claude agents..."
    SOURCE_DIR="$TEMP_DIR/.claude/agents"
    TARGET_DIR="$TARGET_HOME/.claude/agents"
    if [ -d "$SOURCE_DIR" ]; then
        log "Found agents directory at: $SOURCE_DIR"
        log "Listing agent files to copy:"
        for file in "$SOURCE_DIR"/*; do
            if [ -f "$file" ]; then
                filename=$(basename "$file")
                log "  - $filename"
                log_file_op "COPY" "$file" "$TARGET_DIR/$filename"
                cp "$file" "$TARGET_DIR/" 2>/dev/null || log "    Warning: Failed to copy $filename"
            fi
        done
        log "✓ Copied Claude agents"
    else
        log "No agents directory found at: $SOURCE_DIR"
    fi

    # Copy Claude commands
    log ""
    log "Processing Claude commands..."
    SOURCE_DIR="$TEMP_DIR/.claude/commands"
    TARGET_DIR="$TARGET_HOME/.claude/commands"
    if [ -d "$SOURCE_DIR" ]; then
        log "Found commands directory at: $SOURCE_DIR"
        log "Listing command files to copy:"
        for file in "$SOURCE_DIR"/*; do
            if [ -f "$file" ]; then
                filename=$(basename "$file")
                log "  - $filename"
                log_file_op "COPY" "$file" "$TARGET_DIR/$filename"
                cp "$file" "$TARGET_DIR/" 2>/dev/null || log "    Warning: Failed to copy $filename"
            fi
        done
        log "✓ Copied Claude commands"
    else
        log "No commands directory found at: $SOURCE_DIR"
    fi

    # Copy output-styles
    log ""
    log "Processing output-styles..."
    SOURCE_DIR="$TEMP_DIR/.claude/output-styles"
    TARGET_DIR="$TARGET_HOME/.claude/output-styles"
    if [ -d "$SOURCE_DIR" ]; then
        log "Found output-styles directory at: $SOURCE_DIR"
        log "Listing style files to copy:"
        for file in "$SOURCE_DIR"/*; do
            if [ -f "$file" ]; then
                filename=$(basename "$file")
                log "  - $filename"
                log_file_op "COPY" "$file" "$TARGET_DIR/$filename"
                cp "$file" "$TARGET_DIR/" 2>/dev/null || log "    Warning: Failed to copy $filename"
            fi
        done
        log "✓ Copied output-styles"
    else
        log "No output-styles directory found at: $SOURCE_DIR"
    fi

    # Copy Claude config files
    log ""
    log "Processing Claude configuration files..."

    # CLAUDE.md
    SOURCE_FILE="$TEMP_DIR/.claude/CLAUDE.md"
    TARGET_FILE="$TARGET_HOME/.claude/CLAUDE.md"
    if [ -f "$SOURCE_FILE" ]; then
        log_file_op "COPY" "$SOURCE_FILE" "$TARGET_FILE"
        cp "$SOURCE_FILE" "$TARGET_FILE"
        log "✓ Copied CLAUDE.md"
    else
        log "CLAUDE.md not found at: $SOURCE_FILE"
    fi

    # settings.json
    SOURCE_FILE="$TEMP_DIR/.claude/settings.json"
    TARGET_FILE="$TARGET_HOME/.claude/settings.json"
    if [ -f "$SOURCE_FILE" ]; then
        log_file_op "COPY" "$SOURCE_FILE" "$TARGET_FILE"
        cp "$SOURCE_FILE" "$TARGET_FILE"
        log "✓ Copied settings.json"
    else
        log "settings.json not found at: $SOURCE_FILE"
    fi

    # Copy templates
    log ""
    log "Processing Claude code templates..."
    SOURCE_FILE="$TEMP_DIR/claude-code-templates/session-scratchpad-template.md"
    TARGET_FILE="$TARGET_HOME/projects/claude-code-templates/session-scratchpad-template.md"
    if [ -f "$SOURCE_FILE" ]; then
        log_file_op "COPY" "$SOURCE_FILE" "$TARGET_FILE"
        cp "$SOURCE_FILE" "$TARGET_FILE"
        log "✓ Copied templates"
    else
        log "Template not found at: $SOURCE_FILE"
    fi

    # Copy VSCode keybindings
    log ""
    log "Processing VSCode keybindings..."
    SOURCE_FILE="$TEMP_DIR/.vscode/keybindings.json"
    TARGET_FILE="$TARGET_HOME/User/keybindings.json"
    if [ -f "$SOURCE_FILE" ]; then
        log_file_op "COPY" "$SOURCE_FILE" "$TARGET_FILE"
        cp "$SOURCE_FILE" "$TARGET_FILE"
        log "✓ Copied VSCode keybindings"
    else
        log "VSCode keybindings not found at: $SOURCE_FILE"
    fi

    # Copy Gemini files
    log ""
    log "Processing Gemini configuration..."
    if [ -d "$TEMP_DIR/.gemini" ]; then
        log "Found Gemini directory"

        # GEMINI.md
        SOURCE_FILE="$TEMP_DIR/.gemini/GEMINI.md"
        TARGET_FILE="$TARGET_HOME/.gemini/GEMINI.md"
        if [ -f "$SOURCE_FILE" ]; then
            log_file_op "COPY" "$SOURCE_FILE" "$TARGET_FILE"
            cp "$SOURCE_FILE" "$TARGET_FILE"
            log "✓ Copied GEMINI.md"
        else
            log "GEMINI.md not found at: $SOURCE_FILE"
        fi

        # git-commit.toml
        SOURCE_FILE="$TEMP_DIR/.gemini/commands/git-commit.toml"
        TARGET_FILE="$TARGET_HOME/.gemini/commands/git-commit.toml"
        if [ -f "$SOURCE_FILE" ]; then
            log_file_op "COPY" "$SOURCE_FILE" "$TARGET_FILE"
            cp "$SOURCE_FILE" "$TARGET_FILE"
            log "✓ Copied git-commit.toml"
        else
            log "git-commit.toml not found at: $SOURCE_FILE"
        fi

        log "✓ Copied Gemini config"
    else
        log "No Gemini directory found at: $TEMP_DIR/.gemini"
    fi

    # Copy skills directory
    log ""
    log "Processing Claude skills..."
    SOURCE_DIR="$TEMP_DIR/.claude/skills"
    TARGET_DIR="$TARGET_HOME/.claude/skills"
    if [ -d "$SOURCE_DIR" ]; then
        log "Found skills directory at: $SOURCE_DIR"
        # Enable dotglob to include hidden files in glob expansion
        shopt -s dotglob
        cp -r "$SOURCE_DIR"/* "$TARGET_DIR/" 2>/dev/null || true
        shopt -u dotglob
        # Make all Python scripts executable
        find "$TARGET_DIR" -name "*.py" -type f -exec chmod +x {} \;
        log "✓ Copied skills directory with $(find "$TARGET_DIR" -name "*.py" | wc -l) Python scripts"
    else
        log "⚠ No skills directory found at: $SOURCE_DIR"
    fi

    # Copy Codex configuration files
    log ""
    log "Processing Codex configuration..."
    if [ -d "$TEMP_DIR/.codex" ]; then
        log "Found Codex directory"

        # AGENTS.md
        SOURCE_FILE="$TEMP_DIR/.codex/AGENTS.md"
        TARGET_FILE="$TARGET_HOME/.codex/AGENTS.md"
        if [ -f "$SOURCE_FILE" ]; then
            log_file_op "COPY" "$SOURCE_FILE" "$TARGET_FILE"
            cp "$SOURCE_FILE" "$TARGET_FILE"
            log "✓ Copied AGENTS.md"
        else
            log "AGENTS.md not found at: $SOURCE_FILE"
        fi

        # Codex commands
        log ""
        log "Processing Codex commands..."
        SOURCE_DIR="$TEMP_DIR/.codex/commands"
        TARGET_DIR="$TARGET_HOME/.codex/commands"
        if [ -d "$SOURCE_DIR" ]; then
            log "Found Codex commands directory at: $SOURCE_DIR"
            log "Listing command files to copy:"
            for file in "$SOURCE_DIR"/*; do
                if [ -f "$file" ]; then
                    filename=$(basename "$file")
                    log "  - $filename"
                    log_file_op "COPY" "$file" "$TARGET_DIR/$filename"
                    cp "$file" "$TARGET_DIR/" 2>/dev/null || log "    Warning: Failed to copy $filename"
                fi
            done
            log "✓ Copied Codex commands"
        else
            log "No Codex commands directory found at: $SOURCE_DIR"
        fi

        # Codex skills
        log ""
        log "Processing Codex skills..."
        SOURCE_DIR="$TEMP_DIR/.codex/skills"
        TARGET_DIR="$TARGET_HOME/.codex/skills"
        if [ -d "$SOURCE_DIR" ]; then
            log "Found Codex skills directory at: $SOURCE_DIR"
            shopt -s dotglob
            cp -r "$SOURCE_DIR"/* "$TARGET_DIR/" 2>/dev/null || true
            shopt -u dotglob
            # Make all shell scripts executable
            find "$TARGET_DIR" -name "*.sh" -type f -exec chmod +x {} \;
            log "✓ Copied Codex skills directory with $(find "$TARGET_DIR" -type f | wc -l) files"
        else
            log "⚠ No Codex skills directory found at: $SOURCE_DIR"
        fi

        # Codex superpower skill
        log ""
        log "Processing Codex superpower skill..."
        if [ -d "$TARGET_HOME/.codex/superpowers" ]; then
            log "Superpowers directory already exists, pulling latest..."
            if git -C "$TARGET_HOME/.codex/superpowers" pull 2>/dev/null; then
                log "✓ Updated superpowers repository"
            else
                log "⚠ Failed to update superpowers repository"
            fi
        else
            if git clone https://github.com/obra/superpowers.git "$TARGET_HOME/.codex/superpowers" 2>/dev/null; then
                log "✓ Cloned superpowers repository"
            else
                log "⚠ Failed to clone superpowers repository"
            fi
        fi

        mkdir -p "$TARGET_HOME/.agents/skills"
        if [ ! -L "$TARGET_HOME/.agents/skills/superpowers" ]; then
            ln -s "$TARGET_HOME/.codex/superpowers/skills" "$TARGET_HOME/.agents/skills/superpowers"
            log "✓ Created superpowers symlink"
        else
            log "  Superpowers symlink already exists"
        fi
        log "✓ Configured Codex superpower skill"

        log "✓ Copied Codex config"
    else
        log "No Codex directory found at: $TEMP_DIR/.codex"
    fi

    log "File copy operations completed"
else
    log ""
    log "=== STEP 3: Skipping File Copy ==="
    log "Repository not available, skipping all file copy operations"
    log "Reason: Git clone failed or repository was not accessible"
fi

# Add skill scripts to PATH
if [ "$REPO_AVAILABLE" = true ]; then
    log ""
    log "=== STEP 3.5: Configuring Skill Utilities ==="
    log "Configuring PATH for skill utilities..."
    SKILL_SCRIPTS_DIR="$TARGET_HOME/.claude/skills/skill-creator/scripts"
    if [ -d "$SKILL_SCRIPTS_DIR" ]; then
        # Add to .bashrc
        BASHRC="$TARGET_HOME/.bashrc"
        if ! grep -q "claude/skills/skill-creator/scripts" "$BASHRC" 2>/dev/null; then
            echo "" >> "$BASHRC"
            echo "# Claude skill utilities" >> "$BASHRC"
            echo "export PATH=\"\$PATH:$SKILL_SCRIPTS_DIR\"" >> "$BASHRC"
            log "✓ Added skill scripts to PATH in .bashrc"
        else
            log "  PATH already configured in .bashrc"
        fi

        # Add to .profile for non-interactive shells
        PROFILE="$TARGET_HOME/.profile"
        if ! grep -q "claude/skills/skill-creator/scripts" "$PROFILE" 2>/dev/null; then
            echo "" >> "$PROFILE"
            echo "# Claude skill utilities" >> "$PROFILE"
            echo "export PATH=\"\$PATH:$SKILL_SCRIPTS_DIR\"" >> "$PROFILE"
            log "✓ Added skill scripts to PATH in .profile"
        else
            log "  PATH already configured in .profile"
        fi
    else
        log "⚠ Skill scripts directory not found: $SKILL_SCRIPTS_DIR"
    fi
    log "✓ Skill utilities configuration completed"
fi

# Install utility packages
log ""
log "=== STEP 4: Installing Utility Packages ==="
log "Preparing package installation..."

# Remove problematic yarn repository if it exists (added by node feature but has expired GPG key)
if [ -f /etc/apt/sources.list.d/yarn.list ]; then
    log "Removing yarn repository (not needed, has expired GPG key)..."
    rm -f /etc/apt/sources.list.d/yarn.list
    log "✓ Removed yarn.list"
fi

# Essential packages only
PACKAGES=(
    "vim"
    "git"
    "curl"
    "wget"
    "jq"
    "ripgrep"
    "fd-find"
    "tree"
    "htop"
    "net-tools"
    "sed"
    "awk"
    "sort"
    "diff"
    "sdiff"
    "uniq"
    "grep"
    "egrep"
    "fgrep"
    "ack"
    "base64"
    "head"
    "tail"
    "unzip"
    "find"
    "locate"
    "which"
    "vmstat"
    "ip"
    "ifconfig"
    "nslookup"
    "netstat"
    "ss"
    "tcpdump"
    "nmap"
    "ping"
    "traceroute"
    "socat",
    "bubblewrap"
)

log "Total packages to check/install: ${#PACKAGES[@]}"
log "Package list: ${PACKAGES[*]}"

# Update package list
log ""
log "Updating APT package lists..."
log "Command: sudo apt-get update -qq"
sudo apt-get update -qq
log "✓ Package lists updated"

# Install packages
log ""
log "Starting package installation..."
INSTALLED_COUNT=0
SKIPPED_COUNT=0
FAILED_COUNT=0

for package in "${PACKAGES[@]}"; do
    log ""
    log "Processing package: $package"

    # Check if already installed
    if dpkg -l 2>/dev/null | grep -q "^ii  $package " || dpkg -l 2>/dev/null | grep -q "^ii  ${package//-/} "; then
        log "  Package $package is already installed - skipping"
        log "  ○ $package already installed"
        SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    else
        log "  Package $package not found, attempting installation..."
        log "  Command: sudo apt-get install -y -qq $package"

        # Try to install the package with timeout
        if timeout 30 sudo apt-get install -y -qq "$package" 2>&1 | tail -n 5 >> "$LOG_FILE"; then
            log "  ✓ Successfully installed $package"
            log "  Installation completed for $package"
            INSTALLED_COUNT=$((INSTALLED_COUNT + 1))
        else
            log "  ✗ Failed to install $package"
            log "  ERROR: Installation failed for $package"
            FAILED_COUNT=$((FAILED_COUNT + 1))
        fi
    fi
done

# Package installation summary
log ""
log "Package installation summary:"
log "  - New installations: $INSTALLED_COUNT"
log "  - Already installed: $SKIPPED_COUNT"
log "  - Failed installations: $FAILED_COUNT"
log "✓ Package installation phase completed"

# Install Python uv
log ""
log "=== STEP 4.5: Installing Python uv ==="
log "Installing Python's uv package manager..."

# Install uv using pip
log "Installing uv with pip..."
log "Command: pip install uv"
if pip install uv 2>&1 | while IFS= read -r line; do log "    UV: $line"; done; [ ${PIPESTATUS[0]} -eq 0 ]; then
    log "  ✓ Successfully installed uv"

    # Verify installation
    if command -v uv &> /dev/null; then
        UV_VERSION=$(uv --version 2>/dev/null | head -n1)
        log "  ✓ uv is available: $UV_VERSION"
    else
        log "  ⚠ uv installed but not found in PATH"
    fi
else
    log "  ✗ Failed to install uv"
fi

log "✓ Python uv installation phase completed"

# Install Bun
log ""
log "=== STEP 4.6: Installing Bun ==="
log "Installing Bun JavaScript runtime..."

BUN_INSTALL_DIR="$TARGET_HOME/.bun"
log "Bun install directory: $BUN_INSTALL_DIR"
log "Command: curl -fsSL https://bun.sh/install | bash"

if curl -fsSL https://bun.sh/install | BUN_INSTALL="$BUN_INSTALL_DIR" bash 2>&1 | while IFS= read -r line; do log "    BUN: $line"; done; [ ${PIPESTATUS[0]} -eq 0 ]; then
    log "  ✓ Successfully installed Bun"

    # Add bun to PATH in .bashrc
    BASHRC="$TARGET_HOME/.bashrc"
    if ! grep -q "BUN_INSTALL" "$BASHRC" 2>/dev/null; then
        echo "" >> "$BASHRC"
        echo "# Bun" >> "$BASHRC"
        echo "export BUN_INSTALL=\"$BUN_INSTALL_DIR\"" >> "$BASHRC"
        echo "export PATH=\"\$BUN_INSTALL/bin:\$PATH\"" >> "$BASHRC"
        log "  ✓ Added Bun to PATH in .bashrc"
    else
        log "  Bun PATH already configured in .bashrc"
    fi

    # Add bun to PATH in .profile
    PROFILE="$TARGET_HOME/.profile"
    if ! grep -q "BUN_INSTALL" "$PROFILE" 2>/dev/null; then
        echo "" >> "$PROFILE"
        echo "# Bun" >> "$PROFILE"
        echo "export BUN_INSTALL=\"$BUN_INSTALL_DIR\"" >> "$PROFILE"
        echo "export PATH=\"\$BUN_INSTALL/bin:\$PATH\"" >> "$PROFILE"
        log "  ✓ Added Bun to PATH in .profile"
    else
        log "  Bun PATH already configured in .profile"
    fi

    # Verify installation
    if [ -x "$BUN_INSTALL_DIR/bin/bun" ]; then
        BUN_VERSION=$("$BUN_INSTALL_DIR/bin/bun" --version 2>/dev/null)
        log "  ✓ Bun is available: v$BUN_VERSION"
    else
        log "  ⚠ Bun installed but binary not found at $BUN_INSTALL_DIR/bin/bun"
    fi
else
    log "  ✗ Failed to install Bun"
fi

log "✓ Bun installation phase completed"

# Install PyYAML for skill utilities
log ""
log "Installing PyYAML for skill utilities..."
if command -v pip3 >/dev/null 2>&1; then
    pip3 install --quiet PyYAML
    if python3 -c "import yaml" 2>/dev/null; then
        YAML_VERSION=$(python3 -c "import yaml; print(yaml.__version__)" 2>/dev/null)
        log "✓ PyYAML installed successfully (version: $YAML_VERSION)"
    else
        log "⚠ PyYAML installation may have failed"
    fi
else
    log "⚠ pip3 not found, cannot install PyYAML"
fi

# Clean up
log ""
log "=== STEP 5: Cleanup ==="
log "Starting cleanup operations..."

if [ -d "$TEMP_DIR" ]; then
    log "Found temporary directory: $TEMP_DIR"
    log "Calculating size before removal..."
    TEMP_SIZE=$(du -sh "$TEMP_DIR" 2>/dev/null | cut -f1)
    log "Size of temporary directory: $TEMP_SIZE"
    log "Removing temporary directory..."
    rm -rf "$TEMP_DIR"
    log "✓ Temporary directory removed"
else
    log "No temporary directory to clean up"
fi

log "Cleanup completed"

# Final summary
log ""
log "========================================"
log "🎉 SETUP COMPLETED SUCCESSFULLY! 🎉"
log "========================================"
log ""
log "Configuration Summary:"
log "  • Claude configuration: ~/.claude/"
log "    - Agents: ~/.claude/agents/"
log "    - Commands: ~/.claude/commands/"
log "    - Output styles: ~/.claude/output-styles/"
log "    - Skills: ~/.claude/skills/"
log "    - Settings: ~/.claude/settings.json"
log "    - Configuration: ~/.claude/CLAUDE.md"
log ""
log "  • Codex configuration: ~/.codex/"
log "    - Commands: ~/.codex/commands/"
log "    - Skills: ~/.codex/skills/"
log "    - Configuration: ~/.codex/AGENTS.md"
log ""
log "  • Gemini configuration: ~/.gemini/"
log "    - Commands: ~/.gemini/commands/"
log "    - Configuration: ~/.gemini/GEMINI.md"
log ""
log "  • Project templates: ~/projects/claude-code-templates/"
log ""
log "  • VSCode settings: ~/User/"
log ""
log "Statistics:"
log "  • Packages installed: $INSTALLED_COUNT"
log "  • Packages skipped: $SKIPPED_COUNT"
log "  • Packages failed: $FAILED_COUNT"
log ""
log "Log file saved at: $LOG_FILE"
log ""
log "Script execution completed at: $(date '+%Y-%m-%d %H:%M:%S')"
log "========================================="