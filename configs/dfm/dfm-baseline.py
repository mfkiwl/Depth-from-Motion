model = dict(
    type='DfM',
    backbone=dict(
        type='LIGAResNet',  # TODO: check liga setting
        depth=34,
        num_stages=4,
        strides=(1, 2, 1, 1),  # sem [1, 2, 2, 2]
        dilations=(1, 1, 2, 4),  # sem [1, 1, 1, 1]
        out_indices=(0, 1, 2, 3),
        style='pytorch',
        frozen_stages=-1,
        norm_cfg=dict(type='BN', requires_grad=True),
        norm_eval=False,  # sem: True
        with_max_pool=False,
        block_with_final_relu=False,  # sem: True
        num_channels_factor=(1, 2, 2, 2),  # sem [1, 2, 4, 8]
        init_cfg=dict(type='Pretrained', checkpoint='torchvision://resnet34')),
    neck=dict(
        type='SPPUNetNeck',
        in_channels=[3, 64, 128, 128, 128],  # there is a hidden [3]
        start_level=2,
        sem_channels=[128, 32],
        stereo_channels=[32, 32],
        with_upconv=True,
        cat_img_feature=True,
        norm_cfg=dict(type='GN', num_groups=32, requires_grad=True)),
    neck_2d=dict(
        type='FPN',
        in_channels=[32],  # should be the same of sem_channels[-1]
        out_channels=64,
        start_level=0,
        add_extra_convs='on_output',
        num_outs=5),
    bbox_head_2d=None,
    backbone_stereo=dict(
        type='DfMBackbone',
        in_channels=32,  # should be the same of stereo_channels[-1]
        num_3dconvs=1,  # num of 3d conv layers before hourglass
        num_hg=1,  # num of hourglass blocks
        depth_cfg=dict(mode='UD', num_bins=288, depth_min=2, depth_max=59.6),
        voxel_cfg=dict(
            point_cloud_range=[2, -30.4, -3, 59.6, 30.4, 1],
            voxel_size=[0.2, 0.2, 0.2]),
        downsample_factor=4,
        sem_atten_feat=True,
        stereo_atten_feat=False,
        cv_channels=32,  # cost volume channels
        out_channels=32,  # out volume channels after conv/pool
        norm_cfg=dict(type='GN', num_groups=32, requires_grad=True)),
    depth_head=None,
    backbone_3d=dict(
        type='BEVHourglass',
        in_channels=160,  # 160 = 32 * 5
        out_channels=64,
        norm_cfg=dict(type='GN', num_groups=32, requires_grad=True)),
    bbox_head_3d=dict(
        type='LIGAAnchor3DHead',
        num_classes=3,
        in_channels=64,
        feat_channels=64,
        num_convs=2,
        use_direction_classifier=True,
        diff_rad_by_sin=True,
        dir_offset=0.7854,
        anchor_generator=dict(
            type='Anchor3DRangeGenerator',
            ranges=[[2, -30.4, -1.78, 59.6, 30.4, -1.78],
                    [2, -30.4, -0.6, 59.6, 30.4, -0.6],
                    [2, -30.4, -0.6, 59.6, 30.4, -0.6]],
            sizes=[[3.9, 1.6, 1.56], [0.8, 0.6, 1.73], [1.76, 0.6, 1.73]],
            rotations=[0, 1.57],
            reshape_out=False),
        bbox_coder=dict(type='DeltaXYZWLHRBBoxCoder'),
        loss_cls=dict(  # TODO: add weightedsmoothl1loss, iouloss
            type='FocalLoss',
            use_sigmoid=True,
            gamma=2.0,
            alpha=0.25,
            loss_weight=1.0),
        loss_bbox=dict(type='SmoothL1Loss', beta=1.0 / 9.0, loss_weight=2.0),
        loss_dir=dict(
            type='CrossEntropyLoss', use_sigmoid=False, loss_weight=0.2),
        norm_cfg=dict(type='GN', num_groups=32, requires_grad=True)),
    train_cfg=dict(
        assigner=[
            dict(  # for Car
                type='MaxIoUAssigner',
                iou_calculator=dict(type='BboxOverlapsNearest3D'),
                pos_iou_thr=0.6,
                neg_iou_thr=0.45,
                min_pos_iou=0.45,
                ignore_iof_thr=-1),
            dict(  # for Pedestrian
                type='MaxIoUAssigner',
                iou_calculator=dict(type='BboxOverlapsNearest3D'),
                pos_iou_thr=0.5,
                neg_iou_thr=0.35,
                min_pos_iou=0.35,
                ignore_iof_thr=-1),
            dict(  # for Cyclist
                type='MaxIoUAssigner',
                iou_calculator=dict(type='BboxOverlapsNearest3D'),
                pos_iou_thr=0.5,
                neg_iou_thr=0.35,
                min_pos_iou=0.35,
                ignore_iof_thr=-1)
        ],
        allowed_border=0,
        pos_weight=-1,
        debug=False),
    test_cfg=dict(
        use_rotate_nms=True,
        nms_across_levels=False,
        nms_thr=0.25,
        score_thr=0.1,
        min_bbox_size=0,
        nms_pre=4096,
        max_num=500))

