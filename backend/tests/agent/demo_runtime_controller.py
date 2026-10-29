"""Step 39 approved disposable Docker controller; no production deployment path."""

import hashlib
import io
import json
import os
import secrets
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOG_ROOT = ROOT / "docs/integration/step39_logs"
PROJECT = "ghost-demo-validation"
MYSQL = "mysql@sha256:76f0358884cb92d9a086d24e5671c38048d3fef40f2588703d73eb55392d6b69"
MAILPIT = (
    "axllent/mailpit:v1.32.0@sha256:"
    "0790692be935ea4420d085694f7985b1f692ca6a8771ab0e0bd8ba75ac180498"
)
RUNNER = (
    "ghost-resume-validation-runner:step33@sha256:"
    "86fb65f841f3c34323be07228081adb746af77282585f3e3251fd5e79a6cd12c"
)
NONCE = secrets.token_hex(5)
LOGS = LOG_ROOT / ("attempt-" + NONCE)
SECRET_VALUES = {
    key: secrets.token_urlsafe(32) for key in ("V_DB_PASSWORD", "V_ROOT_PASSWORD", "V_OWNER")
}
ENV = {**os.environ, **SECRET_VALUES, "V_NONCE": NONCE}

COMPOSE = f"""name: {PROJECT}
services:
  db:
    image: {MYSQL}
    pull_policy: never
    environment:
      MYSQL_ROOT_PASSWORD: ${{V_ROOT_PASSWORD}}
      MYSQL_DATABASE: nvidia_app_test
      MYSQL_USER: validation
      MYSQL_PASSWORD: ${{V_DB_PASSWORD}}
    command: [--transaction-isolation=READ-COMMITTED, --default-time-zone=+00:00]
    volumes: [data:/var/lib/mysql]
    networks: [isolated]
    healthcheck:
      test:
        - CMD-SHELL
        - >-
          MYSQL_PWD=$$MYSQL_PASSWORD mysql --protocol=socket --user=$$MYSQL_USER
          --database=$$MYSQL_DATABASE --execute="SELECT 1" >/dev/null 2>&1
      interval: 2s
      timeout: 3s
      retries: 60
  mailpit:
    image: {MAILPIT}
    pull_policy: never
    user: '1000:1000'
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    tmpfs: ['/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777']
    networks: [isolated]
    environment:
      TZ: UTC
      MP_DATABASE: /tmp/mailpit.db
      MP_DISABLE_VERSION_CHECK: 'true'
      MP_SMTP_DISABLE_RDNS: 'true'
      MP_SMTP_RELAY_ALL: 'false'
      MP_SMTP_MAX_RECIPIENTS: '1'
      MP_SMTP_ALLOWED_RECIPIENTS: '^(teammate|reviewer)@example\\.test$$'
      MP_ALLOWED_HOSTS: mailpit
      MP_QUIET: 'true'
  staging:
    image: {RUNNER}
    pull_policy: never
    entrypoint: [python]
    command: [-c, 'import time; time.sleep(3600)']
    network_mode: none
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    volumes: [source:/workspace, checkpoints:/checkpoints]
  runner:
    image: {RUNNER}
    pull_policy: never
    entrypoint: [python]
    command: [-c, 'import time; time.sleep(86400)']
    user: '1000:1000'
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    working_dir: /workspace/member_a_backend/nvidia backend
    tmpfs: ['/tmp:rw,noexec,nosuid,nodev,size=536870912,mode=1777']
    volumes: [source:/workspace:ro, checkpoints:/checkpoints]
    networks: [isolated]
    environment:
      MYSQL_VALIDATION_PROJECT: {PROJECT}
      MYSQL_HOST: db
      MYSQL_TEST_DATABASE: nvidia_app_test
      MYSQL_USER: validation
      MYSQL_PASSWORD: ${{V_DB_PASSWORD}}
      API_BEARER_TOKEN: ${{V_OWNER}}
      LANGSMITH_TRACING: 'false'
      LANGCHAIN_TRACING_V2: 'false'
      PYTHONDONTWRITEBYTECODE: '1'
      TZ: UTC
networks:
  isolated:
    name: {PROJECT}-network-${{V_NONCE}}
    internal: true
    enable_ipv6: false
volumes:
  data:
    name: {PROJECT}-mysql-${{V_NONCE}}
  source:
    name: {PROJECT}-source-${{V_NONCE}}
  checkpoints:
    name: {PROJECT}-sqlite-${{V_NONCE}}
"""


def docker(*args, content=None, check=True):
    return subprocess.run(
        ["docker", *args], input=content, capture_output=True, env=ENV, check=check
    )


def compose(*args, check=True):
    return docker(
        "compose",
        "--project-directory",
        str(ROOT),
        "--env-file",
        os.devnull,
        "-p",
        PROJECT,
        "-f",
        "-",
        *args,
        content=COMPOSE.encode(),
        check=check,
    )


def save(name, value):
    data = value if isinstance(value, bytes) else json.dumps(value, indent=2).encode()
    assert all(secret.encode() not in data for secret in SECRET_VALUES.values())
    (LOGS / name).write_bytes(data)


