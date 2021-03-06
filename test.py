#!/usr/bin/env python3

from glob import glob
import logging
import logging.config
import os

import tensorflow as tf
import numpy as np
from PIL import ImageFont

from config import get_logging_config, args, evaluation_logfile
from config import config as net_config
from paths import CKPT_ROOT
from tensorflow.python.profiler import model_analyzer
from tensorflow.python.profiler import option_builder

import matplotlib
matplotlib.use('Agg')

from vgg import VGG
from resnet import ResNet
from voc_loader import VOCLoader
from coco_loader import COCOLoader
from evaluation import Evaluation, COCOEval
from detector import Detector

slim = tf.contrib.slim

logging.config.dictConfig(get_logging_config(args.run_name))
log = logging.getLogger()


def main(argv=None):  # pylint: disable=unused-argument
    assert args.ckpt > 0 or args.batch_eval
    assert args.detect or args.segment, "Either detect or segment should be True"
    if args.trunk == 'resnet50':
        net = ResNet
        depth = 50
    if args.trunk == 'resnet101':
        net = ResNet
        depth = 101
    if args.trunk == 'vgg16':
        net = VGG
        depth = 16

    net = net(config=net_config, depth=depth, training=False)

    if args.dataset == 'voc07' or args.dataset == 'voc07+12':
        loader = VOCLoader('07', 'test')
    if args.dataset == 'voc12':
        loader = VOCLoader('12', 'val', segmentation=args.segment)
    if args.dataset == 'coco':
        loader = COCOLoader(args.split)

    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True,
                                          log_device_placement=False,
                                          gpu_options=tf.GPUOptions(allow_growth=True,
                                                                    per_process_gpu_memory_fraction=0.2))) as sess:
        if args.use_profile:
            profiler = model_analyzer.Profiler(graph=sess.graph)
            detector = Detector(sess, net, loader, net_config,
                                no_gt=args.no_seg_gt, profiler=profiler)
        else:
            detector = Detector(sess, net, loader, net_config,
                                no_gt=args.no_seg_gt)

        if args.dataset == 'coco':
            tester = COCOEval(detector, loader)
        else:
            tester = Evaluation(detector, loader, iou_thresh=args.voc_iou_thresh)
        if not args.batch_eval:
            detector.restore_from_ckpt(args.ckpt)
            tester.evaluate_network(args.ckpt)
        else:
            log.info('Evaluating %s' % args.run_name)
            ckpts_folder = CKPT_ROOT + args.run_name + '/'
            out_file = ckpts_folder + evaluation_logfile

            max_checked = get_last_eval(out_file)
            log.debug("Maximum checked ckpt is %i" % max_checked)
            with open(out_file, 'a') as f:
                start = max(args.min_ckpt, max_checked+1)
                ckpt_files = glob(ckpts_folder + '*.data*')
                folder_has_nums = np.array(list((map(filename2num, ckpt_files))), dtype='int')
                nums_available = sorted(folder_has_nums[folder_has_nums >= start])
                nums_to_eval = [nums_available[-1]]
                for n in reversed(nums_available):
                    if nums_to_eval[-1] - n >= args.step:
                        nums_to_eval.append(n)
                nums_to_eval.reverse()

                for ckpt in nums_to_eval:
                    log.info("Evaluation of ckpt %i" % ckpt)
                    tester.reset()
                    detector.restore_from_ckpt(ckpt)
                    res = tester.evaluate_network(ckpt)
                    f.write(res)
                    f.flush()

        if args.use_profile:
            profile_scope_builder = option_builder.ProfileOptionBuilder(
                # option_builder.ProfileOptionBuilder.trainable_variables_parameter()
            )
            profile_scope_builder.with_max_depth(4)
            profile_scope_builder.with_min_memory(int(2e6))
            profile_scope_builder.with_step(2)
            profile_scope_builder.select(['bytes'])
            # profile_scope_builder.with_node_names(show_name_regexes=['.*resnet.*', '.*ssd.*'])
            # profile_scope_builder.with_node_names(hide_name_regexes=['.*resnet.*', '.*ssd.*'])
            # profile_scope_builder.order_by('output_bytes')
            detector.profiler.profile_name_scope(profile_scope_builder.build())

            # profile_op_builder = option_builder.ProfileOptionBuilder()
            # profile_op_builder.select(['bytes'])
            # profile_op_builder.order_by('bytes')
            # profile_op_builder.with_max_depth(4)
            # profile_op_builder.with_step(200)
            # detector.profiler.profile_operations(profile_op_builder.build())
            #
            # # 统计内容为每个graph node的运行时间和占用内存
            # profile_graph_opts_builder = option_builder.ProfileOptionBuilder(
                # option_builder.ProfileOptionBuilder.time_and_memory()
            # )

            # # 输出方式为timeline
            # profile_graph_opts_builder.with_timeline_output(timeline_file='./model_test_profile.json')
            # profile_graph_opts_builder.with_step(200)
            # profile_graph_opts_builder.with_max_depth(2)
            # profile_graph_opts_builder.select(['bytes'])
            # profile_graph_opts_builder.order_by('bytes')
            # profile_graph_opts_builder.with_step(1)
            #
            # # 显示试图为graph view
            # detector.profiler.profile_graph(profile_graph_opts_builder.build())


def filename2num(filename):
    num = filename.split('/')[-1].split('-')[1].split('.')[0]
    num = int(num) / 1000
    return num


def num2filename(num):
    filename = 'model.ckpt-' + str(num) + '000.data-00000-of-00001'
    return filename


def get_last_eval(out_file):
    '''finds the last evaluated checkpoint'''
    max_num = 0
    if os.path.isfile(out_file):
        with open(out_file, 'r') as f:
            for line in f:
                max_num = int(line.split('\t')[0])
    return max_num


if __name__ == '__main__':
    tf.app.run()
