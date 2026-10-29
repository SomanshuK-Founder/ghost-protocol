"""Assemble and audit the synthetic image context; never execute the probe."""

import hashlib
import io
import json
import platform
import struct
import subprocess
import tarfile
from pathlib import Path


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True, timeout=30)


def prepare() -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("Requires Linux AMD64 trusted build tools")
    source = Path(__file__).resolve().parent
    build = source / "build" / "context"
    # Refuse reuse: stale inputs must not silently enter this dedicated context.
    build.mkdir(mode=0o700, parents=True)
    obj, binary = build / "probe.o", build / "probe"
    run("as", "--64", "-o", str(obj), str(source / "probe.s"))
    run(
        "ld",
        "-m",
        "elf_x86_64",
        "-static",
        "--build-id=none",
        "-z",
        "noexecstack",
        "-o",
        str(binary),
        str(obj),
    )
    elf = binary.read_bytes()
    if elf[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", elf, 18)[0] != 62:
        raise SystemExit("Unexpected ELF architecture")
    headers = run("readelf", "-lW", str(binary))
    if "INTERP" in headers or "DYNAMIC" in headers:
        raise SystemExit("Dynamic loader/dependencies forbidden")
    stack = next(line for line in headers.splitlines() if "GNU_STACK" in line)
    if "RWE" in stack:
        raise SystemExit("Executable stack forbidden")
    disassembly = run("objdump", "-d", "-Mintel", str(binary))
    if "syscall" not in disassembly or "PTR ds:0x" in disassembly:
        raise SystemExit("Unexpected disassembly")
    (build / "probe.disassembly.txt").write_text(disassembly)
    directories = {
        "opt": (0, 0, 0o755),
        "opt/ghost-probe": (0, 0, 0o755),
        "etc": (0, 0, 0o755),
        "tmp": (0, 0, 0o755),
        "tmp/ghost-probe": (1000, 1000, 0o700),
        "work": (1000, 1000, 0o700),
        "dev": (0, 0, 0o755),
        "denied": (1000, 1000, 0o755),
        "denied/home": (0, 0, 0o755),
        "denied/home/.ssh": (0, 0, 0o755),
    }
    files = {
        "opt/ghost-probe/probe": (elf, 0, 0, 0o555),
        "etc/passwd": (b"probe:x:1000:1000:Synthetic probe:/work:/nonexistent\n", 0, 0, 0o444),
        "etc/group": (b"probe:x:1000:\n", 0, 0, 0o444),
        "denied/ghost.env": (b"SYNTHETIC_CANARY_NOT_A_CREDENTIAL\n", 0, 0, 0o444),
        "denied/home/.ssh/canary": (b"SYNTHETIC_CANARY_NOT_AN_SSH_KEY\n", 0, 0, 0o444),
    }
    inventory = []
    archive = build / "rootfs.tar"
    with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as tar:
        for name in sorted(directories.keys() | files.keys()):
            info = tarfile.TarInfo(name)
            info.mtime = 0
            if name in directories:
                info.uid, info.gid, info.mode = directories[name]
                info.type = tarfile.DIRTYPE
                data = b""
            else:
                data, info.uid, info.gid, info.mode = files[name]
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data) if info.isfile() else None)
            inventory.append(
                {
                    "path": "/" + name,
                    "type": "file" if info.isfile() else "directory",
                    "uid": info.uid,
                    "gid": info.gid,
                    "mode": oct(info.mode),
                    "size": info.size,
                    "sha256": hashlib.sha256(data).hexdigest() if info.isfile() else None,
                }
            )
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if {m.name.rstrip("/") for m in members} != directories.keys() | files.keys():
            raise SystemExit("Unexpected rootfs members")
        for member in members:
            if not (member.isfile() or member.isdir()) or member.name.startswith("/"):
                raise SystemExit("Unsafe archive member")
            if ".." in Path(member.name).parts or member.mode & 0o6000:
                raise SystemExit("Unsafe path or set-id mode")
        if tar.extractfile("opt/ghost-probe/probe").read() != elf:
            raise SystemExit("Probe content mismatch")
    dockerfile = (source / "Dockerfile").read_bytes()
    (build / "Dockerfile").write_bytes(dockerfile)
    (build / ".dockerignore").write_text("*\n!Dockerfile\n!rootfs.tar\n")
    manifest = {
        "status": "PREPARED_NOT_EXECUTED",
        "platform": "linux/amd64",
        "base": "scratch (empty filesystem, no registry image or pull)",
        "probe_sha256": hashlib.sha256(elf).hexdigest(),
        "source_sha256": hashlib.sha256((source / "probe.s").read_bytes()).hexdigest(),
        "rootfs_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "dockerfile_sha256": hashlib.sha256(dockerfile).hexdigest(),
        "tools": {name: run(name, "--version").splitlines()[0] for name in ("as", "ld")},
        "files": inventory,
        "device_note": "/dev/null is supplied by the container runtime, not an archive device",
        "functional_tests": "NOT RUN: workload execution requires OpenShell approval",
    }
    (build / "inventory.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}))


if __name__ == "__main__":
    prepare()
