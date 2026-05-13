"""Fluxo de restore para SQL Server — transferência do .bak + restore remoto."""
import os
import datetime

from core.db import add_history
from core.process import append_log, clear_log, set_running
from core.mssql_utils import run_restore_remote
from core.transfer import transfer_sftp, chmod_remote


def upload_sftp(ssh_host: str, ssh_user: str, ssh_password: str,
                local_path: str, remote_dir: str, log_fn=None, ssh_port: int = 22) -> str:
    """Envia arquivo local para o servidor remoto via SFTP. Retorna caminho remoto."""
    import paramiko

    filename = os.path.basename(local_path)
    remote_path = f"{remote_dir.rstrip('/')}/{filename}"

    if log_fn:
        log_fn(f"Conectando via SFTP em {ssh_host}:{ssh_port}...\n")

    transport = paramiko.Transport((ssh_host, ssh_port))
    transport.connect(username=ssh_user, password=ssh_password)

    try:
        sftp = paramiko.SFTPClient.from_transport(transport)

        file_size = os.path.getsize(local_path)
        last_pct = [-1]

        def progress(bytes_so_far, total):
            pct = int(bytes_so_far * 100 / total) if total > 0 else 0
            if pct % 10 == 0 and pct != last_pct[0]:
                last_pct[0] = pct
                if log_fn:
                    log_fn(f"Enviando... {pct}%\n")

        if log_fn:
            log_fn(f"Enviando {filename} ({file_size / 1024 / 1024:.1f} MB) para {remote_path}...\n")

        sftp.put(local_path, remote_path, callback=progress)
        sftp.close()

        if log_fn:
            log_fn(f"Upload concluído: {remote_path}\n")

        return remote_path
    finally:
        transport.close()


def upload_smb(local_path: str, remote_unc_dir: str, log_fn=None) -> str:
    """Copia arquivo local para caminho UNC remoto. Retorna caminho UNC do arquivo."""
    import shutil

    filename = os.path.basename(local_path)
    remote_path = os.path.join(remote_unc_dir, filename)

    if log_fn:
        log_fn(f"Copiando {filename} para {remote_unc_dir}...\n")

    file_size = os.path.getsize(local_path)
    if log_fn:
        log_fn(f"Tamanho: {file_size / 1024 / 1024:.1f} MB\n")

    shutil.copy2(local_path, remote_path)

    if log_fn:
        log_fn(f"Cópia concluída: {remote_path}\n")

    return remote_path


def run_restore_mssql(data: dict):
    """Executa o fluxo completo de restore SQL Server."""
    clear_log()
    set_running(True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(os.path.abspath("."), "logs_restore")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"restore_mssql_{timestamp}.log")

    try:
        with open(log_file, "w", encoding="utf-8") as logfile:

            def sync_log(msg):
                append_log(msg)
                logfile.write(msg)
                logfile.flush()

            sync_log("\n=== INÍCIO DO RESTORE SQL SERVER ===\n")
            sync_log(f"Início: {datetime.datetime.now()}\n")
            sync_log(f"Servidor DB: {data['host']}:{data['port']}\n")
            sync_log(f"Database: {data['database']}\n\n")

            local_file = data.get("backupfile", "")
            database = data.get("database", "")
            transfer_mode = data.get("transfer_mode", "none")
            remote_restore_dir = data.get("remote_restore_dir", "")

            # Validações
            if not local_file or not os.path.exists(local_file):
                sync_log(f"Erro: Arquivo de backup não encontrado: {local_file}\n")
                add_history("RESTORE_MSSQL", database or "ERRO", "FAIL")
                return

            if not database:
                sync_log("Erro: Nome do banco de dados não informado.\n")
                add_history("RESTORE_MSSQL", "ERRO", "FAIL")
                return

            start_time = datetime.datetime.now()
            remote_bak_path = ""

            try:
                # 1. Transferir .bak para o servidor de banco
                if transfer_mode == "sftp":
                    sync_log("=== TRANSFERINDO .BAK PARA O SERVIDOR (SFTP) ===\n")

                    remote_bak_path = upload_sftp(
                        ssh_host=data["host"],
                        ssh_user=data.get("transfer_user", ""),
                        ssh_password=data.get("transfer_password", ""),
                        local_path=local_file,
                        remote_dir=remote_restore_dir,
                        log_fn=sync_log,
                        ssh_port=int(data.get("transfer_port", 22))
                    )

                    # chmod 777 para garantir que o SQL Server consiga ler
                    chmod_remote(
                        ssh_host=data["host"],
                        ssh_user=data.get("transfer_user", ""),
                        ssh_password=data.get("transfer_password", ""),
                        remote_path=remote_bak_path,
                        ssh_port=int(data.get("transfer_port", 22)),
                        log_fn=sync_log
                    )

                elif transfer_mode == "smb":
                    sync_log("=== TRANSFERINDO .BAK PARA O SERVIDOR (SMB) ===\n")

                    # Monta UNC: \\host\c$\path
                    db_host = data["host"]
                    if len(remote_restore_dir) >= 2 and remote_restore_dir[1] == ":":
                        drive_letter = remote_restore_dir[0].lower()
                        rest = remote_restore_dir[2:]
                        unc_dir = f"\\\\{db_host}\\{drive_letter}${rest}"
                    else:
                        unc_dir = f"\\\\{db_host}\\{remote_restore_dir}"

                    upload_smb(
                        local_path=local_file,
                        remote_unc_dir=unc_dir,
                        log_fn=sync_log
                    )

                    # O path que o SQL Server vê é o local (C:\...)
                    filename = os.path.basename(local_file)
                    remote_bak_path = f"{remote_restore_dir.rstrip(chr(92))}\\{filename}"

                else:
                    # Sem transferência — assume que o arquivo já está acessível pelo SQL Server
                    sync_log("Transferência desabilitada. Usando caminho local como path do servidor.\n")
                    remote_bak_path = local_file

                # 2. Executar RESTORE DATABASE
                sync_log("\n=== EXECUTANDO RESTORE ===\n")
                success = run_restore_remote(
                    host=data["host"],
                    port=data["port"],
                    user=data["user"],
                    password=data["password"],
                    database=database,
                    remote_bak_path=remote_bak_path,
                    log_fn=sync_log
                )

                end_time = datetime.datetime.now()
                duration = str(end_time - start_time)
                sync_log(f"\n=== FIM ===\n")
                sync_log(f"Fim: {end_time}\n")
                sync_log(f"Duração: {duration}\n")

                status = "SUCCESS" if success else "FAIL"
                add_history("RESTORE_MSSQL", database, status)

            except Exception as e:
                sync_log(f"\nERRO: {str(e)}\n")
                add_history("RESTORE_MSSQL", database or "ERRO", "FAIL")

    except Exception as e:
        append_log(f"\nERRO FATAL: {str(e)}\n")
        add_history("RESTORE_MSSQL", "ERRO", "FAIL")

    finally:
        set_running(False)