def inventory():
    result = {}
    for kind, args in {
        "containers": ("ps", "-aq"),
        "networks": ("network", "ls", "-q"),
        "volumes": ("volume", "ls", "-q"),
    }.items():
        ids = docker(*args).stdout.decode().split()
        result[kind] = []
        for ref in ids:
            mode = (
                "volume" if kind == "volumes" else "network" if kind == "networks" else "container"
            )
            d = json.loads(docker(mode, "inspect", ref).stdout)[0]
            if mode == "container":
                result[kind].append(
                    {
                        "id": d["Id"],
                        "name": d["Name"],
                        "image": d["Image"],
                        "state": {k: d["State"][k] for k in ("Status", "Running", "ExitCode")},
                        "mounts": [
                            {k: m.get(k) for k in ("Type", "Name", "Destination", "RW")}
                            for m in d["Mounts"]
                        ],
                        "networks": {
                            k: v["NetworkID"] for k, v in d["NetworkSettings"]["Networks"].items()
                        },
                    }
                )
            else:
                result[kind].append({"id": d.get("Id", d.get("Name")), "name": d["Name"]})
    return result


def wait_db():
    ref = compose("ps", "-q", "db").stdout.decode().strip()
    for _ in range(90):
        value = json.loads(docker("inspect", ref).stdout)[0]
        if value["State"].get("Health", {}).get("Status") == "healthy":
            return ref
        time.sleep(2)
    raise RuntimeError("Disposable database did not become healthy")


def query(sql):
    return (
        compose(
            "exec",
            "-T",
            "db",
            "sh",
            "-c",
            'MYSQL_PWD="$MYSQL_PASSWORD" mysql --protocol=socket --user="$MYSQL_USER" --'
            'database="$MYSQL_DATABASE" --batch --skip-column-names --execute=' + "'" + sql + "'",
        )
        .stdout.decode()
        .strip()
    )


def exec_runner(uuid, *args, check=True):
    ref = compose("ps", "-q", "runner").stdout.decode().strip()
    return docker("exec", "-e", "MYSQL_SERVER_UUID=" + uuid, ref, "python", *args, check=check)


def guard(uuid, stage, *args):
    value = exec_runner(
        uuid, "/workspace/backend/tests/agent/demo_runtime_guard.py", stage, *args, check=False
    )
    save(stage + ("-" + args[0] if args else "") + ".log", value.stdout + value.stderr)
    assert value.returncode == 0, "Validation stage failed: " + stage


def source_archive():
    paths = []
    for directory in (
        "backend/app",
        "backend/tests",
        "member_a_backend/nvidia backend/app",
        "member_a_backend/nvidia backend/tests",
        "member_a_backend/nvidia backend/migrations",
    ):
        paths.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file() and p.suffix in (".py", ".mako") and "__pycache__" not in p.parts
        )
    paths += [
        ROOT / p
        for p in (
            "pyproject.toml",
            "member_a_backend/nvidia backend/pyproject.toml",
            "member_a_backend/nvidia backend/alembic.ini",
        )
    ]
    stream = io.BytesIO()
    fingerprints = {}
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for path in sorted(set(paths)):
            assert not path.is_symlink()
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            fingerprints[name] = hashlib.sha256(data).hexdigest()
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o644
            archive.addfile(entry, io.BytesIO(data))
    save("source-manifest.json", fingerprints)
    return stream.getvalue()


