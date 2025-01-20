FROM ubuntu:22.04
WORKDIR /root

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    ninja-build \
    cmake \
    sudo \
    ccache \
    python3-pip \
    libkrb5-3 \
    zlib1g-dev \
    liblttng-ust1t64 \
    libssl-dev \
    libicu-dev \
    cargo \
    gawk \
    bison \
    wget \
    flex \
    curl \
    jq \
    git
RUN wget -O - https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -
RUN apt-get update && apt-get install -y \
    llvm-20-dev \
    clang-20 \
    && rm -rf /var/lib/apt/lists/*

# Clone and build alive2
RUN git clone https://github.com/AliveToolkit/alive2.git && \
    cd alive2 && mkdir -p build && cd build && \
    cmake .. -GNinja -DCMAKE_BUILD_TYPE=Release -DBUILD_TV=1 && \
    cmake --build . -j

# Install python dependencies

# Clone the repository and llvm
RUN git clone https://github.com/dtcxzyw/llvm-apr-benchmark.git && \
    cd llvm-apr-benchmark && \
    pip3 install -r requirements.txt && \
    mkdir -p work && cd work && \
    git clone https://github.com/llvm/llvm-project.git && \

# Set environment variables
ENV LAB_LLVM_DIR=/root/llvm-apr-benchmark/work/llvm-project
ENV LAB_LLVM_BUILD_DIR=/root/llvm-apr-benchmark/work/llvm-build
ENV LAB_LLVM_ALIVE_TV=/root/alive2/build/alive-tv
ENV LAB_DATASET_DIR=/root/llvm-apr-benchmark/dataset
ENV LAB_FIX_DIR=/root/llvm-apr-benchmark/examples/fixes
