import os
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_email(subject, content, sender, recipients, smtp_server, smtp_port):

    server = smtplib.SMTP(smtp_server, smtp_port)
    #server.set_debuglevel(debug_level)
    server.ehlo()
    server.starttls()
    server.ehlo()

    priorities_dict = {'Low': '5', 'Normal': '3', 'High': '1'}

    priority = 'Normal'
    content_type ="plain"

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = ", ".join(recipients)
    msg['X-Priority'] = priorities_dict[priority]
    msg.attach(MIMEText(content, content_type))

    senderrs = server.sendmail(sender, recipients, msg.as_string())
    return senderrs


mandatory_template_fields= ('subject', 'sender', 'recipients', 'content')


def send_email_from_template_file(path_to_template):
    import configVar  # helps avoid circular imports

    resolved_path_to_template = configVar.config_vars.resolve_str(path_to_template)
    with open(resolved_path_to_template, 'r') as rfd:
        template_text = rfd.read()
        template_dict = eval(template_text)

    for name in mandatory_template_fields:
        assert name in template_dict.keys(), f"mandatory field {name} was not found in template {resolved_path_to_template}"

    senderrs = send_email(**template_dict)
    return senderrs