dataset_type = 'KittiDataset'
data_root = 'data/kitti/'
class_names = ['Car', 'Pedestrian',
               'Cyclist']  # TODO: use van? deal with truncation
input_modality = dict(use_lidar=False, use_camera=True)
point_cloud_range = [2, -30.4, -3, 59.6, 30.4, 1]
img_norm_cfg = dict(
    mean=[123.675, 116.28, 103.53], std=[58.395, 57.12, 57.375], to_rgb=False)
# file_client_args = dict(backend='disk')
# Uncomment the following if use ceph or other file clients.
# See https://mmcv.readthedocs.io/en/latest/api.html#mmcv.fileio.FileClient
# for more details.
file_client_args = dict(
    backend='petrel',
    path_mapping=dict({
        '.data/kitti/':
        's3://openmmlab/datasets/detection3d/kitti/',
        'data/kitti/':
        's3://openmmlab/datasets/detection3d/kitti/'
    }))
# Explore RandomFlip3D Aug
train_pipeline = [
    dict(type='LoadAnnotations3D'),
    dict(
        type='VideoPipeline',
        num_ref_imgs=1,
        transforms=[
            dict(type='DepthPipeline', file_client_args=file_client_args),
            dict(type='RandomFlip3D', flip_ratio_bev_horizontal=0.5),
            dict(
                type='Resize3D',
                img_scale=[(1173, 352), (1387, 416)],
                keep_ratio=True,
                multiscale_mode='range'),
            dict(
                type='RandomCrop3D',
                crop_size=(320, 1280),
                rel_offset_h=(1, 1),
                rel_offset_w=(0.5, 0.5)),
            dict(type='Normalize', **img_norm_cfg),
            dict(type='Pad', size_divisor=32),
        ]),
    dict(type='ObjectRangeFilter', point_cloud_range=point_cloud_range),
    dict(type='DefaultFormatBundle3D', class_names=class_names),
    dict(
        type='Collect3D',
        keys=['img', 'gt_bboxes_3d', 'gt_labels_3d', 'depth_maps'])
]
test_pipeline = [
    dict(
        type='VideoPipeline',
        num_ref_imgs=1,
        random=False,
        transforms=[
            dict(
                type='LoadImageFromFileMono3D',
                file_client_args=file_client_args),
            dict(type='Resize3D', img_scale=(1242, 375), keep_ratio=True),
            dict(
                type='RandomCrop3D',
                crop_size=(320, 1280),
                rel_offset_h=(1, 1),
                rel_offset_w=(0.5, 0.5)),
            dict(type='Normalize', **img_norm_cfg),
            dict(type='Pad', size_divisor=32),
        ]),
    dict(
        type='DefaultFormatBundle3D',
        class_names=class_names,
        with_label=False),
    dict(type='Collect3D', keys=['img'])
]

data = dict(
    samples_per_gpu=1,
    workers_per_gpu=1,
    train=dict(
        type='RepeatDataset',
        times=2,
        dataset=dict(
            type=dataset_type,
            data_root=data_root,
            ann_file=data_root + 'kitti_infos_train.pkl',
            split='training',
            pts_prefix='velodyne_reduced',
            pipeline=train_pipeline,
            modality=input_modality,
            classes=class_names,
            test_mode=False)),
    val=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file=data_root + 'kitti_infos_val.pkl',
        split='training',
        pts_prefix='velodyne_reduced',
        pipeline=test_pipeline,
        modality=input_modality,
        classes=class_names,
        test_mode=True),
    test=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file=data_root + 'kitti_infos_val.pkl',
        split='training',
        pts_prefix='velodyne_reduced',
        pipeline=test_pipeline,
        modality=input_modality,
        classes=class_names,
        test_mode=True))

optimizer = dict(type='AdamW', lr=0.001, weight_decay=0.0001)
# although grad_clip is set in original code, it is not used
# optimizer_config = dict(grad_clip=dict(max_norm=35., norm_type=2))
# learning policy
lr_config = dict(
    policy='step',
    warmup='linear',  # cosine in original implementation
    warmup_iters=500,  # 464 for original implementation
    warmup_ratio=0.1,
    step=[25])
total_epochs = 30
runner = dict(type='EpochBasedRunner', max_epochs=total_epochs)

checkpoint_config = dict(interval=1, max_keep_ckpts=10)
log_config = dict(
    interval=50,
    hooks=[dict(type='TextLoggerHook'),
           dict(type='TensorboardLoggerHook')])
evaluation = dict(interval=1)
dist_params = dict(backend='nccl')
log_level = 'INFO'
load_from = None
resume_from = None
workflow = [('train', 1)]