def main():
    LOGS.mkdir(parents=True, exist_ok=False)
    before = inventory()
    save("baseline.json", before)
    save("compose.sanitized.yaml", COMPOSE.encode())
    for ref in (MYSQL, MAILPIT, RUNNER):
        value = json.loads(docker("image", "inspect", ref).stdout)[0]
        assert value["Os"] == "linux" and value["Architecture"] == "amd64"
        assert ref.split("@")[-1] == value["Id"] if "@" in ref else ref == value["Id"]
    assert not docker(
        "ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT
    ).stdout.strip()
    for kind in ("network", "volume"):
        assert not docker(
            kind, "ls", "-q", "--filter", "label=com.docker.compose.project=" + PROJECT
        ).stdout.strip()
    created = False
    driver = None
    try:
        created = True
        compose("up", "-d", "staging")
        staging = compose("ps", "-q", "staging").stdout.decode().strip()
        docker("cp", "-", staging + ":/workspace", content=source_archive())
        docker("exec", staging, "python", "-c", "import os; os.chmod('/checkpoints',0o777)")
        compose("stop", "staging")
        compose("rm", "-f", "staging")
        compose("up", "-d", "db", "mailpit", "runner")
        dbref = wait_db()
        uuid = query("SELECT @@server_uuid")
        ca = docker("cp", dbref + ":/var/lib/mysql/ca.pem", "-").stdout
        with tarfile.open(fileobj=io.BytesIO(ca)) as archive:
            cert = archive.extractfile(archive.getmembers()[0]).read()
        runner = compose("ps", "-q", "runner").stdout.decode().strip()
        docker(
            "exec",
            "-i",
            runner,
            "python",
            "-c",
            "import pathlib,sys; "
            "pathlib.Path('/checkpoints/ca.pem').write_bytes(sys.stdin.buffer.read())",
            content=cert,
        )
        inspected = []
        for service in ("db", "mailpit", "runner"):
            ref = compose("ps", "-q", service).stdout.decode().strip()
            value = json.loads(docker("inspect", ref).stdout)[0]
            assert not value["HostConfig"]["Privileged"] and not value["HostConfig"]["PortBindings"]
            assert all(m["Type"] == "volume" for m in value["Mounts"])
            assert len(value["NetworkSettings"]["Networks"]) == 1
            if service in ("runner", "mailpit"):
                assert value["Config"]["User"] == "1000:1000"
                assert value["HostConfig"]["ReadonlyRootfs"]
                assert value["HostConfig"]["CapDrop"] == ["ALL"]
            if service == "mailpit":
                settings = dict(entry.split("=", 1) for entry in value["Config"]["Env"])
                assert settings["MP_SMTP_RELAY_ALL"] == "false"
                assert not any(
                    "FORWARD" in key or ("RELAY" in key and key != "MP_SMTP_RELAY_ALL")
                    for key in settings
                )
                save(
                    "mailpit-policy.json",
                    {
                        "relay_all": False,
                        "forwarding_configured": False,
                        "host_ports": False,
                        "uid": 1000,
                    },
                )
            inspected.append(
                {
                    "service": service,
                    "id": ref,
                    "image": value["Image"],
                    "user": value["Config"]["User"],
                    "mounts": value["Mounts"],
                    "network_mode": value["HostConfig"]["NetworkMode"],
                    "ports": value["HostConfig"]["PortBindings"],
                }
            )
        network = json.loads(docker("network", "inspect", PROJECT + "-network-" + NONCE).stdout)[0]
        assert network["Internal"]
        save(
            "runtime.json", {"containers": inspected, "network_internal": True, "server_uuid": uuid}
        )
        guard(uuid, "isolation")
        guard(uuid, "mailpit")
        revisions = [
            "0001_initial",
            "0002_agent_identity",
            "0003_scoped_consent",
            "0004_operation_ledger",
            "0005_durable_approvals",
            "0006_trusted_execution",
            "0007_document_catalog",
            "0008_secure_document_reading",
            "0009_mailpit_email",
            "0010_workflow_resume",
            "0011_controlled_execution",
        ]
        for revision in revisions:
            guard(uuid, "migrate", revision)
        guard(uuid, "schema")
        command = [
            "docker",
            "exec",
            "-i",
            "-e",
            "MYSQL_SERVER_UUID=" + uuid,
            runner,
            "python",
            "/workspace/backend/tests/agent/demo_runtime.py",
        ]
        driver = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV
        )
        first = driver.stdout.readline()
        save("scenarios.json", json.loads(first))
        assert json.loads(first)["stage"] == "scenarios"
        guard(uuid, "persistence")
        (LOGS / "persistence-before.log").write_bytes((LOGS / "persistence.log").read_bytes())
        compose("restart", "db")
        wait_db()
        assert query("SELECT @@server_uuid") == uuid
        guard(uuid, "persistence")
        assert (LOGS / "persistence.log").read_bytes() == (
            LOGS / "persistence-before.log"
        ).read_bytes()
        driver.stdin.write(b'{"continue":true}\n')
        driver.stdin.flush()
        second = driver.stdout.readline()
        save("restart-unknown.json", json.loads(second))
        driver.stdin.close()
        driver.wait(timeout=60)
        error = driver.stderr.read()
        save("driver.log", error)
        assert driver.returncode == 0
        guard(uuid, "postcheck")
        save(
            "result.json",
            {
                "status": "PASSED",
                "migrations": 11,
                "scenario_events": len(json.loads(first)["events"]),
                "final_captures": json.loads(second)["unknown_replay"]["captures"],
            },
        )
    except Exception as exc:
        if driver is not None:
            driver.kill()
            error = driver.stderr.read()
            for secret in SECRET_VALUES.values():
                error = error.replace(secret.encode(), b"[REDACTED]")
            save("driver-failure.log", error)
        save("failure.json", {"type": type(exc).__name__, "message": "Validation did not complete"})
        raise
    finally:
        if created:
            compose("down", "-v", "--remove-orphans")
            after = inventory()
            save(
                "cleanup.json",
                {
                    "after": after,
                    "unrelated_containers_unchanged": before["containers"] == after["containers"],
                    "unrelated_volumes_unchanged": before["volumes"] == after["volumes"],
                    "networks_unchanged": before["networks"] == after["networks"],
                    "host_snapshot_created": False,
                },
            )
            assert (
                before["containers"] == after["containers"]
                and before["volumes"] == after["volumes"]
            )
        save(
            "index.json",
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(LOGS.iterdir())
                if p.name != "index.json"
            },
        )


if __name__ == "__main__":
    main()
