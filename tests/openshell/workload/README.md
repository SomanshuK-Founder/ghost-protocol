# Synthetic OpenShell workload — Step 42K.2

Test-only Linux AMD64 probe. Never run it directly on the host or with docker run.
Execution requires a separately approved OpenShell sandbox trial. No agent, model,
provider, SMTP client, backend client, interpreter, or authorization logic is included.

## Build

Run in Ubuntu with its already installed GNU binutils 2.42 and Python 3.12:

    python3 -B prepare.py
    python3 -B -m unittest discover -s . -p test_prepare.py -v
    docker build --network=none --pull=false --provenance=false \
      --platform linux/amd64 --progress=plain \
      --tag ghost-openshell-probe:step42k2-20261026-1 build/context

The approved build has already run once. Do not repeat/tag over it without review.
Preparation refuses an existing context rather than overwriting it. For a future
rebuild use a fresh dedicated source copy; inspect it first, never a repository-root
Docker context or home directory. The tests create only synthetic temporary build
directories, compile twice for reproducibility, and never execute the binary.

FROM scratch means an empty filesystem, not a floating registry image. There is
no external base to download or pin. The final image, source, rootfs and binary
are pinned in image-inventory.json. Existing cached OpenShell images remain trusted
runtime infrastructure and are not repurposed as workload images. No new packages,
compiler, registry access, RUN instruction or build helper container was needed.

prepare.py assembles probe.s and links a static ELF using the existing host tools.
It creates an explicit deterministic rootfs archive with five regular files and
ten directories, no links, devices, set-id bits or private inputs. The build context
filter admits only Dockerfile and rootfs.tar. build/ is ignored and contains local
generated binaries/archive/disassembly/logs; do not stage it. Docker supplies the
ordinary /dev/null at runtime. No CA/key material is embedded. Docker/BuildKit adds
only its conventional PATH environment; the probe never reads environment values.

## Probe interface — future sandbox execution only

| Exact arguments | Intended observation |
| --- | --- |
| identity | Report UID/GID; fail if UID is root |
| hold --seconds 120 | Sleep once for exactly 120 seconds; no service/listener |
| fs-allowed | Exclusively create fixed scratch file, write/read/compare synthetic marker, unlink; refuse existing file |
| fs-denied | Open only the image-baked /denied/ghost.env canary; never read/print its bytes |
| net-denied | Nonblocking TCP connect to TEST-NET 192.0.2.1:443, poll at most one second, no application payload |

Output is one JSON object with probe/result/errno/uid/gid. No arbitrary path,
destination, port, duration, command or environment is accepted. Exit 0 means the
specific observation succeeded; 1 is failure/unexpected access; 2 is invalid input
or inconclusive denial evidence. EACCES/EPERM can be reported as denied; ENOENT,
timeout, refusal and unreachable routes remain inconclusive. Even a denied result
needs corresponding trusted OpenShell logs to attribute it to policy enforcement.

The optional broader OS16 tests (child inheritance, extra denied executable,
MySQL/SMTP/DNS targets, process metadata) are not implemented by this minimal probe.
Do not invent passes for them. There is no general executable allowlist guarantee.

## Review and status

Static ELF/archive/image inspection and three preparation tests passed. Probe
functionality and kernel policy enforcement have NOT RUN. Disassembly review
corrected an immediate-operand bug before the one image build; the final binary
uses immediate marker lengths. A preparatory host chmod failed on the Windows
mount and was removed; image permissions are set in the explicit tar metadata.

See ../../../docs/openshell/OS17_WORKLOAD_IMAGE_PREPARATION.md and OS18 for the
immutable image identity, callback blocker, resource checks and next approval gate.
Images do not encode privileged-container or socket-mount permissions. Future
actual HostConfig/mounts/namespace/qualification must be inspected independently.
