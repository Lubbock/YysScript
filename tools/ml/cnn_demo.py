import tempfile
from tensorflow.examples.tutorials.mnist import input_data
import tensorflow as tf


# 定义一个函数，用于初始化所有的权值 W
def weight_variable(shape):
    initial = tf.truncated_normal(shape, stddev=0.1)
    return tf.Variable(initial)


# 定义一个函数，用于初始化所有的偏置项 b
def bias_variable(shape):
    initial = tf.constant(0.1, shape=shape)
    return tf.Variable(initial)


# 定义一个函数，用于构建卷积层
def conv2d(x, W):
    return tf.nn.conv2d(x, W, strides=[1, 1, 1, 1], padding='SAME')


# 定义一个函数，用于构建池化层
def max_pool(x):
    return tf.nn.max_pool(x, ksize=[1, 2, 2, 1], strides=[1, 2, 2, 1], padding='SAME')


# cnn网络
def deepnn(x):
    print('deepnn')

    # x结构是[n,784] 展开为[n,28,28]
    # 灰度图只有一个通道，x_image第四位为1
    with tf.name_scope('reshape'):
        # 9410 没看懂
        x_image = tf.reshape(x, [-1, 28, 28, 1])
    # 第一个卷积层 讲28*28*1灰度图使用5*5*32核进行卷积

    with tf.name_scope('conv1'):
        # 初始化连接权值, 为了避免梯度消失权值使用正则分布进行初始化

        W_conv1 = weight_variable([5, 5, 1, 32])
        # 初始化偏置值, 这里使用的是0.1
        b_conv1 = bias_variable([32])
        # strides是卷积核移动的步幅. 采用SAME策略填充, 即使用相同值填充
        # def conv2d(x, W):
        #   tf.nn.conv2d(x, W, strides=[1, 1, 1, 1], padding='SAME')

        # h_conv1的结构为[n, 28, 28, 32]
        h_conv1 = tf.nn.relu(conv2d(x_image, W_conv1) + b_conv1)
    # 第一个池化层, 2*2最大值池化, 得到14*14矩阵
    with tf.name_scope('pool1'):
        h_pool1 = max_pool(h_conv1)
    # 第二个卷积层, 将28*28*32特征图使用5*5*64核进行卷积
    with tf.name_scope('conv2'):
        W_conv2 = weight_variable([5, 5, 32, 64])
        b_conv2 = bias_variable([64])
        # h_conv2的结构为[n, 14, 14, 64]
        h_conv2 = tf.nn.relu(conv2d(h_pool1, W_conv2) + b_conv2)

    # 第二个池化层, 2*2最大值池化, 得到7*7矩阵
    with tf.name_scope('pool2'):
        # h_pool2的结构为[n, 7, 7, 64]
        h_pool2 = max_pool(h_conv2)
    # 第一个全连接层, 将7*7*64特征矩阵用全连接层映射到1024个特征
    with tf.name_scope('fc1'):
        W_fc1 = weight_variable([7 * 7 * 64, 1024])
        b_fc1 = bias_variable([1024])
        h_pool2_flat = tf.reshape(h_pool2, [-1, 7 * 7 * 64])
        h_fc1 = tf.nn.relu(tf.matmul(h_pool2_flat, W_fc1) + b_fc1)

    # 使用dropout层避免过拟合
    # 即在训练过程中的一次迭代中, 随机选择一定比例的神经元不参与此次迭代
    # 参与迭代的概率值由keep_prob指定, keep_prob=1.0为使用整个网络
    with tf.name_scope('dropout'):
        keep_prob = tf.placeholder(tf.float32)
        h_fc1_drop = tf.nn.dropout(h_fc1, keep_prob)

        # 第二个全连接层, 将1024个特征映射到10个特征, 即10个分类的one-hot编码
        # one-hot编码是指用 `100`代替1, `010`代替2, `001`代替3... 的编码方式
    with tf.name_scope('fc2'):
        W_fc2 = weight_variable([1024, 10])
        b_fc2 = bias_variable([10])

    return y_conv, keep_prob


if __name__ == '__main__':
    print('Hello world')
    minst = input_data.read_data_sets("", one_hot=True)
    # x是输入层 28 28 被展开成784阶向量
    x = tf.placeholder(tf.float32, [None, 784])

    # one-hot表示10种分类
    y_ = tf.placeholder(tf.float32, [None, 10])

    # deepnn方法构建cnn ,y_conv是cnn的预测输出
    y_conv, keep_prob = deepnn(x)

    # 计算预测y_conv和标签t_交叉熵走损失函数
    with tf.name_scope('loss'):
        cross_entropy = tf.nn.softmax_cross_entropy_with_logits(label=y_, logits=y_conv)

    cross_entropy = tf.reduce_mean(cross_entropy)

    # 使用Adam优化算法，用最小化损失函数为目标
    with tf.name_scope('adam_optimizer'):
        train_step = tf.train.AdamOptimizer(1e-4).minimize(cross_entropy)

    # 计算精确度，正确分类样本数占测试样本数的比列，用于评估模型效果

    with tf.name_scope('accuracy'):
        correct_prediction = tf.equal(tf.argmax(y_conv, 1), tf.argmax(y_, 1))
        correct_prediction = tf.cast(correct_prediction, tf.float32)
    accuracy = tf.reduce_mean(correct_prediction)
