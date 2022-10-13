# Copyright (c) 2019  PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import sys
sys.path.append("../")
import unittest
import paddle
from paddleslim.quant import quant_post_static
from static_case import StaticCase
sys.path.append("../demo")
from models import MobileNet
from layers import conv_bn_layer
import paddle.dataset.mnist as reader
import numpy as np
from paddle.fluid.contrib.slim.quantization import PostTrainingQuantization
from paddleslim.quant.rounding_optimizer import RoundingOptimizer
class TestRoundingOptimizer(StaticCase):
    
    def __init__(self, *args, **kwargs):
        super(TestRoundingOptimizer, self).__init__(*args, **kwargs)
        paddle.enable_static()
        self._gen_model()
    
    def _gen_model(self):
        image = paddle.static.data(
            name='image', shape=[None, 1, 28, 28], dtype='float32')
        label = paddle.static.data(name='label', shape=[None, 1], dtype='int64')
        model = MobileNet()
        out = model.net(input=image, class_dim=10)
        cost = paddle.nn.functional.loss.cross_entropy(input=out, label=label)
        avg_cost = paddle.mean(x=cost)
        acc_top1 = paddle.metric.accuracy(input=out, label=label, k=1)
        acc_top5 = paddle.metric.accuracy(input=out, label=label, k=5)
        optimizer = paddle.optimizer.Momentum(
            momentum=0.9,
            learning_rate=0.01,
            weight_decay=paddle.regularizer.L2Decay(4e-5))
        optimizer.minimize(avg_cost)
        main_prog = paddle.static.default_main_program()
        val_prog = main_prog.clone(for_test=True)
        place = paddle.CUDAPlace(0) if paddle.is_compiled_with_cuda(
        ) else paddle.CPUPlace()
        exe = paddle.static.Executor(place)
        exe.run(paddle.static.default_startup_program())
        def transform(x):
            return np.reshape(x, [1, 28, 28])
        train_dataset = paddle.vision.datasets.MNIST(
            mode='train', backend='cv2', transform=transform)
        test_dataset = paddle.vision.datasets.MNIST(
            mode='test', backend='cv2', transform=transform)
        train_loader = paddle.io.DataLoader(
            train_dataset,
            places=place,
            feed_list=[image, label],
            drop_last=True,
            batch_size=64,
            return_list=False)
        valid_loader = paddle.io.DataLoader(
            test_dataset,
            places=place,
            feed_list=[image, label],
            batch_size=64,
            return_list=False)
        def sample_generator_creator():
            def __reader__():
                for data in test_dataset:
                    image, label = data
                    yield image, label
            return __reader__
        def train(program):
            iter = 0
            for data in train_loader():
                cost, top1, top5 = exe.run(
                    program,
                    feed=data,
                    fetch_list=[avg_cost, acc_top1, acc_top5])
                iter += 1
                if iter % 100 == 0:
                    print(
                        'train iter={}, avg loss {}, acc_top1 {}, acc_top5 {}'.
                        format(iter, cost, top1, top5))
        train(main_prog)
        paddle.fluid.io.save_inference_model(
            dirname='./test_rounding_optimizer',
            feeded_var_names=[image.name, label.name],
            target_vars=[avg_cost, acc_top1, acc_top5],
            main_program=val_prog,
            executor=exe,
            model_filename='model',
            params_filename='params')
        self.post_training_quantization = PostTrainingQuantization(
                                    exe,
                                    './test_rounding_optimizer',
                                    sample_generator=sample_generator_creator(),
                                    model_filename='model',
                                    params_filename='params',
                                    batch_nums=10,
                                    algo='abs_max',
                                    bias_correction=True)
                                    
        self.post_training_quantization._load_model_data()
        self.post_training_quantization._collect_target_varnames()
        self.post_training_quantization._set_activation_persistable()
        for data in self.post_training_quantization._data_loader():
            self.post_training_quantization._executor.run(program=self.post_training_quantization._program,
                                feed=data,
                                fetch_list=self.post_training_quantization._fetch_list,
                                return_numpy=False,
                                scope=self.post_training_quantization._scope)
            self.post_training_quantization._sampling()
        self.post_training_quantization._reset_activation_persistable()
        
        self._blocks= [['image','batch_norm_26.tmp_4']]
        self._block_weights_names= [['conv1_weights', 'conv2_1_dw_weights', 'conv2_1_sep_weights', 'conv2_2_dw_weights', 'conv2_2_sep_weights', 'conv3_1_dw_weights', 'conv3_1_sep_weights','conv3_2_dw_weights','conv3_2_sep_weights'
                                ,'conv4_1_dw_weights','conv4_1_sep_weights','conv4_2_dw_weights','conv4_2_sep_weights','conv5_1_dw_weights','conv5_1_sep_weights','conv5_2_dw_weights','conv5_2_sep_weights','conv5_3_dw_weights','conv5_3_sep_weights','conv5_4_dw_weights','conv5_4_sep_weights','conv5_5_dw_weights','conv5_5_sep_weights','conv5_6_dw_weights','conv5_6_sep_weights','conv6_dw_weights','conv6_sep_weights']]
        
    
    def test_qdrop(self):
        rounding_optimizer = RoundingOptimizer(
                 data_loader=self.post_training_quantization._data_loader,
                 fp32_program=self.post_training_quantization._program,
                 feed_list=self.post_training_quantization._feed_list,
                 fetch_list=self.post_training_quantization._fetch_list,
                 exe=self.post_training_quantization._executor,
                 scope=self.post_training_quantization._scope,
                 place=self.post_training_quantization._place,
                 quantized_op_pairs=self.post_training_quantization._quantized_op_pairs,
                 weight_quantize_type=self.post_training_quantization._weight_quantize_type,
                 scale_dict=self.post_training_quantization._quantized_threshold,
                 blocks=self._blocks,
                 block_weights_names=self._block_weights_names,
                 round_type='qdrop',
                 num_iterations=self.post_training_quantization._batch_nums,
                 lr=self.post_training_quantization._learning_rate,
                 bias_correction=self.post_training_quantization._bias_correction,
                 epochs=10,
                 )
        rounding_optimizer._run()
        rounding_optimizer._get_layers()
        
if __name__ == '__main__':
    unittest.main()