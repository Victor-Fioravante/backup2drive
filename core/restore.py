import os
import re
import subprocess
import datetime

import paramiko

from core.db import add_history
from core.process import append_log, clear_log, set_running, set_process
from core.backup import get_pg_bin_path

PG_BIN = get_pg_bin_path() or r"C:\Program Files\PostgreSQL\11\bin"
PSQL = os.path.join(PG_BIN, "psql.exe")
PG_RESTORE = os.path.join(PG_BIN, "pg_restore.exe")

# Regex para validar versões: apenas dígitos e pontos, pelo menos um dígito
_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")


def validate_upgrade_inputs(data: dict) -> str | None:
    """Valida os parâmetros de upgrade.

    Retorna None se válido, ou uma mensagem de erro descritiva se inválido.
    Verifica:
        - ssh_host, ssh_user, ssh_password são strings não-vazias
        - old_version e new_version contêm apenas dígitos e pontos
    """
    # Validar campos de conexão SSH
    for field in ("ssh_host", "ssh_user", "ssh_password"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"Erro: o campo '{field}' é obrigatório e não pode ser vazio"

    # Validar versões
    for field in ("old_version", "new_version"):
        value = data.get(field)
        if not isinstance(value, str) or not _VERSION_RE.match(value):
            return f"Erro: o campo '{field}' deve conter apenas dígitos e pontos (ex: '14' ou '16.1')"

    return None


def open_ssh_connection(ssh_host: str, ssh_user: str, ssh_password: str,
                        ssh_port: int = 22) -> paramiko.SSHClient:
    """Creates and returns a connected paramiko SSHClient.

    Raises paramiko.SSHException or socket.error on failure.
    Uses AutoAddPolicy for host key verification (matches transfer.py pattern).
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ssh_host, port=ssh_port, username=ssh_user, password=ssh_password)
    return client


def run_remote_command(client: paramiko.SSHClient, command: str,
                       ssh_password: str, log_fn: callable) -> int:
    """Executes a sudo command on the remote server via paramiko.

    Uses sudo -S pattern: pipes ssh_password via stdin.
    Streams stdout/stderr line-by-line to log_fn.
    Returns the command exit code.
    """
    stdin, stdout, stderr = client.exec_command(f"sudo -S {command}")
    # Envia senha para sudo via stdin (-S flag)
    stdin.write(ssh_password + "\n")
    stdin.flush()

    # Stream stdout line-by-line
    for line in stdout:
        log_fn(line)

    # Stream stderr line-by-line
    for line in stderr:
        log_fn(line)

    exit_code = stdout.channel.recv_exit_status()
    return exit_code


def ensure_pgdg_repo(client: paramiko.SSHClient, ssh_password: str,
                     log_fn: callable) -> bool:
    """Ensures the PostgreSQL PGDG apt repository is configured on the remote server.

    Checks if /etc/apt/sources.list.d/pgdg.list exists. If not, imports the GPG key
    and adds the repository. This enables installation of any PostgreSQL version.

    Returns True on success (or if repo already exists), False on failure.
    """
    # Verificar se o repositório já existe
    log_fn("Verificando repositório PGDG...\n")
    exit_code = run_remote_command(
        client, "test -f /etc/apt/sources.list.d/pgdg.list",
        ssh_password, log_fn
    )

    if exit_code == 0:
        log_fn("Repositório PGDG já configurado.\n")
        return True

    log_fn("Repositório PGDG não encontrado. Configurando...\n")

    # Instalar dependências necessárias (curl, gnupg, lsb-release)
    log_fn("Executando: sudo apt-get install -y curl ca-certificates gnupg lsb-release\n")
    exit_code = run_remote_command(
        client,
        "apt-get install -y curl ca-certificates gnupg lsb-release",
        ssh_password, log_fn
    )
    if exit_code != 0:
        log_fn(f"Erro: instalação de dependências falhou (código {exit_code})\n")
        return False

    # Importar chave GPG do PostgreSQL
    log_fn("Importando chave GPG do PostgreSQL...\n")
    gpg_cmd = (
        "curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc "
        "| gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg"
    )
    exit_code = run_remote_command(client, gpg_cmd, ssh_password, log_fn)
    if exit_code != 0:
        log_fn(f"Erro: importação da chave GPG falhou (código {exit_code})\n")
        return False

    # Adicionar repositório PGDG
    log_fn("Adicionando repositório PGDG...\n")
    repo_cmd = (
        'sh -c \'echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] '
        'http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" '
        '> /etc/apt/sources.list.d/pgdg.list\''
    )
    exit_code = run_remote_command(client, repo_cmd, ssh_password, log_fn)
    if exit_code != 0:
        log_fn(f"Erro: adição do repositório PGDG falhou (código {exit_code})\n")
        return False

    log_fn("Repositório PGDG configurado com sucesso.\n")
    return True


def install_pg_remote(client: paramiko.SSHClient, target_version: str,
                      ssh_password: str, log_fn: callable) -> bool:
    """Installs PostgreSQL target_version on the remote server.

    Steps:
        1. Ensure PGDG repository is configured
        2. sudo -S apt-get update
        3. sudo -S apt-get install -y postgresql-{target_version}

    Returns True on success, False on failure.
    Logs all output via log_fn.
    """
    # Fase 0: Garantir repositório PGDG
    if not ensure_pgdg_repo(client, ssh_password, log_fn):
        return False

    # Fase 1: apt-get update
    log_fn("Executando: sudo apt-get update\n")
    exit_code = run_remote_command(client, "apt-get update", ssh_password, log_fn)
    if exit_code != 0:
        log_fn(f"Erro: apt-get update falhou (código {exit_code})\n")
        return False

    # Fase 2: apt-get install
    log_fn(f"Executando: sudo apt-get install -y postgresql-{target_version}\n")
    exit_code = run_remote_command(
        client, f"apt-get install -y postgresql-{target_version}",
        ssh_password, log_fn
    )
    if exit_code != 0:
        log_fn(f"Erro: instalação do PostgreSQL {target_version} falhou (código {exit_code})\n")
        return False

    log_fn(f"PostgreSQL {target_version} instalado com sucesso.\n")
    return True


def run_pg_upgradecluster(client: paramiko.SSHClient, old_version: str,
                          new_version: str, ssh_password: str,
                          log_fn: callable) -> int:
    """Executes pg_upgradecluster on the remote server.

    Command: sudo -S pg_upgradecluster -v {new_version} {old_version} main
    Streams output to log_fn.
    Returns exit code.
    """
    log_fn(f"Executando: sudo pg_upgradecluster -v {new_version} {old_version} main\n")
    exit_code = run_remote_command(
        client,
        f"pg_upgradecluster -v {new_version} {old_version} main",
        ssh_password,
        log_fn
    )
    return exit_code


def run_restore(data):
    clear_log()
    set_running(True)

    try:
        os.environ["PGPASSWORD"] = data.get("password", "")
        # Será limpo no finally para não vazar para outros processos
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        restore_type = data.get("restore_type", "normal")

        if restore_type == "normal" and data.get("backupfile"):
            base_dir = os.path.dirname(data["backupfile"])
            log_dir = os.path.join(base_dir, "logs_restore")
        else:
            log_dir = os.path.join(os.path.abspath("."), "logs_restore")

        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"restore_{timestamp}.log")

        with open(log_file, "w", encoding="utf-8") as logfile:

            def sync_log(msg):
                append_log(msg)
                logfile.write(msg)
                logfile.flush()

            if restore_type == "upgrade":
                # --- Validação de inputs ---
                error = validate_upgrade_inputs(data)
                if error:
                    sync_log(f"{error}\n")
                    set_running(False)
                    return

                ssh_host = data["ssh_host"]
                ssh_user = data["ssh_user"]
                ssh_password = data["ssh_password"]
                old_version = data["old_version"]
                new_version = data["new_version"]
                target = "PG_UPGRADE"

                start_time = datetime.datetime.now()

                # --- Log de início ---
                sync_log("\n=== INÍCIO DO PROCESSO ===\n")
                sync_log(f"Início: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                sync_log(f"Tipo: upgrade\n")
                sync_log(f"Destino: {ssh_user}@{ssh_host}\n\n")

                # --- Fase: Conexão SSH ---
                sync_log("=== FASE: CONEXÃO SSH ===\n")
                sync_log(f"Conectando via SSH em {ssh_host}:22...\n")

                try:
                    client = open_ssh_connection(ssh_host, ssh_user, ssh_password)
                except Exception as e:
                    sync_log(f"Erro: falha na conexão SSH com {ssh_host}: {str(e)}\n")
                    add_history("UPGRADE", target, "FAIL")
                    set_running(False)
                    return

                sync_log("Conexão estabelecida com sucesso.\n\n")

                try:
                    # --- Fase: Instalação PostgreSQL (condicional) ---
                    if data.get("install_pg", True):
                        sync_log(f"=== FASE: INSTALAÇÃO PostgreSQL {new_version} ===\n")
                        success = install_pg_remote(client, new_version, ssh_password, sync_log)
                        if not success:
                            add_history("UPGRADE", target, "FAIL")
                            end_time = datetime.datetime.now()
                            duration = str(end_time - start_time)
                            sync_log("\n=== FIM ===\n")
                            sync_log(f"Fim: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                            sync_log(f"Duração: {duration}\n")
                            sync_log("Status: FAIL\n")
                            set_running(False)
                            return

                    # --- Fase: Upgrade do cluster ---
                    sync_log("\n=== FASE: UPGRADE DO CLUSTER ===\n")
                    exit_code = run_pg_upgradecluster(client, old_version, new_version, ssh_password, sync_log)

                    end_time = datetime.datetime.now()
                    duration = str(end_time - start_time)
                    status = "SUCCESS" if exit_code == 0 else "FAIL"
                    add_history("UPGRADE", target, status)

                    sync_log("\n=== FIM ===\n")
                    sync_log(f"Fim: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    sync_log(f"Duração: {duration}\n")
                    sync_log(f"Status: {status}\n")

                finally:
                    client.close()

                set_running(False)
                return

            else:
                if data["backupfile"].endswith(".backup") or data["backupfile"].endswith(".backup_postgresql"):
                    cmd = [
                        PG_RESTORE,
                        "-h", data["host"],
                        "-p", data["port"],
                        "-U", data["user"],
                        "-d", data["database"],
                        "--clean",
                        "--if-exists",
                        "--no-owner",
                        "--no-privileges",
                        "-v",
                        data["backupfile"]
                    ]
                else:
                    cmd = [
                        PSQL,
                        "-h", data["host"],
                        "-p", data["port"],
                        "-U", data["user"],
                        "-d", data["database"],
                        "-f", data["backupfile"]
                    ]

                target = data.get("database", "RESTORE")

            # ================= EXEC =================
            start_time = datetime.datetime.now()

            sync_log("\n=== INÍCIO DO PROCESSO ===\n")
            sync_log(f"Início: {start_time}\n")
            sync_log(f"Tipo: {restore_type}\n")
            sync_log(f"Comando a ser executado: {' '.join(cmd)}\n\n")

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True
                )

                set_process(proc)

                for line in proc.stdout:
                    sync_log(line)

                proc.wait()

                end_time = datetime.datetime.now()
                duration = str(end_time - start_time)

                sync_log("\n=== FIM ===\n")
                sync_log(f"Fim: {end_time}\n")
                sync_log(f"Duração: {duration}\n")

                status = "SUCCESS" if proc.returncode == 0 else "FAIL"
                add_history(restore_type.upper(), target, status)

            except Exception as e:
                sync_log(f"\nERRO NA EXECUÇÃO DO SUBPROCESS:\n{str(e)}\n")
                add_history(restore_type.upper(), target, "FAIL")

    except Exception as e:
        append_log(f"\nERRO FATAL NA PREPARAÇÃO DO RESTORE:\n{str(e)}\n")
        add_history("RESTORE", "ERRO", "FAIL")

    finally:
        os.environ.pop("PGPASSWORD", None)
        set_running(False)