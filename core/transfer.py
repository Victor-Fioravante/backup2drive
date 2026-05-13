"""Transferência de arquivos entre servidores — SFTP (Linux) e SMB/UNC (Windows).
Inclui browsing remoto de diretórios."""
import os
import shutil
import stat
from dataclasses import dataclass


@dataclass
class RemoteEntry:
    """Representa um item (arquivo ou pasta) em um diretório remoto."""
    name: str
    is_dir: bool
    size: int = 0  # bytes, 0 para diretórios
    path: str = ""  # caminho completo


def browse_sftp(ssh_host: str, ssh_user: str, ssh_password: str,
                remote_path: str, ssh_port: int = 22) -> list[RemoteEntry]:
    """Lista o conteúdo de um diretório remoto via SFTP."""
    import paramiko

    transport = paramiko.Transport((ssh_host, ssh_port))
    transport.connect(username=ssh_user, password=ssh_password)

    try:
        sftp = paramiko.SFTPClient.from_transport(transport)
        entries = []

        for attr in sftp.listdir_attr(remote_path):
            is_dir = stat.S_ISDIR(attr.st_mode) if attr.st_mode else False
            full_path = f"{remote_path.rstrip('/')}/{attr.filename}"
            entries.append(RemoteEntry(
                name=attr.filename,
                is_dir=is_dir,
                size=attr.st_size if not is_dir else 0,
                path=full_path
            ))

        # Ordena: pastas primeiro, depois arquivos
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        sftp.close()
        return entries
    finally:
        transport.close()


def browse_smb(unc_path: str) -> list[RemoteEntry]:
    """Lista o conteúdo de um diretório via caminho UNC (Windows)."""
    entries = []

    if not os.path.exists(unc_path):
        raise FileNotFoundError(f"Caminho não encontrado: {unc_path}")

    for item in os.listdir(unc_path):
        full_path = os.path.join(unc_path, item)
        is_dir = os.path.isdir(full_path)
        size = os.path.getsize(full_path) if not is_dir else 0
        entries.append(RemoteEntry(
            name=item,
            is_dir=is_dir,
            size=size,
            path=full_path
        ))

    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


def chmod_remote(ssh_host: str, ssh_user: str, ssh_password: str,
                 remote_path: str, ssh_port: int = 22, log_fn=None):
    """Executa sudo chmod 777 no arquivo remoto via SSH para garantir permissão de leitura."""
    import paramiko

    if log_fn:
        log_fn(f"Ajustando permissões: sudo chmod 777 {remote_path}\n")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ssh_host, port=ssh_port, username=ssh_user, password=ssh_password)

    try:
        stdin, stdout, stderr = client.exec_command(f"sudo -S chmod 777 '{remote_path}'")
        # Envia senha para sudo via stdin (-S flag)
        stdin.write(ssh_password + "\n")
        stdin.flush()
        exit_code = stdout.channel.recv_exit_status()

        if exit_code != 0:
            err = stderr.read().decode().strip()
            if log_fn:
                log_fn(f"Aviso: chmod retornou código {exit_code}: {err}\n")
        else:
            if log_fn:
                log_fn("Permissões ajustadas com sucesso.\n")
    finally:
        client.close()


def transfer_sftp(ssh_host: str, ssh_user: str, ssh_password: str,
                  remote_path: str, local_dir: str, log_fn=None, ssh_port: int = 22) -> str:
    """Transfere arquivo do servidor remoto via SFTP. Retorna caminho local."""
    import paramiko

    filename = os.path.basename(remote_path)
    local_path = os.path.join(local_dir, filename)

    if log_fn:
        log_fn(f"Conectando via SFTP em {ssh_host}:{ssh_port}...\n")

    transport = paramiko.Transport((ssh_host, ssh_port))
    transport.connect(username=ssh_user, password=ssh_password)

    try:
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Progresso
        remote_size = sftp.stat(remote_path).st_size
        transferred = [0]
        last_pct = [-1]

        def progress(bytes_so_far, total):
            transferred[0] = bytes_so_far
            pct = int(bytes_so_far * 100 / total) if total > 0 else 0
            if pct % 10 == 0 and pct != last_pct[0]:
                last_pct[0] = pct
                if log_fn:
                    log_fn(f"Transferindo... {pct}%\n")

        if log_fn:
            log_fn(f"Baixando {filename} ({remote_size / 1024 / 1024:.1f} MB)...\n")

        sftp.get(remote_path, local_path, callback=progress)
        sftp.close()

        if log_fn:
            log_fn(f"Transferência concluída: {local_path}\n")

        return local_path
    finally:
        transport.close()


def transfer_smb(remote_unc_path: str, local_dir: str, log_fn=None) -> str:
    """Copia arquivo de um caminho UNC (\\\\servidor\\share\\arquivo.bak) para diretório local."""
    filename = os.path.basename(remote_unc_path)
    local_path = os.path.join(local_dir, filename)

    if log_fn:
        log_fn(f"Copiando de {remote_unc_path}...\n")

    if not os.path.exists(remote_unc_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {remote_unc_path}")

    file_size = os.path.getsize(remote_unc_path)
    if log_fn:
        log_fn(f"Tamanho: {file_size / 1024 / 1024:.1f} MB\n")

    shutil.copy2(remote_unc_path, local_path)

    if log_fn:
        log_fn(f"Cópia concluída: {local_path}\n")

    return local_path
