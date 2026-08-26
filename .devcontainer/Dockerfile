# syntax=docker/dockerfile:1.4
ARG BASE_IMAGE=mcr.microsoft.com/playwright:v1.58.2-jammy
FROM ${BASE_IMAGE}

LABEL maintainer="boredengineering"
LABEL description="Full-Stack Physical AI, Cloud IaC, Playwright, uv, R-base & Robotics Development Container"

# Copy fast Rust-based Python package manager (uv)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Environment Variables
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=all \
    MPLCONFIGDIR=/tmp/matplotlib \
    TF_DATA_DIR=/opt/tf-data \
    ANSIBLE_FORCE_COLOR=true \
    PYTHONUNBUFFERED=1

# Layer 1: Core System Dependencies, Vulkan, X11, OpenGL, and R CRAN (r-base)
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    gpg \
    lsb-release \
    build-essential \
    cmake \
    git \
    git-lfs \
    curl \
    wget \
    unzip \
    rsync \
    jq \
    tmux \
    htop \
    nano \
    sudo \
    ffmpeg \
    python3-pip \
    python3-dev \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    libgl1-mesa-dri \
    libglu1-mesa-dev \
    libvulkan1 \
    libvulkan-dev \
    vulkan-tools \
    mesa-vulkan-drivers \
    x11-xserver-utils \
    libxrandr2 \
    libxcursor1 \
    libxinerama1 \
    libxi6 \
    r-base \
    r-base-dev \
    && rm -rf /var/lib/apt/lists/*

# Layer 1.1: Quarto Publishing Engine & R Ecosystem
RUN QUARTO_VERSION=$(curl -s https://api.github.com/repos/quarto-dev/quarto-cli/releases/latest | grep -oP '"tag_name": "\K[^"]+') && \
    wget -q https://github.com/quarto-dev/quarto-cli/releases/download/${QUARTO_VERSION}/quarto-${QUARTO_VERSION#v}-linux-amd64.deb && \
    dpkg -i quarto-${QUARTO_VERSION#v}-linux-amd64.deb && \
    rm quarto-${QUARTO_VERSION#v}-linux-amd64.deb && \
    Rscript -e 'install.packages(c("languageserver", "renv", "rmarkdown", "knitr"), repos="https://cloud.r-project.org")'

# Layer 2: Cloud Providers & Infrastructure as Code (IaC) Stack
# 2.1 HashiCorp Terraform & Packer
RUN wget -O- https://apt.releases.hashicorp.com/gpg | gpg --dearmor | tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/hashicorp.list && \
    apt-get update && apt-get install -y --no-install-recommends terraform packer && \
    rm -rf /var/lib/apt/lists/*

# 2.2 Google Cloud SDK (gcloud CLI)
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    apt-get update && apt-get install -y --no-install-recommends google-cloud-cli && \
    rm -rf /var/lib/apt/lists/*

# 2.3 Azure CLI
RUN curl -sL https://aka.ms/InstallAzureCLIDeb | bash && \
    rm -rf /var/lib/apt/lists/*

# 2.4 AWS CLI v2
RUN cd /tmp && \
    case "$(dpkg --print-architecture)" in \
      amd64) curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" ;; \
      arm64) curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip" ;; \
    esac && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf /tmp/aws*

# 2.5 Alibaba Cloud CLI (aliyun)
RUN curl -fsSL https://raw.githubusercontent.com/aliyun/aliyun-cli/HEAD/install.sh | bash || true

# 2.6 HashiCorp Terraform MCP Server (terraform-mcp-server)
RUN curl -fsSL -o /tmp/tf-mcp.zip https://releases.hashicorp.com/terraform-mcp-server/1.2.0/terraform-mcp-server_1.2.0_linux_amd64.zip && \
    unzip -q /tmp/tf-mcp.zip -d /tmp/ && \
    mv /tmp/terraform-mcp-server /usr/local/bin/ && \
    chmod +x /usr/local/bin/terraform-mcp-server && \
    rm -rf /tmp/tf-mcp*

# Layer 3: Autonomous Terminal AI Agent CLIs (Claude Code, Antigravity CLI, Hermes Agent)
RUN npm install -g @anthropic-ai/claude-code && \
    (curl -fsSL https://antigravity.google/cli/install.sh | bash || true) && \
    (ln -sf /root/.local/bin/agy /usr/local/bin/agy 2>/dev/null || true) && \
    (curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup --skip-browser || true)

# Layer 4: Ansible & Whole-Body Control (WBC) / Robotics Python Stack
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel && \
    pip3 install --no-cache-dir \
        ansible \
        cmeel \
        pin-pink==3.1.0 \
        qpsolvers[daqp,proxsuite] \
        pyzmq \
        msgpack \
        protobuf \
        h5py \
        opencv-python-headless \
        matplotlib \
        pandas \
        scipy \
        tensorboard \
        tabulate \
        gymnasium \
        lerobot \
        jupyter \
        ipykernel \
        "huggingface_hub[cli]" \
        click \
        randomname \
        pwgen \
        debugpy && \
    ansible-galaxy collection install community.docker

# Layer 5: Common Mount Points, Cache & Vulkan ICD Environment
RUN mkdir -p /datasets /models /eval /tmp/matplotlib /opt/tf-data /workspaces && \
    chmod -R 777 /datasets /models /eval /tmp/matplotlib /opt/tf-data /workspaces && \
    mkdir -p /etc/vulkan/icd.d && \
    echo '{"file_format_version": "1.0.0", "ICD": {"library_path": "libGLX_nvidia.so.0", "api_version": "1.3"}}' > /etc/vulkan/icd.d/nvidia_icd.json

WORKDIR /workspaces

CMD ["bash"]
