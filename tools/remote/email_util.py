import poplib
import email
from email.parser import Parser
from email.header import decode_header
from email.utils import parseaddr
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# indent用于缩进显示:
def print_info(msg, indent=0):
    email_msg = []
    if indent == 0:
        # 邮件的From, To, Subject存在于根对象上:
        for header in ['From', 'To', 'Subject']:
            value = msg.get(header, '')
            if value:
                if header == 'Subject':
                    # 需要解码Subject字符串:
                    value = decode_str(value)
                else:
                    # 需要解码Email地址:
                    hdr, addr = parseaddr(value)
                    name = decode_str(hdr)
                    value = u'%s <%s>' % (name, addr)
            # print('%s%s: %s' % (' ' * indent, header, value))
    if (msg.is_multipart()):
        # 如果邮件对象是一个MIMEMultipart,
        # get_payload()返回list，包含所有的子对象:
        parts = msg.get_payload()
        for n, part in enumerate(parts):
            # print('%spart %s' % (' ' * indent, n))
            # print('%s--------------------' % (' ' * indent))
            # 递归打印每一个子对象:
            email_msg.append(print_info(part, indent + 1))
    else:
        # 邮件对象不是一个MIMEMultipart,
        # 就根据content_type判断:
        content_type = msg.get_content_type()
        if content_type == 'text/plain' or content_type == 'text/html':
            # 纯文本或HTML内容:
            content = msg.get_payload(decode=True)
            # 要检测文本编码:
            charset = guess_charset(msg)
            if charset:
                content = content.decode(charset)
            email_msg.append(content)
            # print('%sText: %s' % (' ' * indent, content + '...'))
        else:
            # 不是文本,作为附件处理:
            print('%sAttachment: %s' % (' ' * indent, content_type))

    return email_msg


def decode_str(s):
    value, charset = decode_header(s)[0]
    if charset:
        value = value.decode(charset)
    return value


def guess_charset(msg):
    # 先从msg对象获取编码:
    charset = msg.get_charset()
    if charset is None:
        # 如果获取不到，再从Content-Type字段获取:
        content_type = msg.get('Content-Type', '').lower()
        pos = content_type.find('charset=')
        if pos >= 0:
            charset = content_type[pos + 8:].strip()
    return charset


def get_email_size():
    pop3_server = "pop.qq.com"
    email_address = "2913408047@qq.com"
    password = "ulwacivedwogdegj"
    server = poplib.POP3(host=pop3_server)
    server.user(email_address)
    server.pass_(password)
    resp, mails, octets = server.list()
    index = len(mails)
    server.quit()
    return len(mails)


def getNewestEmail(email_size):
    pop3_server = "pop.qq.com"
    email_address = "2913408047@qq.com"
    password = "ulwacivedwogdegj"
    server = poplib.POP3(host=pop3_server)
    # 身份认证:
    server.user(email_address)
    server.pass_(password)
    # stat()返回邮件数量和占用空间:
    # print('Messages: %s. Size: %s' % server.stat())
    # list()返回所有邮件的编号:
    resp, mails, octets = server.list()
    # 可以查看返回的列表类似['1 82923', '2 2184', ...]
    # print(mails)
    # 获取最新一封邮件, 注意索引号从1开始:
    index = len(mails)
    print("检测到邮箱 " + str(index) + "封")
    config = ""
    if email_size < index:
        email_size = index
        resp, lines, octets = server.retr(index)
        # lines存储了邮件的原始文本的每一行,
        # 可以获得整个邮件的原始文本:
        msg_content = '\r\n'.join([line.decode("utf-8") for line in lines])
        # 稍后解析出邮件:
        msg = Parser().parsestr(msg_content)
        print_infos = print_info(msg)
        config = print_infos[0][0]
        print("检测类型 " + config)
    server.quit()
    return email_size, config


def send_report(img_path):
    try:
        sender = '2913408047@qq.com'
        receiver = '249725579@qq.com'
        smtpserver = 'smtp.qq.com'
        username = '2913408047@qq.com'
        password = 'ulwacivedwogdegj'
        mail_title = '主题：远程控制结果'
        # 创建一个带附件的实例
        message = MIMEMultipart()
        message['From'] = sender
        message['To'] = receiver
        message['Subject'] = Header(mail_title, 'utf-8')
        # 邮件正文内容
        message.attach(MIMEText('本次操作结果', 'plain', 'utf-8'))
        # 构造附件2（附件为JPG格式的图片）
        att2 = MIMEText(open(img_path, 'rb').read(), 'base64', 'utf-8')
        att2["Content-Type"] = 'application/octet-stream'
        att2["Content-Disposition"] = 'attachment; filename="123.jpg"'
        message.attach(att2)
        smtpObj = smtplib.SMTP_SSL(host=smtpserver,port=465)  # 注意：如果遇到发送失败的情况（提示远程主机拒接连接），这里要使用SMTP_SSL方法
        smtpObj.connect(smtpserver)
        smtpObj.login(username, password)
        smtpObj.sendmail(sender, receiver, message.as_string())
        print("邮件发送成功！！！")
        smtpObj.quit()
        return 1
    except Exception as err:
        print(err)
        return 0


if __name__ == "__main__":
    size, configs = getNewestEmail(2)
    print(size)
    print(configs)
