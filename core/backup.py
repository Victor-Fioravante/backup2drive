import os
import sys
import subprocess
import datetime
import shutil
import zipfile
import urllib.request
import tempfile

from core.db import add_history
from core.process import append_log, clear_log, set_running, set_process
from core.services.google_drive_service import GoogleDriveService
from core.services.mitte_service import send_mitte_email

PG_INSTALLER_URL = "https://ftp.postgresql.org/pub/pgadmin/pgadmin4/v9.14/windows/pgadmin4-9.14-x64.exe"
PG_INSTALL_DIR = r"C:\Program Files\pgAdmin 4"


def get_pg_bin_path():
    # 1. Binarios embutidos no exe (PyInstaller)
    if getattr(sys, 'frozen', False):
        embedded = os.path.join(sys._MEIPASS, 'pgbin')
        if os.path.exists(os.path.join(embedded, 'pg_dump.exe')):
            return embedded

    # 2. Tenta achar pelo PATH do Windows
    pg_dump_path = shutil.which('pg_dump.exe')
    if pg_dump_path:
        return os.path.dirname(pg_dump_path)

    # 3. Varredura nas pastas comuns
    base_dirs = [
        r'C:\Program Files\PostgreSQL',
        r'C:\Program Files\pgAdmin 4',
        r'C:\Program Files (x86)\PostgreSQL',
        r'C:\Program Files (x86)\pgAdmin 4',
        r'C:\Program Files\pgAdmin III',
        r'C:\Program Files (x86)\pgAdmin III',
    ]

    pastas_encontradas = []
    for base in base_dirs:
        if os.path.exists(base):
            for root, dirs, files in os.walk(base):
                if 'pg_dump.exe' in files:
                    pastas_encontradas.append(root)

    if pastas_encontradas:
        pastas_encontradas.sort(reverse=True)
        return pastas_encontradas[0]

    return None


