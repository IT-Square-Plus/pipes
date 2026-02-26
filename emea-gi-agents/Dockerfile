FROM quay.io/lib/ubuntu:latest

LABEL maintainer="EMEA-GI-Team"
LABEL description="Custom Azure DevOps Agent with DevOps tools"

ENV DEBIAN_FRONTEND=noninteractive

USER root

# Install base tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        wget \
        curl \
        jq \
        unzip \
        git \
        gnupg \
        lsb-release \
        software-properties-common \
        libcurl4 \
        libicu74 \
        libunwind8 \
        netcat-openbsd \
    && update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Python 3.14 from deadsnakes PPA
RUN add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.14 \
        python3.14-venv \
        python3.14-dev \
        python3-pip \
    && rm -rf /var/lib/apt/lists/* && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.14 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.14 1

# Install gitleaks
RUN GITLEAKS_VERSION=$(curl -s https://api.github.com/repos/gitleaks/gitleaks/releases/latest | jq -r .tag_name | sed s/^v//) && \
    echo "Installing Gitleaks version: $GITLEAKS_VERSION" && \
    wget "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" && \
    tar -xzf "gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" && \
    mv gitleaks /usr/local/bin/ && \
    chmod +x /usr/local/bin/gitleaks && \
    rm "gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" && \
    gitleaks version

# Install yamllint and ansible-lint
RUN pip3 install --no-cache-dir yamllint ansible-lint ansible PyYAML packaging rich --break-system-packages && \
    yamllint --version && \
    ansible-lint --version

# Install Azure Pipelines Agent
WORKDIR /azp
RUN AZP_AGENT_VERSION=$(curl -s https://api.github.com/repos/microsoft/azure-pipelines-agent/releases/latest | jq -r .tag_name | sed s/^v//) && \
    echo "Installing Azure Pipelines Agent version: $AZP_AGENT_VERSION" && \
    wget https://download.agent.dev.azure.com/agent/${AZP_AGENT_VERSION}/vsts-agent-linux-x64-${AZP_AGENT_VERSION}.tar.gz && \
    tar -xzf vsts-agent-linux-x64-${AZP_AGENT_VERSION}.tar.gz && \
    rm vsts-agent-linux-x64-${AZP_AGENT_VERSION}.tar.gz && \
    ./bin/installdependencies.sh

# Create azdevops user
RUN useradd -m -d /azp azdevops && \
    chown -R azdevops:azdevops /azp

USER azdevops
WORKDIR /azp

# Verify tools
RUN gitleaks version && yamllint --version && ansible-lint --version

CMD ["bash"]
