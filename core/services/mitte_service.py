import os
import hmac
import time
import hashlib
import requests
import json
from collections import OrderedDict
from core.config import MITTE_AUTH_KEY, MITTE_SECRET

MITTE_SENDER_CANCELAMENTO = 'Your App <cancelamento@yourdomain.com>'
MITTE_SENDER_PONTUAL = 'Your App <backup@yourdomain.com>'

TEMPLATE_CANCELAMENTO = 'your-cancellation-template-slug'
TEMPLATE_PONTUAL = 'your-backup-template-slug'

SUBJECT_CANCELAMENTO = 'Your App - Cancellation Notification #RESTRICTED'
SUBJECT_PONTUAL = 'Your App - Backup Notification #RESTRICTED'


def encode_param_without_escaping(key, value):
    if isinstance(value, list):
        return '&'.join([key + '[]=' + str(item) for item in value])
    else:
        if isinstance(value, dict):
            value = json.dumps(value)
    return "{key}={value}".format(key=key, value=value)


def send_mitte_email(recipient_email, client_name, folder_link, file_name, tech_email=None, template_type="cancelamento"):
    timestamp = int(time.time())
    auth_data = {
        "auth_key": MITTE_AUTH_KEY,
        "auth_timestamp": timestamp,
        "auth_version": "1.0",
    }

    lista_emails = [f"<{recipient_email}>"]
    if tech_email:
        lista_emails.append(f"<{tech_email}>")

    # Seleciona template e subject conforme tipo
    if template_type == "pontual":
        template_slug = TEMPLATE_PONTUAL
        subject = SUBJECT_PONTUAL
        sender = MITTE_SENDER_PONTUAL
    else:
        template_slug = TEMPLATE_CANCELAMENTO
        subject = SUBJECT_CANCELAMENTO
        sender = MITTE_SENDER_CANCELAMENTO

    data = {
        'recipient_list': lista_emails,
        'from': sender,
        'subject': subject,
        'use_template_subject': False,
        'template_slug': template_slug,
        'context': {
            'CLIENT_NAME': client_name,
            'FOLDER_LINK': folder_link
        },
        'activate_tracking': True,
        'expose_recipients_list': True
    }

    data.update(auth_data)
    params_dict = OrderedDict(sorted(data.items()))

    hmac_list = []
    for key, value in params_dict.items():
        hmac_list.append(encode_param_without_escaping(key, value))
    hmac_body = '&'.join(hmac_list)

    hmac_msg = 'POST\n/api/send_mail/template/\n' + hmac_body
    auth_signature_post_text = hmac.new(
        key=MITTE_SECRET.encode('utf-8'),
        msg=hmac_msg.encode('utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()

    url_post_text = f"https://www.mitte.pro/api/send_mail/template/?auth_key={MITTE_AUTH_KEY}&auth_timestamp={timestamp}&auth_version=1.0&auth_signature={auth_signature_post_text}"

    response = requests.post(url_post_text, json=params_dict)
    return response.json()
