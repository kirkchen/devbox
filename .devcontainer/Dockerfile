FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04

# Avoid warnings by switching to noninteractive
ENV DEBIAN_FRONTEND=noninteractive

# Install essential tools
RUN apt-get update && apt-get -y install --no-install-recommends \
    # Core utilities
    curl \
    wget \
    git \
    vim \
    tmux \
    # Build tools (for some installations)
    build-essential \
    # Search tools from your config
    silversearcher-ag \
    # Git UI tool
    tig \
    # Process monitoring
    htop \
    # Additional useful tools
    jq \
    unzip \
    # Clean up
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# Install fzf globally
RUN git clone --depth 1 https://github.com/junegunn/fzf.git /opt/fzf \
    && /opt/fzf/install --bin \
    && ln -s /opt/fzf/bin/fzf /usr/local/bin/fzf

# Install bat (better cat) - multi-arch support
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "amd64" ]; then \
        curl -L https://github.com/sharkdp/bat/releases/download/v0.24.0/bat_0.24.0_amd64.deb -o /tmp/bat.deb; \
    elif [ "$ARCH" = "arm64" ]; then \
        curl -L https://github.com/sharkdp/bat/releases/download/v0.24.0/bat_0.24.0_arm64.deb -o /tmp/bat.deb; \
    fi \
    && dpkg -i /tmp/bat.deb \
    && rm /tmp/bat.deb

# Install eza (modern ls replacement, successor to exa)
RUN apt-get update && apt-get install -y gpg \
    && mkdir -p /etc/apt/keyrings \
    && wget -qO- https://raw.githubusercontent.com/eza-community/eza/main/deb.asc | gpg --dearmor -o /etc/apt/keyrings/gierens.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/gierens.gpg] http://deb.gierens.de stable main" | tee /etc/apt/sources.list.d/gierens.list \
    && chmod 644 /etc/apt/keyrings/gierens.gpg /etc/apt/sources.list.d/gierens.list \
    && apt-get update \
    && apt-get install -y eza \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Switch back to dialog for any ad-hoc use of apt-get
ENV DEBIAN_FRONTEND=dialog

# Set the default shell to zsh (will be configured by devcontainer features)
ENV SHELL=/bin/zsh