FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04

# Avoid warnings by switching to noninteractive
ENV DEBIAN_FRONTEND=noninteractive

# Install essential tools
RUN apt-get update && apt-get -y install --no-install-recommends \
    # Core utilities
    curl \
    wget \
    git \
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
    # Environment management
    direnv \
    # Dependencies for building Vim
    libncurses5-dev \
    libgtk2.0-dev \
    libatk1.0-dev \
    libcairo2-dev \
    libx11-dev \
    libxpm-dev \
    libxt-dev \
    python3-dev \
    # Clean up
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# Install Vim 9.x from source
RUN git clone https://github.com/vim/vim.git /tmp/vim \
    && cd /tmp/vim \
    && ./configure \
        --with-features=huge \
        --enable-multibyte \
        --enable-python3interp=yes \
        --with-python3-config-dir=/usr/lib/python3.*/config-*-linux-gnu \
        --enable-gui=gtk2 \
        --enable-cscope \
        --prefix=/usr/local \
    && make -j$(nproc) \
    && make install \
    && cd / \
    && rm -rf /tmp/vim \
    && update-alternatives --install /usr/bin/editor editor /usr/local/bin/vim 60 \
    && update-alternatives --config editor \
    && update-alternatives --install /usr/bin/vi vi /usr/local/bin/vim 60 \
    && update-alternatives --config vi

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

# Install diff-so-fancy (better git diff)
RUN curl -L https://raw.githubusercontent.com/so-fancy/diff-so-fancy/master/third_party/build_fatpack/diff-so-fancy -o /usr/local/bin/diff-so-fancy \
    && chmod +x /usr/local/bin/diff-so-fancy

# Install uv (fast Python package and project manager)
# Using the official Docker image to get the binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# Make sure the binaries are executable
RUN chmod +x /bin/uv /bin/uvx

# Switch back to dialog for any ad-hoc use of apt-get
ENV DEBIAN_FRONTEND=dialog

# Set the default shell to zsh (will be configured by devcontainer features)
ENV SHELL=/bin/zsh