import os
# 上传文件优化,文件名安全的意思
from werkzeug.utils import secure_filename
from flask import render_template, request, app, Flask

# os.path.dirname(__file__)获取的是app.py文件的路径，也就是在项目根目录中，然后把它放在images文件夹中
UPLOAD_PATH = os.path.join(os.path.dirname(__file__), 'files')

app = Flask(__name__,template_folder='.')


# Flask上传文件的实现
@app.route('/upload/', methods=['POST', 'GET'])
def upload():
    if request.method == 'GET':
        return render_template('upload.html')
    else:
        desc = request.form.get('desc')
        # 获取pichead文件对象
        pichead = request.files.get('pichead')
        print(desc)
        # 保存到服务器
        # save方法传完整的路径和文件名
        # pichead.save(os.path.join(UPLOAD_PATH,pichead.filename))
        # 上行可以进行优化,下行是对pichead文件名进行包装，保证文件名更安全。
        filename = secure_filename(pichead.filename)
        pichead.save(os.path.join(UPLOAD_PATH, filename))
        return '文件上传成功'


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
