"""Fluxo de backup para SQL Server — backup remoto + transferência + upload Drive."""
import os
import datetime
import zipfile

from core.db import add_history
from core.process import append_log, clear_log, set_running
from core.mssql_utils import run_backup_remote
from core.transfer import transfer_sftp, transfer_smb, chmod_remote
from core.services.google_drive_service import GoogleDriveService
from core.services.mitte_service import send_mitte_email


def run_backup_mssql(data: dict):
    """Executa o fluxo completo de backup SQL Server."""
    clear_log()
    set_running(True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    local_dir = data.get("backupdir", "")
    os.makedirs(local_dir, exist_ok=True)
    log_dir = os.path.join(local_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"backup_mssql_{timestamp}.log")

    try:
        with open(log_file, "w", encoding="utf-8") as logfile:

            def sync_log(msg):
                append_log(msg)
                logfile.write(msg)
                logfile.flush()

            sync_log("\n=== INÍCIO DO BACKUP SQL SERVER ===\n")
            sync_log(f"Início: {datetime.datetime.now()}\n")
            sync_log(f"Servidor DB: {data['host']}:{data['port']}\n\n")

            # Resolve lista de databases
            databases_raw = data.get("databases") or data.get("database", "")
            if isinstance(databases_raw, list):
                databases = databases_raw
            else:
                databases = [d.strip() for d in databases_raw.split(",") if d.strip()]

            remote_bak_dir = data.get("remote_bak_dir", "C:\\SQLBackups")
            # Detecta separador: se o path usa / é Linux, senão Windows
            if "/" in remote_bak_dir and "\\" not in remote_bak_dir:
                path_sep = "/"
            else:
                path_sep = "\\"
            start_time = datetime.datetime.now()
            local_files = []
            status_geral = "SUCCESS"

            for db in databases:
                sync_log(f"\n--- Backup de: [{db}] ---\n")

                try:
                    # 1. Executa backup no servidor remoto
                    linha = data.get("linha_produto", "")
                    drive_folder = data.get("drive_folder", "")
                    nome_arquivo = f"{drive_folder}_{linha}_{db}" if linha else f"{drive_folder}_{db}"
                    bak_filename = f"{nome_arquivo}_{timestamp}.bak"
                    remote_bak_path = f"{remote_bak_dir.rstrip(path_sep)}{path_sep}{bak_filename}"
                    remote_bak_path = run_backup_remote(
                        host=data["host"],
                        port=data["port"],
                        user=data["user"],
                        password=data["password"],
                        database=db,
                        remote_path=remote_bak_path,
                        log_fn=sync_log
                    )

                    # 2. Transferência (opcional)
                    transfer_mode = data.get("transfer_mode", "none")

                    if transfer_mode == "sftp":
                        sync_log("Transferindo via SFTP...\n")
                        # No Linux o path remoto usa /
                        remote_linux_path = remote_bak_path.replace("\\", "/")

                        # Ajusta permissões antes de transferir
                        chmod_remote(
                            ssh_host=data.get("transfer_host", data["host"]),
                            ssh_user=data.get("transfer_user", ""),
                            ssh_password=data.get("transfer_password", ""),
                            remote_path=remote_linux_path,
                            ssh_port=int(data.get("transfer_port", 22)),
                            log_fn=sync_log
                        )

                        local_path = transfer_sftp(
                            ssh_host=data.get("transfer_host", data["host"]),
                            ssh_user=data.get("transfer_user", ""),
                            ssh_password=data.get("transfer_password", ""),
                            remote_path=remote_linux_path,
                            local_dir=local_dir,
                            log_fn=sync_log,
                            ssh_port=int(data.get("transfer_port", 22))
                        )
                        local_files.append((local_path, os.path.basename(local_path)))

                    elif transfer_mode == "smb":
                        sync_log("Transferindo via SMB/UNC...\n")
                        unc_path = data.get("smb_unc_prefix", "")
                        if unc_path:
                            full_unc = f"{unc_path}\\{bak_filename}"
                        else:
                            full_unc = remote_bak_path
                        local_path = transfer_smb(
                            remote_unc_path=full_unc,
                            local_dir=local_dir,
                            log_fn=sync_log
                        )
                        local_files.append((local_path, os.path.basename(local_path)))

                    else:
                        # Sem transferência — arquivo fica no servidor remoto
                        sync_log("Transferência desabilitada. Arquivo permanece no servidor de banco.\n")
                        # Tenta usar caminho UNC direto se acessível
                        local_files.append((remote_bak_path, bak_filename))

                    sync_log(f"Backup de [{db}] concluído.\n")

                except Exception as e:
                    sync_log(f"ERRO no backup de [{db}]: {str(e)}\n")
                    status_geral = "FAIL"

            end_time = datetime.datetime.now()
            duration = str(end_time - start_time)
            sync_log(f"\n=== FIM DO BACKUP LOCAL ===\n")
            sync_log(f"Fim: {end_time}\n")
            sync_log(f"Duração: {duration}\n")

            # Compactação se múltiplas bases
            linha = data.get("linha_produto", "")
            multiplo = len(databases) > 1

            if multiplo and local_files and data.get("transfer_mode", "none") != "none":
                zip_nome = f"{data.get('drive_folder', 'backup')}_{linha}" if linha else data.get('drive_folder', 'backup')
                zip_path = os.path.join(local_dir, f"{zip_nome}_{timestamp}.zip")
                sync_log(f"\nCompactando {len(local_files)} arquivo(s) em: {zip_path}\n")
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for caminho, nome_zip in local_files:
                        if os.path.exists(caminho):
                            zf.write(caminho, nome_zip)
                sync_log("Compactação concluída.\n")
                upload_file = zip_path
                upload_filename = f"{zip_nome}.zip"
            elif local_files and data.get("transfer_mode", "none") != "none":
                upload_file = local_files[0][0]
                # nome_base já segue o padrão: {drive_folder}_{linha}_{db}_{timestamp}.bak
                # Para o Drive, remove o timestamp do nome
                drive_folder = data.get("drive_folder", "")
                linha = data.get("linha_produto", "")
                db_name = databases[0] if databases else "backup"
                upload_filename = f"{drive_folder}_{linha}_{db_name}.bak" if linha else f"{drive_folder}_{db_name}.bak"
            else:
                upload_file = None
                upload_filename = ""

            # Upload para o Drive
            if (status_geral == "SUCCESS" and upload_file and os.path.exists(upload_file)
                    and data.get("drive_folder") and data.get("drive_subfolder")):
                sync_log("\n=== UPLOAD PARA O GOOGLE DRIVE ===\n")
                try:
                    drive_service = GoogleDriveService()
                    sync_log(f"Enviando: {upload_filename}...\n")

                    file_id, folder_link = drive_service.upload_backup_custom(
                        file_path=upload_file,
                        folder_level_1=data["drive_folder"],
                        folder_level_2=data["drive_subfolder"],
                        custom_file_name=upload_filename,
                        client_email=data.get("client_email")
                    )
                    sync_log(f"Upload concluído! ID: {file_id}\n")

                    # E-mail
                    client_email = data.get("client_email")
                    if client_email and folder_link:
                        sync_log(f"Enviando link via Mitte Pro para {client_email}...\n")
                        try:
                            resposta = send_mitte_email(
                                recipient_email=client_email,
                                client_name=data["drive_folder"],
                                folder_link=folder_link,
                                file_name=upload_filename,
                                template_type=data.get("template_type", "cancelamento")
                            )
                            sync_log(f"E-mail disparado! Resposta: {resposta}\n")

                            if 'error' not in str(resposta).lower():
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
                    sync_log(f"Erro no upload para o Drive: {str(e)}\n")
                    status_geral = "PARTIAL_SUCCESS"

            target = ", ".join(databases)
            add_history("BACKUP_MSSQL", target, status_geral)

    except Exception as e:
        append_log(f"\nERRO FATAL: {str(e)}\n")
        add_history("BACKUP_MSSQL", "ERRO", "FAIL")

    finally:
        set_running(False)