def install_pg_client(log_fn):
    log_fn("\n=== pg_dump.exe NAO ENCONTRADO — INICIANDO INSTALACAO DO pgAdmin 4 ===\n")

    installer_path = os.path.join(tempfile.gettempdir(), "pgadmin4_installer.exe")

    if not os.path.exists(installer_path):
        log_fn(f"Baixando instalador de {PG_INSTALLER_URL}...\n")
        try:
            ultimo_pct = [-1]
            def progresso(count, block_size, total_size):
                if total_size > 0:
                    pct = min(count * block_size * 100 // total_size, 100)
                    if pct % 10 == 0 and pct != ultimo_pct[0]:
                        ultimo_pct[0] = pct
                        log_fn(f"Baixando... {pct}%\n")

            urllib.request.urlretrieve(PG_INSTALLER_URL, installer_path, reporthook=progresso)
            log_fn("\nDownload concluido.\n")
        except Exception as e:
            raise RuntimeError(f"Falha ao baixar o instalador do pgAdmin 4: {e}")
    else:
        log_fn("Instalador ja encontrado em cache, pulando download.\n")

    log_fn("Instalando pgAdmin 4 (modo silencioso)...\n")
    cmd = [
        installer_path,
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    for line in proc.stdout:
        log_fn(line)
    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"Instalacao falhou com codigo {proc.returncode}")

    log_fn("Instalacao concluida com sucesso!\n")

    pg_bin = get_pg_bin_path()
    log_fn(f"Procurando pg_dump.exe apos instalacao...\n")
    if not pg_bin:
        pg_bin = os.path.join(PG_INSTALL_DIR, "runtime")
        log_fn(f"pg_dump nao encontrado na varredura, usando fallback: {pg_bin}\n")
    else:
        log_fn(f"pg_dump encontrado em: {pg_bin}\n")
    return pg_bin


def _dump_database(pg_dump, data, database, output_file, sync_log):
    cmd = [
        pg_dump,
        "-h", data["host"], "-p", data["port"], "-U", data["user"],
        "-d", database, "-F", "c", "-b", "-v", "-f", output_file
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    set_process(proc)
    for line in proc.stdout:
        sync_log(line)
    proc.wait()
    return proc.returncode


def run_backup(data):
    clear_log()
    set_running(True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_type = data["type"]

    os.makedirs(data["backupdir"], exist_ok=True)
    log_dir = os.path.join(data["backupdir"], "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"backup_{timestamp}.log")

    os.environ["PGPASSWORD"] = data["password"]

    try:
        with open(log_file, "w", encoding="utf-8") as logfile:

            def sync_log(msg):
                append_log(msg)
                logfile.write(msg)
                logfile.flush()

            sync_log("\n=== INÍCIO DO BACKUP ===\n")
            sync_log(f"Início: {datetime.datetime.now()}\n")
            sync_log(f"Destino: {data['backupdir']}\n\n")

            pg_bin = get_pg_bin_path()
            if not pg_bin:
                pg_bin = install_pg_client(sync_log)

            pg_dump = os.path.join(pg_bin, "pg_dump.exe")
            pg_dumpall = os.path.join(pg_bin, "pg_dumpall.exe")

            # Resolve lista de databases
            databases_raw = data.get("databases") or data.get("database", "")
            if isinstance(databases_raw, list):
                databases = databases_raw
            else:
                databases = [d.strip() for d in databases_raw.split(",") if d.strip()]

            multiplo = backup_type == "dump" and len(databases) > 1

            start_time = datetime.datetime.now()
            output_files = []
            status_geral = "SUCCESS"

            try:
                if backup_type == "dumpall":
                    output_file = os.path.join(data["backupdir"], f"cluster_{timestamp}.sql")
                    cmd = [
                        pg_dumpall,
                        "-h", data["host"], "-p", data["port"], "-U", data["user"],
                        "-v", "-f", output_file
                    ]
                    sync_log(f"Destino: {output_file}\n\n")
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    set_process(proc)
                    for line in proc.stdout:
                        sync_log(line)
                    proc.wait()
                    if proc.returncode == 0:
                        output_files.append((output_file, os.path.basename(output_file)))
                    else:
                        status_geral = "FAIL"
                    target = "CLUSTER"

                else:
                    target = ", ".join(databases)
                    for db in databases:
                        linha = data.get("linha_produto", "")
                        nome_arquivo = f"{data['drive_folder']}_{linha}_{db}" if linha else f"{data['drive_folder']}_{db}"
                        output_file = os.path.join(data["backupdir"], f"{nome_arquivo}_{timestamp}.backup")
                        sync_log(f"\n--- Backup de: {db} ---\n")
                        sync_log(f"Destino: {output_file}\n")
                        rc = _dump_database(pg_dump, data, db, output_file, sync_log)
                        if rc == 0:
                            output_files.append((output_file, f"{nome_arquivo}.backup"))
                            sync_log(f"Backup de {db} concluído com sucesso.\n")
                        else:
                            status_geral = "FAIL"
                            sync_log(f"Erro no backup de {db} (código {rc}).\n")

                end_time = datetime.datetime.now()
                duration = str(end_time - start_time)
                sync_log("\n=== FIM DO BACKUP LOCAL ===\n")
                sync_log(f"Fim: {end_time}\n")
                sync_log(f"Duração: {duration}\n")

                # Compacta se multiplas bases
                upload_file = output_files[0][0] if output_files else None
                linha = data.get("linha_produto", "")
                folder_name = os.path.basename(os.path.normpath(data["backupdir"]))

                if multiplo and output_files:
                    zip_nome = f"{data['drive_folder']}_{linha}" if linha else data['drive_folder']
                    zip_path = os.path.join(data["backupdir"], f"{zip_nome}_{timestamp}.zip")
                    sync_log(f"\nCompactando {len(output_files)} arquivo(s) em: {zip_path}\n")
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for caminho, nome_zip in output_files:
                            zf.write(caminho, nome_zip)
                    sync_log("Compactação concluída.\n")
                    upload_file = zip_path
                    upload_filename = f"{zip_nome}.zip"
                elif upload_file and not multiplo:
                    _, nome_zip = output_files[0]
                    upload_filename = nome_zip
                    if backup_type == "dumpall":
                        upload_filename = (f"{data['drive_folder']}_{linha}_CLUSTER" if linha else f"{data['drive_folder']}_CLUSTER") + ".sql"
                else:
                    upload_filename = folder_name

                if status_geral == "SUCCESS" and upload_file and data.get("drive_folder") and data.get("drive_subfolder"):
                    sync_log("\n=== INICIAR UPLOAD PARA O GOOGLE DRIVE ===\n")
                    try:
                        drive_service = GoogleDriveService()
                        sync_log(f"A criar estrutura de pastas e enviar: {upload_filename}...\n")

                        file_id, folder_link = drive_service.upload_backup_custom(
                            file_path=upload_file,
                            folder_level_1=data["drive_folder"],
                            folder_level_2=data["drive_subfolder"],
                            custom_file_name=upload_filename,
                            client_email=data.get("client_email")
                        )
                        sync_log(f"Upload concluído com sucesso! ID no Drive: {file_id}\n")
                        if not folder_link:
                            sync_log("Aviso: Não foi possível compartilhar a pasta (domínio bloqueado pelo administrador). O link do Drive não estará disponível no e-mail.\n")

                        tech_email = None
                        try:
                            tech_email = drive_service.get_authenticated_user_email()
                            sync_log(f"Técnico logado: {tech_email}\n")
                        except Exception as e:
                            sync_log(f"Aviso: Não foi possível obter o e-mail do técnico: {str(e)}\n")

                        client_email = data.get("client_email")
                        if client_email:
                            sync_log(f"A enviar link via Mitte Pro para {client_email}...\n")
                            try:
                                resposta_mitte = send_mitte_email(
                                    recipient_email=client_email,
                                    client_name=data["drive_folder"],
                                    folder_link=folder_link,
                                    file_name=upload_filename,
                                    template_type=data.get("template_type", "cancelamento")
                                )
                                sync_log(f"E-mail Mitte Pro disparado! Resposta: {resposta_mitte}\n")

                                if 'error' not in str(resposta_mitte).lower():
                                    audit_file = os.path.join(log_dir, f"comprovante_envio_{timestamp}.txt")
                                    data_envio = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                                    template_type = data.get("template_type", "cancelamento")

                                    if template_type == "pontual":
                                        corpo_log = (
                                            f"De:  Alterdata Nuvem <suporte_nuvem_backup@alterdata.com.br>\n"
                                            f"Para:   <{client_email}>\n"
                                            f"Enviado em:  {data_envio}\n\n"
                                            f"=========================================================\n"
                                            f"CORPO DO E-MAIL ENVIADO\n"
                                            f"=========================================================\n"
                                            f"Seu Backup está pronto!\n\n"
                                            f"Conforme solicitado, informamos que o processo de backup da base de dados do seu sistema em Nuvem foi concluído com sucesso.\n\n"
                                            f"Acesse o arquivo através do link abaixo:\n"
                                            f"LINK DO BACKUP: {folder_link}\n\n"
                                            f"Atenção: Por motivos de segurança e espaço, o link para download ficará disponível por apenas 7 dias. Recomendamos que você baixe e guarde o arquivo em um local seguro o quanto antes.\n"
                                            f"========================================================="
                                        )
                                    else:
                                        corpo_log = (
                                            f"De:  Alterdata Nuvem <suporte_nuvem_cancelamento@alterdata.com.br>\n"
                                            f"Para:   <{client_email}>\n"
                                            f"Enviado em:  {data_envio}\n\n"
                                            f"=========================================================\n"
                                            f"CORPO DO E-MAIL ENVIADO\n"
                                            f"=========================================================\n"
                                            f"Prezado(a) cliente {data['drive_folder']},\n\n"
                                            f"Em razão da rescisão contratual dos serviços de Nuvem/hospedagem de dados, informamos que os acessos a estes serviços, nos termos do contrato celebrado, foram bloqueados.\n\n"
                                            f"O backup de sua base de dados foi disponibilizado no link abaixo e enviado exclusivamente a este e-mail vinculado ao seu contrato. Você deverá resgatá-lo no prazo improrrogável de até 30 (trinta) dias contados da data de envio deste e-mail.\n\n"
                                            f"Alertamos que, após o prazo estipulado, os dados serão permanentemente excluídos de nossos servidores, observando as diretrizes de proteção e segurança de dados.\n\n"
                                            f"LINK DO BACKUP: {folder_link}\n\n"
                                            f"IMPORTANTE: Este link é compartilhado e mantido através dos padrões de segurança do Google, devendo ser acessado através de um e-mail autenticado como Conta Google. Em caso de dificuldades no acesso, nos contate imediatamente.\n"
                                            f"========================================================="
                                        )

                                    with open(audit_file, "w", encoding="utf-8") as f_audit:
                                        f_audit.write(corpo_log)
                                    sync_log(f"Comprovante de envio gerado: {audit_file}\n")
                                else:
                                    sync_log("Aviso: A API retornou erro. O e-mail não foi entregue.\n")
                            except Exception as email_err:
                                sync_log(f"Aviso: Erro ao enviar e-mail: {str(email_err)}\n")

                    except Exception as e:
                        sync_log(f"Erro durante o upload para o Drive: {str(e)}\n")
                        status_geral = "PARTIAL_SUCCESS"

                add_history("BACKUP", target, status_geral)

            except Exception as e:
                sync_log(f"\nErro fatal: {str(e)}\n")
                add_history("BACKUP", data.get("database", "ERRO"), "FAIL")

    finally:
        os.environ.pop("PGPASSWORD", None)
        set_running(False)