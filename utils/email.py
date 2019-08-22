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
